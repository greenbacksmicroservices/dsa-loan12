from django.conf import settings
from django.core.mail import send_mail


ROLE_LABELS = {
    "admin": "Admin",
    "subadmin": "Partner",
    "employee": "Employee",
    "agent": "Channel Partner",
    "dsa": "DSA",
}


def role_display(role):
    raw_role = str(role or "").strip().lower()
    return ROLE_LABELS.get(raw_role, raw_role.title() if raw_role else "User")


def send_account_credentials_email(*, request, email, full_name, username, password, role):
    """
    Send a simple credentials email in English to the newly created user.
    Returns (sent: bool, detail: str).
    """
    recipient = str(email or "").strip()
    if not recipient:
        return False, "Email address not available"

    login_url = request.build_absolute_uri("/login/") if request else "/login/"
    display_name = str(full_name or "").strip() or username or "User"
    role_name = role_display(role)

    subject = f"Your {role_name} Account Credentials"
    message = (
        f"Hello {display_name},\n\n"
        f"Your account has been created successfully on the loan management portal.\n\n"
        f"Role: {role_name}\n"
        f"Mail ID / Email: {recipient}\n"
        f"User Name: {username}\n"
        f"Password: {password}\n"
        f"Login URL: {login_url}\n\n"
        "You can sign in with your Mail ID or User Name. Please change your password after your first login.\n\n"
        f"Regards,\n{getattr(settings, 'DEFAULT_FROM_EMAIL', 'Support Team')}"
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[recipient],
            fail_silently=False,
        )
        return True, "Credentials email sent successfully"
    except Exception as exc:
        return False, str(exc)
