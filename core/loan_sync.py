import re
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Applicant, Loan, LoanApplication, User


LOAN_TO_APPLICATION_STATUS = {
    "draft": "New Entry",
    "new_entry": "New Entry",
    "waiting": "Waiting for Processing",
    "follow_up": "Required Follow-up",
    "approved": "Approved",
    "rejected": "Rejected",
    "disbursed": "Disbursed",
}

APPLICATION_TO_LOAN_STATUS = {
    "New Entry": "new_entry",
    "Waiting for Processing": "waiting",
    "Required Follow-up": "follow_up",
    "Approved": "approved",
    "Rejected": "rejected",
    "Disbursed": "disbursed",
}

ROLE_LABELS = {
    "admin": "Admin",
    "subadmin": "Partner",
    "employee": "Employee",
    "agent": "Channel Partner",
    "dsa": "DSA",
}

ASSIGNMENT_PATTERNS = (
    ("subadmin", re.compile(r"^Assigned By (?:SubAdmin|Partner):\s*(.+?)\s*->\s*Employee:\s*(.+?)(?:\s*\|\s*Remark:.*)?$", re.IGNORECASE)),
    ("admin", re.compile(r"^Assigned By Admin:\s*(.+?)\s*->\s*Employee:\s*(.+?)(?:\s*\|\s*Remark:.*)?$", re.IGNORECASE)),
)


def role_label(user_obj):
    if not user_obj:
        return "System"
    return ROLE_LABELS.get(user_obj.role, (user_obj.role or "User").title())


def loan_status_to_application_status(status_key):
    return LOAN_TO_APPLICATION_STATUS.get((status_key or "").strip().lower(), "New Entry")


def application_status_to_loan_status(status_key):
    return APPLICATION_TO_LOAN_STATUS.get((status_key or "").strip(), "new_entry")


def generate_unique_applicant_username(base_username):
    base = (base_username or "applicant").strip().lower()[:90]
    if not base:
        base = "applicant"

    candidate = base
    counter = 1
    while Applicant.objects.filter(username=candidate).exists():
        counter += 1
        candidate = f"{base}{counter}"
    return candidate


def normalize_gender(value):
    normalized = (value or "").strip().lower()
    if normalized in ["male", "female", "other"]:
        return normalized
    return "other"


def find_related_loan_application(loan_obj):
    if not loan_obj:
        return None

    base_qs = LoanApplication.objects.select_related(
        "applicant",
        "assigned_by",
        "assigned_employee",
        "assigned_agent",
    )

    created_at = loan_obj.created_at or timezone.now()
    window_start = created_at - timedelta(days=7)
    window_end = created_at + timedelta(days=7)

    # Prefer strict identity matches first.
    strict_filters = []
    if loan_obj.email and loan_obj.mobile_number:
        strict_filters.append({
            "applicant__email__iexact": loan_obj.email,
            "applicant__mobile": loan_obj.mobile_number,
        })
    if loan_obj.full_name and loan_obj.mobile_number:
        strict_filters.append({
            "applicant__full_name__iexact": loan_obj.full_name,
            "applicant__mobile": loan_obj.mobile_number,
        })
    if loan_obj.email and loan_obj.full_name:
        strict_filters.append({
            "applicant__email__iexact": loan_obj.email,
            "applicant__full_name__iexact": loan_obj.full_name,
        })
    if loan_obj.username:
        strict_filters.append({
            "applicant__username__iexact": loan_obj.username,
        })

    # Try in date-window first, then global fallback so older records still map.
    for filters in strict_filters:
        match = (
            base_qs.filter(**filters, created_at__gte=window_start, created_at__lte=window_end)
            .order_by("-created_at")
            .first()
        )
        if match:
            return match

    for filters in strict_filters:
        match = base_qs.filter(**filters).order_by("-created_at").first()
        if match:
            return match

    # Last-resort fuzzy OR match.
    queries = []
    if loan_obj.email:
        queries.append(Q(applicant__email__iexact=loan_obj.email))
    if loan_obj.mobile_number:
        queries.append(Q(applicant__mobile=loan_obj.mobile_number))
    if loan_obj.full_name:
        queries.append(Q(applicant__full_name__iexact=loan_obj.full_name))

    if not queries:
        return None

    condition = queries.pop(0)
    for query in queries:
        condition |= query

    return base_qs.filter(condition).order_by("-created_at").first()


