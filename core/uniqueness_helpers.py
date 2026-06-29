"""Helpers for reusable identity fields after soft-delete and active-only uniqueness checks."""

from __future__ import annotations

import re

from django.utils import timezone

from .models import Agent, User


def _deleted_token(record_id):
    return timezone.now().strftime(f'%Y%m%d%H%M%S_{record_id}_')


def _archive_value(value, record_id, max_length):
    raw = str(value or '').strip()
    if not raw or raw.startswith('_deleted_'):
        return raw
    archived = f'_deleted_{_deleted_token(record_id)}{raw}'
    return archived[:max_length]


def release_user_unique_identity(user, *, save=True):
    """Free username/email/phone/employee_id so the same details can be re-used."""
    if not user:
        return user

    user.username = _archive_value(user.username, user.id, 150)
    user.email = _archive_value(user.email, user.id, 254)
    user.phone = _archive_value(user.phone, user.id, 15)
    user.employee_id = _archive_value(user.employee_id, user.id, 50)
    user.is_active = False

    if save:
        user.save(update_fields=[
            'username', 'email', 'phone', 'employee_id', 'is_active', 'updated_at',
        ])
    return user


def release_agent_unique_identity(agent, *, save=True):
    """Free agent contact/code fields and deactivate linked login user."""
    if not agent:
        return agent

    agent.agent_id = _archive_value(agent.agent_id, agent.id, 50)
    agent.email = _archive_value(agent.email, agent.id, 254) or None
    agent.phone = _archive_value(agent.phone, agent.id, 15)
    agent.status = 'blocked'

    if save:
        agent.save(update_fields=['agent_id', 'email', 'phone', 'status', 'updated_at'])

    if agent.user_id:
        release_user_unique_identity(agent.user, save=save)
    return agent


def active_users_qs():
    return User.objects.filter(is_active=True)


def active_agents_qs():
    return Agent.objects.filter(status='active')


def username_taken(username, *, exclude_user_id=None):
    username = str(username or '').strip()
    if not username:
        return False
    qs = User.objects.filter(username__iexact=username)
    if exclude_user_id:
        qs = qs.exclude(id=exclude_user_id)
    return qs.exists()


def active_username_taken(username, *, exclude_user_id=None):
    username = str(username or '').strip()
    if not username:
        return False
    qs = active_users_qs().filter(username__iexact=username)
    if exclude_user_id:
        qs = qs.exclude(id=exclude_user_id)
    return qs.exists()


def employee_id_taken(employee_id, *, exclude_user_id=None, active_only=True):
    employee_id = str(employee_id or '').strip()
    if not employee_id:
        return False
    qs = User.objects.filter(employee_id=employee_id)
    if active_only:
        qs = qs.filter(is_active=True)
    if exclude_user_id:
        qs = qs.exclude(id=exclude_user_id)
    return qs.exists()


def agent_id_taken(agent_id, *, exclude_agent_id=None, exclude_user_id=None, active_only=True):
    agent_id = str(agent_id or '').strip()
    if not agent_id:
        return False

    agent_qs = Agent.objects.filter(agent_id=agent_id)
    if active_only:
        agent_qs = agent_qs.filter(status='active')
    if exclude_agent_id:
        agent_qs = agent_qs.exclude(id=exclude_agent_id)
    if agent_qs.exists():
        return True

    user_qs = User.objects.filter(username__iexact=agent_id)
    if active_only:
        user_qs = user_qs.filter(is_active=True)
    if exclude_user_id:
        user_qs = user_qs.exclude(id=exclude_user_id)
    return user_qs.exists()


def active_email_taken(email, *, exclude_user_id=None):
    email = str(email or '').strip()
    if not email:
        return False
    qs = active_users_qs().filter(email__iexact=email)
    if exclude_user_id:
        qs = qs.exclude(id=exclude_user_id)
    return qs.exists()


def active_phone_taken(phone, *, exclude_user_id=None):
    phone = str(phone or '').strip()
    if not phone:
        return False
    qs = active_users_qs().filter(phone=phone)
    if exclude_user_id:
        qs = qs.exclude(id=exclude_user_id)
    return qs.exists()


def active_agent_email_taken(email, *, exclude_agent_id=None, exclude_user_id=None):
    email = str(email or '').strip()
    if not email:
        return False
    if active_agents_qs().filter(email__iexact=email).exclude(id=exclude_agent_id or 0).exists():
        return True
    return active_email_taken(email, exclude_user_id=exclude_user_id)


def active_agent_phone_taken(phone, *, exclude_agent_id=None, exclude_user_id=None):
    phone = str(phone or '').strip()
    if not phone:
        return False
    if active_agents_qs().filter(phone=phone).exclude(id=exclude_agent_id or 0).exists():
        return True
    return active_phone_taken(phone, exclude_user_id=exclude_user_id)


def generate_available_username(base_value, *, exclude_user_id=None, max_length=150):
    """Return a username that is not used by any account (including archived rows)."""
    seed = re.sub(r'[^a-zA-Z0-9._-]+', '', str(base_value or '').strip().lower()) or 'user'
    seed = seed[:max(1, max_length - 8)]
    candidate = seed
    counter = 1
    while username_taken(candidate, exclude_user_id=exclude_user_id):
        suffix = f'_{counter}'
        candidate = f'{seed[:max_length - len(suffix)]}{suffix}'
        counter += 1
    return candidate
