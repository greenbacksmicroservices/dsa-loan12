"""Display helpers for workflow-only loan applications.

Dashboard cards count both legacy ``Loan`` records and newer
``LoanApplication`` workflow records. These helpers let list pages render the
workflow-only records with the same shape as legacy rows.
"""

from types import SimpleNamespace

from .loan_helpers import display_loan_id, get_submitted_processed_display, resolve_stored_loan_id
from .loan_sync import find_related_loan
from .models import Applicant, Loan
from .updated_document_utils import (
    UPDATED_DOCUMENT_STATUS_KEY,
    application_has_updated_documents,
)

FOLLOW_UP_PENDING_LABEL = "Follow Up"
PENDING_DOCUMENT_CLEARED_LABEL = "Pending Document Cleared"

APP_STATUS_TO_LOAN_KEY = {
    "New Entry": "new_entry",
    "Waiting for Processing": "waiting",
    "Required Follow-up": "follow_up",
    "Approved": "approved",
    "Rejected": "rejected",
    "Disbursed": "disbursed",
}


def has_revert_marker(raw_text):
    return "revert remark" in str(raw_text or "").lower()


def user_display(user_obj, fallback="-"):
    if not user_obj:
        return fallback
    return user_obj.get_full_name() or user_obj.username or user_obj.email or fallback


def role_label(user_obj):
    if not user_obj:
        return "System"
    return {
        "admin": "Admin",
        "subadmin": "Partner",
        "employee": "Employee",
        "agent": "Channel Partner",
        "dsa": "DSA",
    }.get(getattr(user_obj, "role", ""), (getattr(user_obj, "role", "") or "User").title())


def agent_display(agent_obj, fallback="-"):
    if not agent_obj:
        return fallback
    return (
        getattr(agent_obj, "name", "")
        or user_display(getattr(agent_obj, "user", None), "")
        or fallback
    )


def loan_type_display(loan_type):
    choices = {}
    try:
        choices.update(dict(Loan.LOAN_TYPE_CHOICES))
    except Exception:
        pass
    try:
        choices.update(dict(Applicant.LOAN_TYPE_CHOICES))
    except Exception:
        pass
    key = str(loan_type or "").strip()
    return choices.get(key, key.replace("_", " ").title() if key else "-")


def application_effective_status_key(app_obj):
    app_key = APP_STATUS_TO_LOAN_KEY.get(getattr(app_obj, "status", ""), "")
    if app_key in ["new_entry", "waiting"] and has_revert_marker(getattr(app_obj, "approval_notes", "")):
        return "follow_up_pending"
    if app_key == "waiting" and application_has_updated_documents(app_obj):
        return UPDATED_DOCUMENT_STATUS_KEY
    return app_key


def status_label_from_key(status_key, fallback_text=""):
    key = str(status_key or "").strip().lower()
    labels = {
        "draft": "Draft",
        "new_entry": "New Application",
        "waiting": "Document Pending",
        UPDATED_DOCUMENT_STATUS_KEY: PENDING_DOCUMENT_CLEARED_LABEL,
        "follow_up": "Bank Login Process",
        "follow_up_pending": FOLLOW_UP_PENDING_LABEL,
        "approved": "Approved",
        "rejected": "Rejected",
        "disbursed": "Disbursed",
    }
    return labels.get(key, fallback_text or (key.replace("_", " ").title() if key else "-"))


def status_stage_from_key(status_key):
    key = str(status_key or "").strip().lower()
    if key == "approved":
        return "Completed"
    if key == "rejected":
        return "Closed"
    if key == "disbursed":
        return "Disbursed"
    return status_label_from_key(key)


class WorkflowApplicationRow(SimpleNamespace):
    def get_loan_type_display(self):
        return loan_type_display(getattr(self, "loan_type", ""))

    def get_status_display(self):
        return getattr(self, "status_display_text", "") or status_label_from_key(getattr(self, "status", ""))