def find_related_loan(loan_app):
    if not loan_app or not loan_app.applicant:
        return None

    applicant = loan_app.applicant
    base_qs = Loan.objects.select_related("created_by", "assigned_employee", "assigned_agent")
    created_at = loan_app.created_at or timezone.now()
    window_start = created_at - timedelta(days=7)
    window_end = created_at + timedelta(days=7)

    strict_filters = []
    if applicant.email and applicant.mobile:
        strict_filters.append({
            "email__iexact": applicant.email,
            "mobile_number": applicant.mobile,
        })
    if applicant.full_name and applicant.mobile:
        strict_filters.append({
            "full_name__iexact": applicant.full_name,
            "mobile_number": applicant.mobile,
        })
    if applicant.email and applicant.full_name:
        strict_filters.append({
            "email__iexact": applicant.email,
            "full_name__iexact": applicant.full_name,
        })
    if applicant.username:
        strict_filters.append({
            "username__iexact": applicant.username,
        })

    for filters in strict_filters:
        match = (
            base_qs.filter(**filters, created_at__gte=window_start, created_at__lte=window_end)
            .order_by("-created_at")
            .first()
        )
        if match:
            return match

    for filters in strict_filters:
        match = base_qs.filter(**filters).order_by("-created_at").first()
        if match:
            return match

    queries = []
    if applicant.email:
        queries.append(Q(email__iexact=applicant.email))
    if applicant.mobile:
        queries.append(Q(mobile_number=applicant.mobile))
    if applicant.full_name:
        queries.append(Q(full_name__iexact=applicant.full_name))

    if not queries:
        return None

    condition = queries.pop(0)
    for query in queries:
        condition |= query

    return base_qs.filter(condition).order_by("-created_at").first()


def resolve_user_by_role_and_name(role, raw_name):
    clean_name = (raw_name or "").strip()
    if not clean_name:
        return None

    base_qs = User.objects.filter(role=role)
    exact_match = base_qs.filter(
        Q(username__iexact=clean_name) |
        Q(email__iexact=clean_name) |
        Q(first_name__iexact=clean_name) |
        Q(last_name__iexact=clean_name)
    ).first()
    if exact_match:
        return exact_match

    parts = clean_name.split()
    if len(parts) >= 2:
        full_match = base_qs.filter(
            first_name__iexact=parts[0],
            last_name__iexact=" ".join(parts[1:]),
        ).first()
        if full_match:
            return full_match

    return base_qs.filter(
        Q(first_name__icontains=clean_name) | Q(last_name__icontains=clean_name)
    ).first()


def extract_assignment_context(loan_obj, fallback_application=None):
    remarks = str(getattr(loan_obj, "remarks", "") or "")
    lines = [line.strip() for line in remarks.splitlines() if line.strip()]

    for line in reversed(lines):
        for role, pattern in ASSIGNMENT_PATTERNS:
            match = pattern.match(line)
            if not match:
                continue
            assigner_name = match.group(1).strip()
            employee_name = match.group(2).strip()
            assigner_user = resolve_user_by_role_and_name(role, assigner_name)
            role_name = role_label(assigner_user) if assigner_user else ROLE_LABELS.get(role, role.title())
            return {
                "role": role,
                "line": line,
                "assigned_by_name": assigner_name,
                "assigned_by_user": assigner_user,
                "assigned_by_display": f"{role_name} - {assigner_name}",
                "assigned_employee_name": employee_name,
            }

    loan_app = fallback_application or find_related_loan_application(loan_obj)
    if loan_app and loan_app.assigned_by:
        assigner = loan_app.assigned_by
        assigner_name = assigner.get_full_name() or assigner.username
        assigned_employee_name = (
            loan_app.assigned_employee.get_full_name() or loan_app.assigned_employee.username
            if loan_app.assigned_employee else "-"
        )
        return {
            "role": assigner.role,
            "line": "",
            "assigned_by_name": assigner_name,
            "assigned_by_user": assigner,
            "assigned_by_display": f"{role_label(assigner)} - {assigner_name}",
            "assigned_employee_name": assigned_employee_name,
        }

    return {
        "role": "",
        "line": "",
        "assigned_by_name": "",
        "assigned_by_user": None,
        "assigned_by_display": "-",
        "assigned_employee_name": (
            loan_obj.assigned_employee.get_full_name() or loan_obj.assigned_employee.username
            if getattr(loan_obj, "assigned_employee", None) else "-"
        ),
    }


