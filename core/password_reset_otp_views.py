import secrets
import string
import time
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

OTP_VALIDITY_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 30


def _normalized_email(email):
    return str(email or '').strip().lower()


def _otp_cache_key(email):
    return f"password_reset_otp::{_normalized_email(email)}"


def _otp_cooldown_key(email):
    return f"password_reset_otp_cooldown::{_normalized_email(email)}"


def _mask_email(email):
    local, at, domain = str(email or '').partition('@')
    if not at:
        return email
    if len(local) <= 2:
        hidden_local = local[0] + '*'
    else:
        hidden_local = local[:2] + ('*' * max(1, len(local) - 2))
    return f"{hidden_local}@{domain}"


def _generate_otp():
    return f"{secrets.randbelow(1_000_000):06d}"


def _generate_password(length=10):
    alphabet = string.ascii_letters + string.digits
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return f"{password}{secrets.choice('@#%*')}"


def _verify_url(email):
    return f"{reverse('password_reset_verify')}?email={quote(_normalized_email(email))}"


def _cooldown_remaining_seconds(email):
    sent_at = cache.get(_otp_cooldown_key(email))
    if not sent_at:
        return 0
    elapsed = int(time.time() - float(sent_at))
    remaining = OTP_RESEND_COOLDOWN_SECONDS - elapsed
    return max(0, remaining)


def _save_otp(email, user_id, otp):
    cache.set(
        _otp_cache_key(email),
        {
            'otp': otp,
            'user_id': user_id,
            'attempts': 0,
            'sent_at': int(time.time()),
        },
        timeout=OTP_VALIDITY_SECONDS,
    )
    cache.set(_otp_cooldown_key(email), int(time.time()), timeout=OTP_RESEND_COOLDOWN_SECONDS)


def _send_otp_email(to_email, otp_code):
    subject = 'DSA Loans Password Reset OTP'
    message = (
        "Your OTP for password reset is:\n\n"
        f"{otp_code}\n\n"
        f"This OTP is valid for {OTP_VALIDITY_SECONDS // 60} minutes.\n"
        "If you did not request this, please ignore this email."
    )
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to_email],
        fail_silently=False,
    )


def _send_new_password_email(to_email, new_password):
    subject = 'DSA Loans - Your New Password'
    message = (
        "Your password has been reset successfully.\n\n"
        f"New Password: {new_password}\n\n"
        "Please login and change this password immediately from your profile settings."
    )
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to_email],
        fail_silently=False,
    )


@require_http_methods(["GET", "POST"])
def password_reset_otp_request(request):
    User = get_user_model()

    if request.method == 'POST':
        email = _normalized_email(request.POST.get('email'))
        if not email:
            messages.error(request, 'Please enter your registered email.')
            return render(request, 'core/auth/password_reset_otp_form.html', {'email': ''})

        request.session['password_reset_email'] = email

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user:
            remaining = _cooldown_remaining_seconds(email)
            if remaining > 0:
                messages.warning(request, f'Please wait {remaining} seconds before requesting another OTP.')
                return redirect(_verify_url(email))
            try:
                otp_code = _generate_otp()
                _save_otp(email, user.id, otp_code)
                _send_otp_email(user.email, otp_code)
            except Exception as exc:
                messages.error(request, f'Could not send OTP email right now: {exc}')
                return render(request, 'core/auth/password_reset_otp_form.html', {'email': email})

        # Generic response to avoid account enumeration.
        messages.success(request, 'If the email is registered, OTP has been sent successfully.')
        return redirect(_verify_url(email))

    return render(request, 'core/auth/password_reset_otp_form.html', {
        'email': request.session.get('password_reset_email', ''),
    })


@require_http_methods(["GET", "POST"])
def password_reset_otp_verify(request):
    User = get_user_model()

    email = _normalized_email(
        request.POST.get('email')
        or request.GET.get('email')
        or request.session.get('password_reset_email')
    )
    if not email:
        messages.info(request, 'Please enter email first.')
        return redirect('password_reset')

    request.session['password_reset_email'] = email

    if request.method == 'POST':
        action = request.POST.get('action', 'verify')
        user = User.objects.filter(email__iexact=email, is_active=True).first()

        if action == 'resend':
            if user:
                remaining = _cooldown_remaining_seconds(email)
                if remaining > 0:
                    messages.warning(request, f'Please wait {remaining} seconds before resending OTP.')
                else:
                    try:
                        otp_code = _generate_otp()
                        _save_otp(email, user.id, otp_code)
                        _send_otp_email(user.email, otp_code)
                        messages.success(request, 'New OTP sent to your email.')
                    except Exception as exc:
                        messages.error(request, f'Failed to resend OTP: {exc}')
            else:
                messages.success(request, 'If the email is registered, OTP has been sent successfully.')

            return redirect(_verify_url(email))

        otp_input = str(request.POST.get('otp', '')).strip()
        if len(otp_input) != 6 or not otp_input.isdigit():
            messages.error(request, 'Please enter a valid 6-digit OTP.')
            return redirect(_verify_url(email))

        otp_payload = cache.get(_otp_cache_key(email))
        if not otp_payload:
            messages.error(request, 'OTP expired or invalid. Please request a new OTP.')
            return redirect(_verify_url(email))

        if otp_payload.get('otp') != otp_input:
            attempts = int(otp_payload.get('attempts', 0)) + 1
            if attempts >= OTP_MAX_ATTEMPTS:
                cache.delete(_otp_cache_key(email))
                messages.error(request, 'Too many incorrect attempts. Please request a new OTP.')
            else:
                otp_payload['attempts'] = attempts
                cache.set(_otp_cache_key(email), otp_payload, timeout=OTP_VALIDITY_SECONDS)
                messages.error(request, f'Incorrect OTP. Attempts left: {OTP_MAX_ATTEMPTS - attempts}')
            return redirect(_verify_url(email))

        if not user or int(otp_payload.get('user_id') or 0) != user.id:
            cache.delete(_otp_cache_key(email))
            messages.error(request, 'Unable to verify this OTP. Please request a new OTP.')
            return redirect('password_reset')

        new_password = _generate_password()
        old_password_hash = user.password
        user.set_password(new_password)
        user.save(update_fields=['password'])

        try:
            _send_new_password_email(user.email, new_password)
        except Exception as exc:
            user.password = old_password_hash
            user.save(update_fields=['password'])
            messages.error(request, f'OTP verified but email sending failed. Please try again. ({exc})')
            return redirect(_verify_url(email))

        cache.delete(_otp_cache_key(email))
        cache.delete(_otp_cooldown_key(email))
        request.session.pop('password_reset_email', None)
        request.session['password_reset_success_email'] = email
        return redirect('password_reset_done')

    return render(request, 'core/auth/password_reset_otp_verify.html', {
        'email': email,
        'masked_email': _mask_email(email),
        'cooldown_remaining': _cooldown_remaining_seconds(email),
        'otp_validity_seconds': OTP_VALIDITY_SECONDS,
    })


@require_http_methods(["GET"])
def password_reset_otp_done(request):
    email = request.session.get('password_reset_success_email', '')
    return render(request, 'core/auth/password_reset_otp_done.html', {
        'email': email,
        'masked_email': _mask_email(email),
    })
