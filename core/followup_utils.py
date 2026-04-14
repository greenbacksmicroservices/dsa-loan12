from datetime import timedelta

from django.utils import timezone

from .loan_sync import find_related_loan, sync_loan_to_application
from .models import ActivityLog, Loan, LoanApplication, LoanStatusHistory


FOLLOW_UP_TIMEOUT_HOURS = 4
BANKING_PROCESS_TIMEOUT_HOURS = 4


def _append_note_line(existing_text, new_line):
    line = str(new_line or "").strip()
    if not line:
        return existing_text or ""
    existing = str(existing_text or "").strip()
    return f"{existing}\n{line}".strip() if existing else line


def _has_revert_marker(raw_text):
    return "revert remark " in str(raw_text or "").lower()


def _next_revert_index_from_lines(raw_text):
    count = 0
    for line in str(raw_text or "").splitlines():
        if str(line or "").strip().lower().startswith("revert remark "):
            count += 1
    return count + 1


def _next_revert_index_from_history(loan_app):
    count = 0
    history_reasons = loan_app.status_history.exclude(reason__isnull=True).exclude(reason__exact="")
    for reason in history_reasons.values_list("reason", flat=True):
        if str(reason or "").strip().lower().startswith("revert remark "):
            count += 1
    return count + 1


def _build_auto_revert_reason(loan_app=None, legacy_loan=None):
    if loan_app:
        next_idx = max(
            _next_revert_index_from_lines(loan_app.approval_notes),
            _next_revert_index_from_history(loan_app),
        )
    elif legacy_loan:
        next_idx = _next_revert_index_from_lines(legacy_loan.remarks)
    else:
        next_idx = 1
    return f"Revert Remark {next_idx}: Auto follow up after {BANKING_PROCESS_TIMEOUT_HOURS}h in Banking Processing"


def _legacy_banking_anchor(loan_obj):
    return (
        loan_obj.action_taken_at
        or loan_obj.follow_up_triggered_at
        or loan_obj.updated_at
        or loan_obj.assigned_at
    )


def _move_application_waiting_to_banking(app_obj):
    app_obj.trigger_follow_up()
    ActivityLog.objects.create(
        action="follow_up_triggered_auto",
        description=(
            f"Auto moved to Banking Processing after {FOLLOW_UP_TIMEOUT_HOURS}h: "
            f"{app_obj.applicant.full_name}"
        ),
        user=None,
    )


def _move_legacy_waiting_to_banking(loan_obj, now):
    loan_obj.status = "follow_up"
    loan_obj.requires_follow_up = True
    loan_obj.follow_up_triggered_at = now
    if not loan_obj.action_taken_at:
        loan_obj.action_taken_at = now
    loan_obj.save(
        update_fields=[
            "status",
            "requires_follow_up",
            "follow_up_triggered_at",
            "action_taken_at",
            "updated_at",
        ]
    )
    ActivityLog.objects.create(
        action="follow_up_triggered_auto",
        description=f"Auto moved to Banking Processing after {FOLLOW_UP_TIMEOUT_HOURS}h: {loan_obj.full_name}",
        user=None,
    )


def _move_application_banking_to_follow_up_pending(app_obj, reason_line, now):
    previous_status = app_obj.status
    app_obj.status = "Waiting for Processing"
    app_obj.is_sm_signed = False
    app_obj.sm_signed_at = None
    app_obj.approval_notes = _append_note_line(app_obj.approval_notes, reason_line)
    app_obj.follow_up_notified_at = now
    app_obj.save(
        update_fields=[
            "status",
            "is_sm_signed",
            "sm_signed_at",
            "approval_notes",
            "follow_up_notified_at",
            "updated_at",
        ]
    )

    LoanStatusHistory.objects.create(
        loan_application=app_obj,
        from_status="follow_up" if previous_status == "Required Follow-up" else "waiting",
        to_status="waiting",
        changed_by=None,
        reason=reason_line,
        is_auto_triggered=True,
    )

    related_loan = find_related_loan(app_obj)
    if related_loan:
        related_loan.status = "waiting"
        related_loan.is_sm_signed = False
        related_loan.sm_signed_at = None
        related_loan.requires_follow_up = True
        related_loan.remarks = _append_note_line(related_loan.remarks, reason_line)
        related_loan.action_taken_at = now
        related_loan.follow_up_triggered_at = now
        related_loan.save(
            update_fields=[
                "status",
                "is_sm_signed",
                "sm_signed_at",
                "requires_follow_up",
                "remarks",
                "action_taken_at",
                "follow_up_triggered_at",
                "updated_at",
            ]
        )

    ActivityLog.objects.create(
        action="follow_up_pending_triggered_auto",
        description=f"Auto moved to Follow Up after {BANKING_PROCESS_TIMEOUT_HOURS}h in Banking Processing: {app_obj.applicant.full_name}",
        user=None,
    )