def _maybe_append_assignment_remark(loan_obj, loan_app):
    if not loan_obj or not loan_app or not loan_app.assigned_by or not loan_app.assigned_employee:
        return None

    assigner = loan_app.assigned_by
    if assigner.role not in ["admin", "subadmin"]:
        return None

    label = "Admin" if assigner.role == "admin" else "SubAdmin"
    assigner_name = assigner.get_full_name() or assigner.username
    employee_name = loan_app.assigned_employee.get_full_name() or loan_app.assigned_employee.username
    assignment_line = f"Assigned By {label}: {assigner_name} -> Employee: {employee_name}"

    existing_remarks = str(loan_obj.remarks or "")
    if assignment_line in existing_remarks:
        return existing_remarks

    return f"{existing_remarks}\n{assignment_line}".strip() if existing_remarks else assignment_line


def sync_loan_to_application(loan_obj, assigned_by_user=None, create_if_missing=True):
    if not loan_obj:
        return None

    loan_app = find_related_loan_application(loan_obj)
    mapped_status = loan_status_to_application_status(loan_obj.status)
    assignment_context = extract_assignment_context(loan_obj, loan_app)
    assigner = assigned_by_user or assignment_context.get("assigned_by_user")

    if not loan_app and not create_if_missing:
        return None

    if not loan_app:
        base_username = (loan_obj.email or f"loan{loan_obj.id}").split("@")[0]
        applicant = Applicant.objects.create(
            role="agent" if loan_obj.applicant_type == "agent" else "employee",
            full_name=loan_obj.full_name or f"Applicant {loan_obj.id}",
            username=generate_unique_applicant_username(base_username),
            mobile=loan_obj.mobile_number or f"000000{loan_obj.id % 10000:04d}",
            email=loan_obj.email or f"loan{loan_obj.id}@example.com",
            city=loan_obj.city or "NA",
            state=loan_obj.state or "NA",
            pin_code=loan_obj.pin_code or "000000",
            gender=normalize_gender(getattr(loan_obj, "gender", None)),
            loan_type=loan_obj.loan_type or None,
            loan_amount=loan_obj.loan_amount or None,
            tenure_months=loan_obj.tenure_months or None,
            interest_rate=loan_obj.interest_rate or None,
            loan_purpose=loan_obj.loan_purpose or None,
            bank_name=loan_obj.bank_name or None,
            bank_type=loan_obj.bank_type or None,
            account_number=loan_obj.bank_account_number or None,
            ifsc_code=loan_obj.bank_ifsc_code or None,
        )

        loan_app = LoanApplication.objects.create(
            applicant=applicant,
            status=mapped_status,
            assigned_employee=loan_obj.assigned_employee,
            assigned_agent=loan_obj.assigned_agent,
            assigned_at=loan_obj.assigned_at if mapped_status in ["Waiting for Processing", "Required Follow-up"] else None,
            assigned_by=assigner,
            sm_name=loan_obj.sm_name,
            sm_phone_number=loan_obj.sm_phone_number,
            sm_email=loan_obj.sm_email,
            is_sm_signed=bool(loan_obj.is_sm_signed),
            sm_signed_at=loan_obj.sm_signed_at,
        )
        return loan_app

    update_fields = []
    applicant = loan_app.applicant

    applicant_updates = {
        "full_name": loan_obj.full_name or applicant.full_name,
        "mobile": loan_obj.mobile_number or applicant.mobile,
        "email": loan_obj.email or applicant.email,
        "city": loan_obj.city or applicant.city,
        "state": loan_obj.state or applicant.state,
        "pin_code": loan_obj.pin_code or applicant.pin_code,
        "loan_type": loan_obj.loan_type or applicant.loan_type,
        "loan_amount": loan_obj.loan_amount or applicant.loan_amount,
        "tenure_months": loan_obj.tenure_months or applicant.tenure_months,
        "interest_rate": loan_obj.interest_rate if loan_obj.interest_rate is not None else applicant.interest_rate,
        "loan_purpose": loan_obj.loan_purpose or applicant.loan_purpose,
        "bank_name": loan_obj.bank_name or applicant.bank_name,
        "bank_type": loan_obj.bank_type or applicant.bank_type,
        "account_number": loan_obj.bank_account_number or applicant.account_number,
        "ifsc_code": loan_obj.bank_ifsc_code or applicant.ifsc_code,
    }
    applicant_changed = False
    for field_name, field_value in applicant_updates.items():
        if getattr(applicant, field_name) != field_value:
            setattr(applicant, field_name, field_value)
            applicant_changed = True
    if applicant_changed:
        applicant.save()

    if loan_app.status != mapped_status:
        loan_app.status = mapped_status
        update_fields.append("status")

    if loan_app.assigned_employee_id != loan_obj.assigned_employee_id:
        loan_app.assigned_employee = loan_obj.assigned_employee
        update_fields.append("assigned_employee")

    if loan_app.assigned_agent_id != loan_obj.assigned_agent_id:
        loan_app.assigned_agent = loan_obj.assigned_agent
        update_fields.append("assigned_agent")

    effective_assigned_at = loan_obj.assigned_at
    if mapped_status not in ["Waiting for Processing", "Required Follow-up"]:
        effective_assigned_at = loan_app.assigned_at or loan_obj.assigned_at
    elif not effective_assigned_at and (loan_obj.assigned_employee_id or loan_obj.assigned_agent_id):
        effective_assigned_at = timezone.now()

    if loan_app.assigned_at != effective_assigned_at:
        loan_app.assigned_at = effective_assigned_at
        update_fields.append("assigned_at")

    if assigner and loan_app.assigned_by_id != assigner.id:
        loan_app.assigned_by = assigner
        update_fields.append("assigned_by")

    if loan_app.sm_name != loan_obj.sm_name:
        loan_app.sm_name = loan_obj.sm_name
        update_fields.append("sm_name")

    if loan_app.sm_phone_number != loan_obj.sm_phone_number:
        loan_app.sm_phone_number = loan_obj.sm_phone_number
        update_fields.append("sm_phone_number")

    if loan_app.sm_email != loan_obj.sm_email:
        loan_app.sm_email = loan_obj.sm_email
        update_fields.append("sm_email")

    if bool(loan_app.is_sm_signed) != bool(loan_obj.is_sm_signed):
        loan_app.is_sm_signed = bool(loan_obj.is_sm_signed)
        update_fields.append("is_sm_signed")

    if loan_app.sm_signed_at != loan_obj.sm_signed_at:
        loan_app.sm_signed_at = loan_obj.sm_signed_at
        update_fields.append("sm_signed_at")

    if update_fields:
        loan_app._skip_sync_to_loan = True
        loan_app.save(update_fields=update_fields + ["updated_at"])

    return loan_app


