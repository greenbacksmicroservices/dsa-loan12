"""Chart data helpers for admin and partner dashboards."""

from __future__ import annotations

import logging

from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .loan_helpers import is_sub_channel_partner_agent
from .models import Agent, Loan, LoanApplication, User
from .updated_document_utils import UPDATED_DOCUMENT_STATUS_KEY

logger = logging.getLogger(__name__)

STATUS_CHART_ORDER = [
    ('new_entry', 'New'),
    ('waiting', 'Document Pending'),
    (UPDATED_DOCUMENT_STATUS_KEY, 'Updated Document'),
    ('follow_up', 'Banking Processing'),
    ('follow_up_pending', 'Follow Up'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('disbursed', 'Disbursed'),
]


def _month_bucket_starts(months=12):
    """Return timezone-aware datetimes for the first day of each month (oldest first)."""
    now = timezone.now()
    cursor = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_starts = []
    for _ in range(months):
        month_starts.append(cursor)
        if cursor.month == 1:
            cursor = cursor.replace(year=cursor.year - 1, month=12)
        else:
            cursor = cursor.replace(month=cursor.month - 1)
    month_starts.reverse()
    return month_starts


def _month_key(dt):
    return dt.strftime('%Y-%m')


def _counts_to_chart_payload(counts):
    return {
        'labels': [label for _, label in STATUS_CHART_ORDER],
        'keys': [key for key, _ in STATUS_CHART_ORDER],
        'data': [int(counts.get(key, 0) or 0) for key, _ in STATUS_CHART_ORDER],
        'counts': {key: int(counts.get(key, 0) or 0) for key, _ in STATUS_CHART_ORDER},
    }


def get_partner_visible_applications(partner_user):
    """Loans visible under a partner (subadmin) hierarchy."""
    from .subadmin_views import _subadmin_scoped_loans_qs

    return _subadmin_scoped_loans_qs(partner_user)


def get_partner_hierarchy_queryset(partner_user):
    """Backward-compatible alias for partner loan queryset."""
    return get_partner_visible_applications(partner_user)


def _linked_legacy_loan_ids():
    return set(
        LoanApplication.objects.exclude(legacy_loan_id__isnull=True)
        .values_list('legacy_loan_id', flat=True)
    )


def get_monthly_loan_application_counts(months=12):
    """
    Return last N months of application counts.
    Uses LoanApplication.created_at plus legacy Loan rows not linked to a workflow app.
    """
    month_starts = _month_bucket_starts(months)
    if not month_starts:
        return {'labels': [], 'data': []}

    earliest = month_starts[0]
    linked_legacy_ids = _linked_legacy_loan_ids()

    app_counts = {
        _month_key(row['month']): row['count']
        for row in (
            LoanApplication.objects.filter(created_at__gte=earliest)
            .annotate(month=TruncMonth('created_at'))
            .values('month')
            .annotate(count=Count('id'))
        )
    }

    legacy_qs = Loan.objects.filter(created_at__gte=earliest)
    if linked_legacy_ids:
        legacy_qs = legacy_qs.exclude(id__in=linked_legacy_ids)

    legacy_counts = {
        _month_key(row['month']): row['count']
        for row in (
            legacy_qs.annotate(month=TruncMonth('created_at'))
            .values('month')
            .annotate(count=Count('id'))
        )
    }

    labels = []
    data = []
    for start in month_starts:
        key = _month_key(start)
        labels.append(start.strftime('%b %Y'))
        data.append(int(app_counts.get(key, 0)) + int(legacy_counts.get(key, 0)))

    return {'labels': labels, 'data': data}


def get_user_hierarchy_counts():
    """Realtime counts for admin hierarchy overview chart."""
    partners = User.objects.filter(
        Q(role__iexact='subadmin') | Q(role__iexact='partner'),
        is_active=True,
    ).count()
    employees = User.objects.filter(role__iexact='employee', is_active=True).count()

    cp_count = 0
    scp_count = 0
    for agent in Agent.objects.select_related('user', 'created_by').only(
        'id', 'agent_id', 'created_by_id', 'user_id'
    ):
        if is_sub_channel_partner_agent(agent):
            scp_count += 1
        else:
            cp_count += 1

    return {
        'labels': ['Partners', 'Employees', 'Channel Partners', 'Sub Channel Partners'],
        'data': [partners, employees, cp_count, scp_count],
        'partners': partners,
        'employees': employees,
        'channel_partners': cp_count,
        'sub_channel_partners': scp_count,
    }


def _admin_merged_status_counts(*, created_date=None):
    """Merge legacy Loan and workflow-only LoanApplication counts for admin scope."""
    from .subadmin_views import (
        _count_statuses_for_applications,
        _count_statuses_for_loans,
        _merge_status_counts,
    )
    from .workflow_rows import related_application_ids_for_loans

    loan_qs = Loan.objects.all()
    if created_date:
        loan_qs = loan_qs.filter(created_at__date=created_date)

    legacy_list = list(loan_qs.only('id', 'status', 'remarks'))
    loan_counts = _count_statuses_for_loans(legacy_list)
    related_ids = related_application_ids_for_loans(legacy_list)

    app_qs = LoanApplication.objects.all()
    if created_date:
        app_qs = app_qs.filter(created_at__date=created_date)
    if related_ids:
        app_qs = app_qs.exclude(id__in=related_ids)

    app_counts = _count_statuses_for_applications(app_qs)
    return _merge_status_counts(loan_counts, app_counts)


def _partner_merged_status_counts(partner_user):
    """Merge legacy and workflow-only counts for a partner hierarchy."""
    from .loan_sync import find_related_loan_application
    from .subadmin_views import (
        _count_statuses_for_applications,
        _count_statuses_for_loans,
        _merge_status_counts,
        _subadmin_managed_agents_qs,
        _subadmin_managed_employees_qs,
        _subadmin_scoped_loans_qs,
    )

    all_loans_list = list(_subadmin_scoped_loans_qs(partner_user).only('id', 'status', 'remarks'))
    status_stats = _count_statuses_for_loans(all_loans_list)

    related_app_ids = {
        related_app.id
        for related_app in (find_related_loan_application(loan) for loan in all_loans_list)
        if related_app
    }
    managed_employee_ids = list(
        _subadmin_managed_employees_qs(partner_user).values_list('id', flat=True)
    )
    managed_agent_ids = list(
        _subadmin_managed_agents_qs(partner_user).values_list('id', flat=True)
    )
    workflow_filters = Q(assigned_by=partner_user)
    if managed_employee_ids:
        workflow_filters |= Q(assigned_employee_id__in=managed_employee_ids)
    if managed_agent_ids:
        workflow_filters |= Q(assigned_agent_id__in=managed_agent_ids)

    workflow_counts = _count_statuses_for_applications(
        LoanApplication.objects.filter(workflow_filters).exclude(id__in=related_app_ids)
    )
    return _merge_status_counts(status_stats, workflow_counts)


def get_today_application_status_counts(queryset=None):
    """Timezone-aware today counts grouped by effective status."""
    today = timezone.localdate()
    if queryset is None:
        merged = _admin_merged_status_counts(created_date=today)
    else:
        from .report_helpers import _effective_status_key

        counts = {key: 0 for key, _ in STATUS_CHART_ORDER}
        for loan in queryset.filter(created_at__date=today).only('id', 'status', 'remarks'):
            key = _effective_status_key(loan)
            if key in counts:
                counts[key] += 1
        merged = counts

    payload = _counts_to_chart_payload(merged)
    payload['date'] = today.isoformat()
    return payload


def get_partner_loan_status_counts(partner_user):
    """Status breakdown for loans under partner hierarchy."""
    merged = _partner_merged_status_counts(partner_user)
    return _counts_to_chart_payload(merged)


def get_partner_loan_status_overview(partner_user):
    """Backward-compatible alias."""
    return get_partner_loan_status_counts(partner_user)


def get_partner_team_overview_counts(partner_user):
    """Team counts under partner hierarchy."""
    from .subadmin_views import _subadmin_managed_agents_qs, _subadmin_managed_employees_qs

    employees_qs = _subadmin_managed_employees_qs(partner_user)
    agents_qs = _subadmin_managed_agents_qs(partner_user)

    channel_partners = 0
    sub_channel_partners = 0
    for agent in agents_qs:
        if is_sub_channel_partner_agent(agent):
            sub_channel_partners += 1
        else:
            channel_partners += 1

    merged = _partner_merged_status_counts(partner_user)
    total_applications = int(merged.get('total', 0) or 0)
    employee_count = employees_qs.count()

    return {
        'labels': ['Employees', 'Channel Partners', 'Sub Channel Partners', 'Total Applications'],
        'data': [
            employee_count,
            channel_partners,
            sub_channel_partners,
            total_applications,
        ],
        'employees': employee_count,
        'channel_partners': channel_partners,
        'sub_channel_partners': sub_channel_partners,
        'total_applications': total_applications,
    }


def get_partner_team_application_overview(partner_user):
    """Backward-compatible alias."""
    return get_partner_team_overview_counts(partner_user)


def empty_monthly_loan_applications(months=12):
    month_starts = _month_bucket_starts(months)
    labels = [start.strftime('%b %Y') for start in month_starts]
    return {'labels': labels, 'data': [0] * len(labels)}


def empty_status_chart_payload():
    counts = {key: 0 for key, _ in STATUS_CHART_ORDER}
    return _counts_to_chart_payload(counts)


def empty_user_hierarchy_counts():
    return {
        'labels': ['Partners', 'Employees', 'Channel Partners', 'Sub Channel Partners'],
        'data': [0, 0, 0, 0],
        'partners': 0,
        'employees': 0,
        'channel_partners': 0,
        'sub_channel_partners': 0,
    }


def empty_partner_team_overview():
    return {
        'labels': ['Employees', 'Channel Partners', 'Sub Channel Partners', 'Total Applications'],
        'data': [0, 0, 0, 0],
        'employees': 0,
        'channel_partners': 0,
        'sub_channel_partners': 0,
        'total_applications': 0,
    }
