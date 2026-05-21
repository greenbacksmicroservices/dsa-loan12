import re

from django.db import transaction

from .models import Agent, User


def _next_serial(existing_values, prefix, fallback_serials=None):
    max_serial = -1
    for value in existing_values:
        raw = str(value or "").strip().upper()
        if not raw.startswith(prefix):
            continue
        match = re.search(r"(\d+)$", raw)
        if not match:
            continue
        try:
            serial = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if serial > max_serial:
            max_serial = serial
    for serial in fallback_serials or []:
        try:
            parsed = int(serial)
        except (TypeError, ValueError):
            continue
        if parsed > max_serial:
            max_serial = parsed
    return max_serial + 1


def format_sequence_id(prefix, serial):
    return f"{prefix}{serial:04d}"


def normalize_manual_loan_id(raw_value):
    value = str(raw_value or "").strip()
    if not value:
        return ""
    return re.sub(r"\s+", "", value).upper()


def display_manual_loan_id(loan_obj, empty_label="Pending Manual ID"):
    value = normalize_manual_loan_id(getattr(loan_obj, "user_id", ""))
    return value or empty_label


@transaction.atomic
def generate_user_sequence_id(role):
    role = str(role or "").strip().lower()
    prefix_map = {
        "employee": "EDC-EMP-",
        "subadmin": "EDC-P-",
    }
    if role not in prefix_map:
        raise ValueError(f"Unsupported role for user sequence id: {role}")

    prefix = prefix_map[role]
    rows = list(
        User.objects.select_for_update()
        .filter(role=role)
        .values("id", "employee_id")
    )
    values = [row.get("employee_id") for row in rows if row.get("employee_id")]
    fallback_serials = [row.get("id") for row in rows if not row.get("employee_id")]
    serial = _next_serial(values, prefix, fallback_serials=fallback_serials)
    return format_sequence_id(prefix, serial)


@transaction.atomic
def generate_agent_sequence_id(is_sub_channel_partner=False):
    prefix = "EDC-SCP-" if is_sub_channel_partner else "EDC-CP-"
    rows = list(
        Agent.objects.select_for_update()
        .values("id", "agent_id", "created_by__role")
    )
    values = [row.get("agent_id") for row in rows if row.get("agent_id")]
    if is_sub_channel_partner:
        fallback_serials = [row.get("id") for row in rows if not row.get("agent_id") and row.get("created_by__role") == "subadmin"]
    else:
        fallback_serials = [row.get("id") for row in rows if not row.get("agent_id") and row.get("created_by__role") != "subadmin"]
    serial = _next_serial(values, prefix, fallback_serials=fallback_serials)
    return format_sequence_id(prefix, serial)