def build_application_display_row(app_obj, status_key=None):
    applicant = getattr(app_obj, "applicant", None)
    status_key = status_key or application_effective_status_key(app_obj)
    assigned_agent = getattr(app_obj, "assigned_agent", None)
    assigned_employee = getattr(app_obj, "assigned_employee", None)
    assigned_by = getattr(app_obj, "assigned_by", None)

    submitted_by = "-"
    if assigned_agent:
        submitted_by = agent_display(assigned_agent)
    elif getattr(assigned_by, "role", "") == "agent":
        submitted_by = user_display(assigned_by)

    processed_by = user_display(assigned_employee) if assigned_employee else "-"

    partner_under = "-"
    partner_under_id = ""
    if getattr(assigned_by, "role", "") == "subadmin":
        partner_under = user_display(assigned_by)
        partner_under_id = getattr(assigned_by, "id", "") or ""
    elif assigned_agent and getattr(getattr(assigned_agent, "created_by", None), "role", "") == "subadmin":
        partner_under = user_display(assigned_agent.created_by)
        partner_under_id = getattr(assigned_agent.created_by, "id", "") or ""

    assigned_to = "-"
    if assigned_employee:
        assigned_to = f"Employee - {user_display(assigned_employee)}"
    elif assigned_agent:
        assigned_to = f"Channel Partner - {agent_display(assigned_agent)}"

    created_under = f"{role_label(assigned_by)} - {user_display(assigned_by)}" if assigned_by else "System"
    loan_type = getattr(applicant, "loan_type", "") or ""
    loan_amount = getattr(applicant, "loan_amount", None) or 0
    related_legacy = find_related_loan(app_obj)
    official_loan_id = resolve_stored_loan_id(
        legacy_loan=related_legacy,
        loan_application=app_obj,
    )
    sp_display = get_submitted_processed_display(related_legacy, app_obj)
    submitted_processed_lines = sp_display.get('lines', [])

    return WorkflowApplicationRow(
        id=app_obj.id,
        entity_type="application",
        source="application",
        user_id=str(app_obj.id),
        loan_id=official_loan_id,
        loan_id_display=display_loan_id(
            legacy_loan=related_legacy,
            loan_application=app_obj,
        ),
        full_name=getattr(applicant, "full_name", "") or "N/A",
        applicant_name=getattr(applicant, "full_name", "") or "N/A",
        email=getattr(applicant, "email", "") or "",
        mobile_number=getattr(applicant, "mobile", "") or "",
        phone=getattr(applicant, "mobile", "") or "",
        loan_type=loan_type,
        loan_amount=loan_amount,
        amount=loan_amount,
        created_at=getattr(app_obj, "created_at", None),
        created_date=getattr(app_obj, "created_at", None),
        status=status_key,
        status_raw=getattr(app_obj, "status", ""),
        status_key=status_key,
        status_key_display=status_key,
        follow_up_pending=status_key == "follow_up_pending",
        has_revert_pending=status_key == "follow_up_pending",
        status_display=status_label_from_key(status_key),
        status_display_text=status_label_from_key(status_key),
        created_under=created_under,
        created_under_display=created_under,
        assigned_agent_id=getattr(assigned_agent, "id", "") or "",
        assigned_employee_id=getattr(assigned_employee, "id", "") or "",
        assigned_to=assigned_to,
        assigned_to_display=assigned_to,
        assigned_by=user_display(assigned_by),
        assigned_by_display=user_display(assigned_by, "N/A"),
        submitted_by=submitted_by,
        submitted_by_display=submitted_by if submitted_by != "-" else "N/A",
        processed_by=processed_by,
        processed_by_display=processed_by if processed_by != "-" else "N/A",
        partner_under=partner_under,
        partner_under_display=partner_under if partner_under != "-" else "N/A",
        partner_under_id=partner_under_id,
        agent=agent_display(assigned_agent, "Unassigned"),
        employee=user_display(assigned_employee, "Unassigned"),
        submitted_processed_lines=submitted_processed_lines,
    )


def related_application_ids_for_loans(loans):
    from .loan_sync import find_related_loan_application

    related_ids = set()
    for loan in loans or []:
        related_app = find_related_loan_application(loan)
        if related_app:
            related_ids.add(related_app.id)
    return related_ids
