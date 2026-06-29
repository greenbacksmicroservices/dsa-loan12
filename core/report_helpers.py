"""Shared report query, export, and loan permission helpers."""

from __future__ import annotations

import csv
from decimal import Decimal

from django.db.models import Q
from django.http import HttpResponse

from .loan_helpers import (
    display_loan_id,
    get_agent_loan_visibility_filter,
    get_agent_type_label,
    get_sub_channel_partner_users_for_parent_agent,
    is_sub_channel_partner_agent,
)
from .loan_sync import find_related_loan_application
from .models import Agent, Loan, User


def get_child_channel_partners(user):
    """Channel partners visible under an employee or partner context."""
    if not user:
        return Agent.objects.none()
    role = str(getattr(user, 'role', '') or '').lower()
    if role == 'employee':
        return Agent.objects.filter(
            Q(under_employee=user)
            | Q(created_by=user)
            | Q(employee_assignments__employee=user)
        ).distinct().order_by('name', 'id')
    if role in {'subadmin', 'partner'}:
        from .subadmin_views import _subadmin_managed_agents_qs
        return _subadmin_managed_agents_qs(user).order_by('name', 'id')
    return Agent.objects.none()


def get_child_sub_channel_partners(user, channel_partner_id=None):
    """Sub channel partners under employee scope or a specific parent CP."""
    if channel_partner_id:
        parent = Agent.objects.filter(id=channel_partner_id).first()
        if not parent:
            return Agent.objects.none()
        scp_users = get_sub_channel_partner_users_for_parent_agent(parent)
        return Agent.objects.filter(user__in=scp_users).order_by('name', 'id')

    partners = get_child_channel_partners(user)
    scp_agents = []
    for partner in partners:
        for child in Agent.objects.filter(created_by=partner.user).select_related('user'):
            if child.user_id and is_sub_channel_partner_agent(child):
                scp_agents.append(child.id)
    if not scp_agents:
        return Agent.objects.none()
    return Agent.objects.filter(id__in=scp_agents).order_by('name', 'id')


def _employee_visible_loans_qs(user):
    cp_ids = list(get_child_channel_partners(user).values_list('id', flat=True))
    scp_user_ids = []
    for cp in Agent.objects.filter(id__in=cp_ids).select_related('user'):
        scp_user_ids.extend(
            get_sub_channel_partner_users_for_parent_agent(cp).values_list('id', flat=True)
        )
    visibility = (
        Q(assigned_employee=user)
        | Q(created_by=user)
        | Q(assigned_agent_id__in=cp_ids)
        | Q(created_by_id__in=scp_user_ids)
    )
    return Loan.objects.filter(visibility).distinct()


def _partner_visible_loans_qs(user):
    from .subadmin_views import _subadmin_scoped_loans_qs
    return _subadmin_scoped_loans_qs(user)


def _agent_visible_loans_qs(user):
    agent = Agent.objects.filter(user=user).first()
    if not agent:
        return Loan.objects.none()
    return Loan.objects.filter(get_agent_loan_visibility_filter(user, agent)).distinct()


def get_visible_applications_for_user(user):
    role = str(getattr(user, 'role', '') or '').lower()
    if role == 'admin':
        return Loan.objects.all()
    if role in {'subadmin', 'partner'}:
        return _partner_visible_loans_qs(user)
    if role == 'employee':
        return _employee_visible_loans_qs(user)
    if role == 'agent':
        return _agent_visible_loans_qs(user)
    return Loan.objects.none()


def can_view_loan(user, loan):
    if not user or not loan:
        return False
    if getattr(user, 'role', '') == 'admin':
        return True
    return get_visible_applications_for_user(user).filter(pk=loan.pk).exists()


def can_edit_loan(user, loan):
    return can_view_loan(user, loan)


def _effective_status_key(loan):
    from .updated_document_utils import UPDATED_DOCUMENT_STATUS_KEY, loan_has_updated_documents

    raw = str(getattr(loan, 'status', '') or '').strip().lower()
    if raw in {'new_entry', 'waiting'} and 'revert remark ' in str(getattr(loan, 'remarks', '') or '').lower():
        return 'follow_up_pending'
    if raw == 'waiting' and loan_has_updated_documents(loan):
        return UPDATED_DOCUMENT_STATUS_KEY
    return raw