def _move_legacy_banking_to_follow_up_pending(loan_obj, reason_line, now):
    previous_status = loan_obj.status
    loan_obj.status = "waiting"
    loan_obj.requires_follow_up = True
    loan_obj.is_sm_signed = False
    loan_obj.sm_signed_at = None
    loan_obj.remarks = _append_note_line(loan_obj.remarks, reason_line)
    loan_obj.action_taken_at = now
    loan_obj.follow_up_triggered_at = now
    loan_obj.save(
        update_fields=[
            "status",
            "requires_follow_up",
            "is_sm_signed",
            "sm_signed_at",
            "remarks",
            "action_taken_at",
            "follow_up_triggered_at",
            "updated_at",
        ]
    )

    synced_app = sync_loan_to_application(
        loan_obj,
        assigned_by_user=None,
        create_if_missing=True,
    )
    if synced_app and synced_app.status != "Waiting for Processing":
        app_prev = synced_app.status
        synced_app.status = "Waiting for Processing"
        synced_app.approval_notes = _append_note_line(synced_app.approval_notes, reason_line)
        synced_app.is_sm_signed = False
        synced_app.sm_signed_at = None
        synced_app.follow_up_notified_at = now
        synced_app.save(
            update_fields=[
                "status",
                "approval_notes",
                "is_sm_signed",
                "sm_signed_at",
                "follow_up_notified_at",
                "updated_at",
            ]
        )
        LoanStatusHistory.objects.create(
            loan_application=synced_app,
            from_status="follow_up" if app_prev == "Required Follow-up" else "waiting",
            to_status="waiting",
            changed_by=None,
            reason=reason_line,
            is_auto_triggered=True,
        )
    elif synced_app and not _has_revert_marker(synced_app.approval_notes):
        synced_app.approval_notes = _append_note_line(synced_app.approval_notes, reason_line)
        synced_app.follow_up_notified_at = now
        synced_app.save(update_fields=["approval_notes", "follow_up_notified_at", "updated_at"])

    ActivityLog.objects.create(
        action="follow_up_pending_triggered_auto",
        description=f"Auto moved to Follow Up after {BANKING_PROCESS_TIMEOUT_HOURS}h in Banking Processing: {loan_obj.full_name}",
        user=None,
    )


def auto_move_overdue_to_follow_up():
    """
    Real-time automation:
    1) Banking Processing -> Follow Up (revert-pending) after 4h

    Note:
    Waiting / Document Pending records stay in place until a processor
    explicitly moves them to Banking Processing.
    """
    now = timezone.now()
    banking_cutoff = now - timedelta(hours=BANKING_PROCESS_TIMEOUT_HOURS)

    moved = {
        "applications_to_follow_up_pending": 0,
        "loans_to_follow_up_pending": 0,
    }

    banking_apps = LoanApplication.objects.filter(status="Required Follow-up")
    for app in banking_apps:
        if _has_revert_marker(app.approval_notes):
            continue
        banking_anchor = app.follow_up_scheduled_at or app.follow_up_notified_at or app.updated_at
        if not banking_anchor or banking_anchor > banking_cutoff:
            continue
        auto_reason = _build_auto_revert_reason(loan_app=app)
        _move_application_banking_to_follow_up_pending(app, auto_reason, now)
        moved["applications_to_follow_up_pending"] += 1

    banking_loans = Loan.objects.filter(status="follow_up")
    for loan in banking_loans:
        if _has_revert_marker(loan.remarks):
            continue
        anchor = _legacy_banking_anchor(loan)
        if not anchor or anchor > banking_cutoff:
            continue
        auto_reason = _build_auto_revert_reason(legacy_loan=loan)
        _move_legacy_banking_to_follow_up_pending(loan, auto_reason, now)
        moved["loans_to_follow_up_pending"] += 1

    return moved
