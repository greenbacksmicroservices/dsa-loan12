"""Admin fast-action helpers for All Loans loan management."""

from __future__ import annotations

from django.utils import timezone

TERMINAL_APPLICATION_STATUSES = {'Rejected', 'Disbursed', 'Approved'}
TERMINAL_LEGACY_STATUSES = {'rejected', 'disbursed', 'approved'}


def can_admin_fast_action(user, loan_app=None, legacy=None):
    """Only admin users may use All Loans fast approve/disburse shortcuts."""
    return getattr(user, 'role', '') == 'admin'


def admin_fast_approvable_application(loan_app):
    return bool(loan_app and loan_app.status not in TERMINAL_APPLICATION_STATUSES)


def admin_fast_approvable_legacy(legacy):
    return bool(legacy and legacy.status not in TERMINAL_LEGACY_STATUSES)


def admin_fast_disbursable_application(loan_app):
    return bool(loan_app and loan_app.status == 'Approved')


def admin_fast_disbursable_legacy(legacy):
    return bool(legacy and legacy.status == 'approved')


def parse_admin_fast_flag(payload, user):
  """
  Return (use_admin_fast, error_response).
  error_response is None when allowed; otherwise a DRF Response should be returned.
  """
  requested = str((payload or {}).get('admin_fast_action', '')).lower() in {'1', 'true', 'yes'}
  if not requested:
      return False, None
  if not can_admin_fast_action(user):
      return False, 'denied'
  return True, None


def ensure_banking_timestamps(loan_app=None, legacy=None):
    """Ensure banking_processing_started_at exists before admin fast approval."""
    now = timezone.now()
    if loan_app and not loan_app.banking_processing_started_at:
        loan_app.banking_processing_started_at = now
        loan_app.save(update_fields=['banking_processing_started_at', 'updated_at'])
    if legacy and not legacy.banking_processing_started_at:
        legacy.banking_processing_started_at = now
        legacy.save(update_fields=['banking_processing_started_at', 'updated_at'])