def _disbursed_amount_for_loan(loan):
    related_app = find_related_loan_application(loan)
    if related_app and related_app.disbursement_amount is not None:
        return float(related_app.disbursement_amount)
    if related_app and related_app.status == 'Disbursed' and loan.loan_amount is not None:
        return float(loan.loan_amount)
    if str(getattr(loan, 'status', '') or '').lower() == 'disbursed' and loan.loan_amount is not None:
        return float(loan.loan_amount)
    return ''


def _disbursed_date_for_loan(loan):
    related_app = find_related_loan_application(loan)
    if related_app and related_app.disbursed_at:
        return related_app.disbursed_at.strftime('%Y-%m-%d')
    if getattr(loan, 'action_taken_at', None) and str(getattr(loan, 'status', '') or '').lower() == 'disbursed':
        return loan.action_taken_at.strftime('%Y-%m-%d')
    return ''


def build_report_row(loan, status_label_getter=None):
    status_key = _effective_status_key(loan)
    if status_label_getter:
        status_display = status_label_getter(status_key)
    else:
        status_display = status_key.replace('_', ' ').title()
    return {
        'id': loan.id,
        'loan_id': display_loan_id(legacy_loan=loan),
        'name': loan.full_name or '-',
        'email': loan.email or '-',
        'phone': loan.mobile_number or '-',
        'applied_amount': float(loan.loan_amount or 0),
        'disbursed_amount': _disbursed_amount_for_loan(loan),
        'disbursed_date': _disbursed_date_for_loan(loan),
        'status': status_key,
        'status_display': status_display,
        'created_by_id': getattr(loan, 'created_by_id', None),
        'assigned_agent_id': getattr(loan, 'assigned_agent_id', None),
        'view_url': '',
    }


def get_report_queryset_for_user(user, filters=None):
    filters = filters or {}
    qs = get_visible_applications_for_user(user).select_related(
        'assigned_agent',
        'assigned_employee',
        'created_by',
    ).order_by('-updated_at', '-created_at')

    search = str(filters.get('q') or filters.get('search') or '').strip()
    if search:
        qs = qs.filter(
            Q(full_name__icontains=search)
            | Q(email__icontains=search)
            | Q(mobile_number__icontains=search)
            | Q(user_id__icontains=search)
            | Q(loan_id__icontains=search)
        )

    status_filter = str(filters.get('status') or '').strip().lower()
    if status_filter:
        matching_ids = [loan.id for loan in qs if _effective_status_key(loan) == status_filter]
        qs = qs.filter(id__in=matching_ids)

    cp_filter = str(filters.get('channel_partner') or filters.get('partner') or '').strip()
    if cp_filter:
        qs = qs.filter(Q(assigned_agent_id=cp_filter) | Q(created_by__agent_profile__id=cp_filter))

    scp_filter = str(filters.get('sub_channel_partner') or filters.get('scp') or '').strip()
    if scp_filter:
        scp_agent = Agent.objects.filter(id=scp_filter).select_related('user').first()
        if scp_agent and scp_agent.user_id:
            qs = qs.filter(created_by_id=scp_agent.user_id)
        else:
            qs = qs.none()

    return qs


def export_standard_report_csv(rows, filename='reports.csv'):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow([
        'Loan ID',
        'Name',
        'Email',
        'Phone',
        'Applied Amount',
        'Disbursed Amount',
        'Disbursed Date',
        'Status',
    ])
    for row in rows:
        writer.writerow([
            row.get('loan_id', ''),
            row.get('name', ''),
            row.get('email', ''),
            row.get('phone', ''),
            row.get('applied_amount', ''),
            row.get('disbursed_amount', ''),
            row.get('disbursed_date', ''),
            row.get('status_display', row.get('status', '')),
        ])
    return response


def paginate_rows(rows, page=1, per_page=10):
    page = max(int(page or 1), 1)
    per_page = max(min(int(per_page or 10), 100), 1)
    total = len(rows)
    start = (page - 1) * per_page
    end = start + per_page
    page_rows = rows[start:end]
    return {
        'rows': page_rows,
        'page': page,
        'per_page': per_page,
        'total': total,
        'start': start + 1 if total else 0,
        'end': min(end, total),
        'total_pages': max((total + per_page - 1) // per_page, 1),
    }