def sync_application_to_loan(loan_app):
    if not loan_app or not getattr(loan_app, "applicant", None):
        return None

    loan_obj = find_related_loan(loan_app)
    if not loan_obj:
        return None

    applicant = loan_app.applicant
    mapped_status = application_status_to_loan_status(loan_app.status)
    effective_assigned_at = loan_app.assigned_at
    if mapped_status in ["waiting", "follow_up"] and not effective_assigned_at and loan_app.assigned_employee_id:
        effective_assigned_at = timezone.now()

    updated_remarks = _maybe_append_assignment_remark(loan_obj, loan_app)

    update_values = {
        "full_name": applicant.full_name or loan_obj.full_name,
        "mobile_number": applicant.mobile or loan_obj.mobile_number,
        "email": applicant.email or loan_obj.email,
        "city": applicant.city or loan_obj.city,
        "state": applicant.state or loan_obj.state,
        "pin_code": applicant.pin_code or loan_obj.pin_code,
        "loan_type": applicant.loan_type or loan_obj.loan_type,
        "loan_amount": applicant.loan_amount or loan_obj.loan_amount,
        "tenure_months": applicant.tenure_months or loan_obj.tenure_months,
        "interest_rate": applicant.interest_rate if applicant.interest_rate is not None else loan_obj.interest_rate,
        "loan_purpose": applicant.loan_purpose or loan_obj.loan_purpose,
        "bank_name": applicant.bank_name or loan_obj.bank_name,
        "bank_type": applicant.bank_type or loan_obj.bank_type,
        "bank_account_number": applicant.account_number or loan_obj.bank_account_number,
        "bank_ifsc_code": applicant.ifsc_code or loan_obj.bank_ifsc_code,
        "status": mapped_status,
        "assigned_employee": loan_app.assigned_employee,
        "assigned_agent": loan_app.assigned_agent,
        "assigned_at": effective_assigned_at,
        "action_taken_at": timezone.now() if mapped_status in ["approved", "rejected", "disbursed"] else loan_obj.action_taken_at,
        "sm_name": loan_app.sm_name,
        "sm_phone_number": loan_app.sm_phone_number,
        "sm_email": loan_app.sm_email,
        "is_sm_signed": bool(loan_app.is_sm_signed),
        "sm_signed_at": loan_app.sm_signed_at,
        "updated_at": timezone.now(),
    }

    if updated_remarks is not None:
        update_values["remarks"] = updated_remarks

    Loan.objects.filter(id=loan_obj.id).update(**update_values)
    loan_obj.refresh_from_db()
    return loan_obj
