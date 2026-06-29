"""Chart data helpers for admin and partner dashboards."""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from .loan_helpers import is_sub_channel_partner_agent
from .models import Agent, Loan, User
from .report_helpers import _effective_status_key, get_visible_applications_for_user
from .updated_document_utils import UPDATED_DOCUMENT_STATUS_KEY


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


def get_partner_hierarchy_queryset(partner_user):
    """Loans visible under a partner (subadmin) hierarchy."""
    return get_visible_applications_for_user(partner_user)


def get_monthly_loan_application_counts(months=12):
    """Return last N months of loan application counts from legacy Loan records."""
    now = timezone.now()
    labels = []
    data = []
    cursor = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    month_starts = []
    for _ in range(months):
        month_starts.append(cursor)
        if cursor.month == 1:
            cursor = cursor.replace(year=cursor.year - 1, month=12)
        else:
            cursor = cursor.replace(month=cursor.month - 1)

    month_starts.reverse()

    for index, start in enumerate(month_starts):
        if index + 1 < len(month_starts):
            end = month_starts[index + 1]
        else:
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)

        count = Loan.objects.filter(created_at__gte=start, created_at__lt=end).count()
        labels.append(start.strftime('%b %Y'))
        data.append(count)

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
        'labels': ['Partner', 'Employee', 'Channel Partner', 'Sub Channel Partner'],
        'data': [partners, employees, cp_count, scp_count],
        'partners': partners,
        'employees': employees,
        'channel_partners': cp_count,
        'sub_channel_partners': scp_count,
    }


def _status_counts_for_queryset(loans_qs):
    counts = {key: 0 for key, _ in STATUS_CHART_ORDER}
    for loan in loans_qs.only('id', 'status', 'remarks'):
        key = _effective_status_key(loan)
        if key in counts:
            counts[key] += 1
        elif key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def get_today_application_status_counts(queryset=None):
    """Timezone-aware today counts grouped by effective status."""
    today = timezone.localdate()
    qs = queryset if queryset is not None else Loan.objects.all()
    today_loans = qs.filter(created_at__date=today)
    counts = _status_counts_for_queryset(today_loans)
    return {
        'labels': [label for _, label in STATUS_CHART_ORDER],
        'keys': [key for key, _ in STATUS_CHART_ORDER],
        'data': [counts.get(key, 0) for key, _ in STATUS_CHART_ORDER],
        'counts': counts,
        'date': today.isoformat(),
    }


def get_partner_loan_status_overview(partner_user):
    """Status breakdown for loans under partner hierarchy."""
    qs = get_partner_hierarchy_queryset(partner_user)
    counts = _status_counts_for_queryset(qs)
    return {
        'labels': [label for _, label in STATUS_CHART_ORDER],
        'keys': [key for key, _ in STATUS_CHART_ORDER],
        'data': [counts.get(key, 0) for key, _ in STATUS_CHART_ORDER],
        'counts': counts,
    }


def get_partner_team_application_overview(partner_user):
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

    total_applications = get_partner_hierarchy_queryset(partner_user).count()

    return {
        'labels': ['Employees', 'Channel Partners', 'Sub Channel Partners', 'Total Applications'],
        'data': [
            employees_qs.count(),
            channel_partners,
            sub_channel_partners,
            total_applications,
        ],
        'employees': employees_qs.count(),
        'channel_partners': channel_partners,
        'sub_channel_partners': sub_channel_partners,
        'total_applications': total_applications,
    }
