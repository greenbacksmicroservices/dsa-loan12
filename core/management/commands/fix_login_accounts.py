from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Agent, User


DEFAULT_PASSWORD = "123456789"


class Command(BaseCommand):
    help = "Create/update required admin, subadmin, employee, and agent login accounts."

    accounts = [
        {
            "email": "admin@gmail.com",
            "username": "admin",
            "role": "admin",
            "first_name": "Admin",
            "last_name": "User",
            "is_staff": True,
            "is_superuser": True,
        },
        {
            "email": "subadmin@gmail.com",
            "username": "subadmin",
            "role": "subadmin",
            "first_name": "Sub",
            "last_name": "Admin",
            "is_staff": False,
            "is_superuser": False,
        },
        {
            "email": "emp12@gmail.com",
            "username": "emp12",
            "role": "employee",
            "first_name": "Employee",
            "last_name": "User",
            "is_staff": False,
            "is_superuser": False,
        },
        {
            "email": "agent12@gmail.com",
            "username": "agent12",
            "role": "agent",
            "first_name": "Agent",
            "last_name": "User",
            "is_staff": False,
            "is_superuser": False,
        },
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=DEFAULT_PASSWORD,
            help="Password to set for all listed accounts (default: 123456789).",
        )

    def _unique_username(self, preferred, current_user=None):
        base = (preferred or "user").strip()
        if not base:
            base = "user"

        candidate = base
        index = 1
        while User.objects.filter(username=candidate).exclude(
            id=getattr(current_user, "id", None)
        ).exists():
            candidate = f"{base}{index}"
            index += 1
        return candidate

    def _ensure_user(self, account, password):
        email = account["email"].strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        created = False

        if user is None:
            created = True
            username = self._unique_username(account["username"])
            user = User(
                username=username,
                email=email,
            )
        else:
            if not user.username:
                user.username = self._unique_username(account["username"], current_user=user)

        user.first_name = account["first_name"]
        user.last_name = account["last_name"]
        user.role = account["role"]
        user.is_active = True
        user.is_staff = account["is_staff"]
        user.is_superuser = account["is_superuser"]
        user.set_password(password)
        user.save()

        return user, created

    def _build_agent_id(self, user, current_agent=None):
        base = f"AGENT{user.id:06d}"
        candidate = base
        index = 1
        while Agent.objects.filter(agent_id=candidate).exclude(
            id=getattr(current_agent, "id", None)
        ).exists():
            candidate = f"{base}{index}"
            index += 1
        return candidate

    def _ensure_agent_profile(self, agent_user, admin_user=None):
        profile = Agent.objects.filter(user=agent_user).first()
        if profile is None:
            profile = Agent.objects.filter(email__iexact=agent_user.email).first()

        created = False
        if profile is None:
            created = True
            profile = Agent(user=agent_user)
        elif profile.user_id != agent_user.id:
            profile.user = agent_user

        profile.name = profile.name or (agent_user.get_full_name().strip() or "Agent User")
        profile.email = agent_user.email
        profile.phone = profile.phone or "9999999999"
        profile.status = "active"
        profile.agent_id = self._build_agent_id(agent_user, current_agent=profile)
        if profile.created_by_id is None and admin_user is not None:
            profile.created_by = admin_user
        profile.save()
        return created, profile

    @transaction.atomic
    def handle(self, *args, **options):
        password = options["password"]
        summary = []
        users = {}

        for account in self.accounts:
            user, created = self._ensure_user(account, password)
            users[account["role"]] = user
            summary.append(
                {
                    "email": account["email"],
                    "role": account["role"],
                    "username": user.username,
                    "status": "created" if created else "updated",
                }
            )

        agent_created, agent_profile = self._ensure_agent_profile(
            users["agent"], admin_user=users.get("admin")
        )

        self.stdout.write(self.style.SUCCESS("Login accounts configured successfully."))
        self.stdout.write("")
        for item in summary:
            self.stdout.write(
                f"- {item['email']} ({item['role']}): {item['status']} | username={item['username']}"
            )
        self.stdout.write("")
        self.stdout.write(f"Password for all above users: {password}")
        self.stdout.write(
            f"Agent profile: {'created' if agent_created else 'updated'} | agent_id={agent_profile.agent_id}"
        )
