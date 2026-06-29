"""
Signals for workflow automation and model synchronization.
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import ActivityLog, Loan, LoanApplication
from .loan_sync import (
    find_related_loan_application,
    sync_application_to_loan,
    sync_loan_to_application,
)


@receiver(pre_save, sender=LoanApplication)
def stamp_banking_processing_started_for_application(sender, instance, **kwargs):
    if kwargs.get("raw", False):
        return
    if instance.status != "Required Follow-up":
        return
    if instance.banking_processing_started_at:
        return
    if not instance.pk:
        instance.banking_processing_started_at = timezone.now()
        return
    previous_status = (
        LoanApplication.objects.filter(pk=instance.pk)
        .values_list("status", flat=True)
        .first()
    )
    if previous_status != "Required Follow-up":
        instance.banking_processing_started_at = timezone.now()


@receiver(pre_save, sender=Loan)
def stamp_banking_processing_started_for_loan(sender, instance, **kwargs):
    if kwargs.get("raw", False):
        return
    if instance.status != "follow_up":
        return
    if instance.banking_processing_started_at:
        return
    if not instance.pk:
        instance.banking_processing_started_at = timezone.now()
        return
    previous_status = Loan.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    if previous_status != "follow_up":
        instance.banking_processing_started_at = timezone.now()


@receiver(post_save, sender=LoanApplication)
def ensure_assigned_at_for_waiting(sender, instance, created, **kwargs):
    """
    Keep waiting/banking-process records timestamped for aging logic.
    """
    if kwargs.get("raw", False):
        return

    if created:
        if instance.status in ["Waiting for Processing", "Required Follow-up"] and not instance.assigned_at:
            assigned_at = timezone.now()
            instance.assigned_at = assigned_at
            LoanApplication.objects.filter(id=instance.id).update(assigned_at=assigned_at)
        return

    if instance.status in ["Waiting for Processing", "Required Follow-up"] and not instance.assigned_at:
        assigned_at = timezone.now()
        instance.assigned_at = assigned_at
        LoanApplication.objects.filter(id=instance.id).update(assigned_at=assigned_at)


@receiver(post_save, sender=LoanApplication)
def mirror_application_to_loan(sender, instance, created, **kwargs):
    """
    Keep the legacy Loan table aligned with workflow updates done on LoanApplication.
    """
    if kwargs.get("raw", False):
        return

    if getattr(instance, "_skip_sync_to_loan", False):
        return

    try:
        sync_application_to_loan(instance)
    except Exception:
        return


@receiver(post_save, sender=Loan)
def mirror_loan_to_application(sender, instance, created, **kwargs):
    """
    Ensure every Loan created by any role also appears in LoanApplication (New Entry workflow).
    """
    if kwargs.get("raw", False):
        return

    existing_app = find_related_loan_application(instance)
    loan_app = sync_loan_to_application(instance, create_if_missing=True)

    if created and loan_app and not existing_app:
        ActivityLog.objects.create(
            action="status_updated",
            description=f"Workflow entry created from Loan #{instance.id} for {loan_app.applicant.full_name} ({loan_app.status})",
            user=instance.created_by if instance.created_by else None,
        )


def check_and_trigger_followups():
    """
    Deprecated waiting->banking automation.
    Banking Login Process aging is handled by auto_move_overdue_to_follow_up().
    """
    from .followup_utils import auto_move_overdue_to_follow_up

    moved = auto_move_overdue_to_follow_up()
    return moved.get("applications_to_follow_up_pending", 0) + moved.get("loans_to_follow_up_pending", 0)
