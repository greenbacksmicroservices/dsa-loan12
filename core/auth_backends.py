"""Authentication backends supporting email, username, employee ID, and agent ID."""

from django.contrib.auth.backends import ModelBackend

from .models import Agent, User


class EmailUsernameEmployeeAgentBackend(ModelBackend):
    """Authenticate using username, email, employee_id, or channel partner agent_id."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not password:
            return None

        login_value = (username or kwargs.get('email') or '').strip()
        if not login_value:
            return None

        user = self._resolve_user(login_value)
        if user is None:
            return None
        if not user.is_active:
            return None
        if user.check_password(password):
            return user
        return None

    def _resolve_user(self, login_value):
        if '@' in login_value:
            user = User.objects.filter(email__iexact=login_value).first()
            if user:
                return user

        user = User.objects.filter(username__iexact=login_value).first()
        if user:
            return user

        user = User.objects.filter(employee_id__iexact=login_value, is_active=True).first()
        if user:
            return user

        agent = Agent.objects.filter(agent_id__iexact=login_value).select_related('user').first()
        if agent and agent.user:
            return agent.user

        return None
