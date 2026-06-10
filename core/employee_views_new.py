"""
Employee Panel Views - Complete Implementation
- All Loans Page
- New Entry Requests Page
- Dashboard Statistics
- Loan Actions (Approve/Reject/Disburse)
- Agent Management

Uses Loan model as single source of truth
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.db.models import Sum, Count, Q, F
from django.contrib import messages
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import json
import csv
from decimal import Decimal
from datetime import timedelta

from .models import User, Loan, LoanApplication, Agent, ActivityLog, LoanDocument, AgentAssignment
from .loan_helpers import display_loan_id, is_channel_partner
from .followup_utils import auto_move_overdue_to_follow_up
from .loan_sync import find_related_loan, find_related_loan_application
from .id_utils import generate_agent_sequence_id
from .onboarding_utils import collect_user_document_payload
from .remarks_utils import detail_value, sanitize_display_remark, upsert_manual_remark
from .updated_document_utils import (
    UPDATED_DOCUMENT_LABEL,
    UPDATED_DOCUMENT_STATUS_KEY,
    application_has_updated_documents,
    loan_has_updated_documents,
)


def _is_document_pending_note(raw_text):
    return 'document pending by' in str(raw_text or '').lower()


def _remove_document_pending_lines(raw_text, show_document_pending=False):
    text = str(raw_text or '').strip()
    if not text or show_document_pending:
        return text

    kept_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not _is_document_pending_note(line)
    ]
    return '\n'.join(kept_lines).strip()


# ============================================================
# EMPLOYEE DASHBOARD
# ============================================================

@login_required
@require_http_methods(["GET"])
def employee_dashboard(request):
    """Employee dashboard with stats and overview"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    return render(request, 'core/employee/dashboard.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_dashboard_stats(request):
    """Employee dashboard statistics
    Returns counts of loans by status assigned to employee
    Uses Loan model as source of truth
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        auto_move_overdue_to_follow_up()

        # Get all loans assigned to this employee
        loans = Loan.objects.filter(assigned_employee=request.user)
        loans_list = list(loans)
        effective_statuses = [_employee_effective_status_key(loan) for loan in loans_list]
        related_app_ids = {
            related_app.id
            for related_app in (find_related_loan_application(loan) for loan in loans_list)
            if related_app
        }
        app_status_map = {
            'New Entry': 'new_entry',
            'Waiting for Processing': 'waiting',
            'Required Follow-up': 'follow_up',
            'Approved': 'approved',
            'Rejected': 'rejected',
            'Disbursed': 'disbursed',
        }
        app_statuses = []
        for app in LoanApplication.objects.filter(assigned_employee=request.user).exclude(id__in=related_app_ids):
            app_key = app_status_map.get(getattr(app, 'status', ''), '')
            if app_key in ['new_entry', 'waiting'] and FOLLOW_UP_PENDING_MARKER in str(getattr(app, 'approval_notes', '') or '').lower():
                app_key = 'follow_up_pending'
            elif app_key == 'waiting' and application_has_updated_documents(app):
                app_key = UPDATED_DOCUMENT_STATUS_KEY
            if app_key:
                app_statuses.append(app_key)
        effective_statuses.extend(app_statuses)
        
        # Calculate stats
        total_loans = len(effective_statuses)
        new_entry_count = effective_statuses.count('new_entry')
        waiting_count = effective_statuses.count('waiting')
        updated_document_count = effective_statuses.count(UPDATED_DOCUMENT_STATUS_KEY)
        follow_up_count = effective_statuses.count('follow_up')
        follow_up_pending_count = effective_statuses.count('follow_up_pending')
        in_processing = waiting_count + follow_up_count
        approved = effective_statuses.count('approved')
        rejected = effective_statuses.count('rejected')
        disbursed = effective_statuses.count('disbursed')
        
        # Calculate totals
        total_amount = loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or Decimal('0')
        approved_amount = loans.filter(status='approved').aggregate(Sum('loan_amount'))['loan_amount__sum'] or Decimal('0')
        disbursed_amount = loans.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or Decimal('0')
        
        return Response({
            'success': True,
            'total_loans': total_loans,
            'new_entry': new_entry_count,
            'in_processing': in_processing,
            'waiting': waiting_count,
            'updated_document': updated_document_count,
            'follow_up': follow_up_count,
            'follow_up_pending': follow_up_pending_count,
            'approved': approved,
            'rejected': rejected,
            'disbursed': disbursed,
            'total_amount': float(total_amount),
            'approved_amount': float(approved_amount),
            'disbursed_amount': float(disbursed_amount),
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# EMPLOYEE ALL LOANS PAGE
# ============================================================

def _display_user(user_obj, fallback='-'):
    if not user_obj:
        return fallback
    return user_obj.get_full_name() or user_obj.username or fallback


def _partner_under_for(created_by=None, assigned_agent=None):
    partner = None
    if created_by and getattr(created_by, 'role', '') == 'subadmin':
        partner = created_by
    elif assigned_agent and getattr(assigned_agent, 'created_by', None) and assigned_agent.created_by.role == 'subadmin':
        partner = assigned_agent.created_by
    if not partner:
        return '-'
    return _display_user(partner, 'Partner')


def _employee_clean_remark(raw_text, default='-'):
    return sanitize_display_remark(_remove_document_pending_lines(raw_text, False), default=default)


def _employee_channel_partner_name_for_loan(loan):
    assigned_agent = getattr(loan, 'assigned_agent', None)
    if assigned_agent:
        agent_user = getattr(assigned_agent, 'user', None)
        return (
            getattr(assigned_agent, 'name', '')
            or _display_user(agent_user, '')
            or '-'
        )

    creator = getattr(loan, 'created_by', None)
    if getattr(creator, 'role', '') == 'agent':
        try:
            creator_agent = Agent.objects.filter(user=creator).only('name').first()
        except Exception:
            creator_agent = None
        return (
            getattr(creator_agent, 'name', '')
            or _display_user(creator, '')
            or '-'
        )

    return (
        detail_value(
            getattr(loan, 'remarks', ''),
            'lead receive channel partner name',
            'channel partner name',
            default='',
        )
        or '-'
    )


FOLLOW_UP_PENDING_MARKER = 'revert remark '


def _employee_role_label(user_obj):
    if not user_obj:
        return 'System'
    mapping = {
        'admin': 'Admin',
        'subadmin': 'Partner',
        'employee': 'Employee',
        'agent': 'Channel Partner',
        'dsa': 'DSA',
    }
    return mapping.get(getattr(user_obj, 'role', ''), getattr(user_obj, 'role', 'User').title())


def _employee_agent_photo_url(agent):
    if getattr(agent, 'profile_photo', None):
        return agent.profile_photo.url
    if getattr(agent, 'user', None) and getattr(agent.user, 'profile_photo', None):
        return agent.user.profile_photo.url
    return ''


def _employee_is_follow_up_pending_loan(loan_obj):
    if not loan_obj or loan_obj.status not in ['new_entry', 'waiting']:
        return False
    if FOLLOW_UP_PENDING_MARKER in str(loan_obj.remarks or '').lower():
        return True
    related_app = find_related_loan_application(loan_obj)
    return FOLLOW_UP_PENDING_MARKER in str(getattr(related_app, 'approval_notes', '') or '').lower()


def _employee_effective_status_key(loan_obj):
    if _employee_is_follow_up_pending_loan(loan_obj):
        return 'follow_up_pending'
    raw_status = str(getattr(loan_obj, 'status', '') or '').strip().lower()
    if raw_status == 'waiting' and loan_has_updated_documents(loan_obj):
        return UPDATED_DOCUMENT_STATUS_KEY
    return raw_status


def _employee_status_label(status_key):
    labels = {
        'draft': 'Draft',
        'new_entry': 'New Application',
        'waiting': 'Document Pending',
        UPDATED_DOCUMENT_STATUS_KEY: 'Pending Document Cleared',
        'follow_up': 'Bank Login Process',
        'follow_up_pending': 'Follow Up',
        'approved': 'Approved',
        'rejected': 'Rejected',
        'disbursed': 'Disbursed',
    }
    return labels.get(status_key, str(status_key or '-').replace('_', ' ').title())


def _employee_agent_scope_loans(employee_user, agent):
    base_filter = Q(assigned_agent=agent)
    if getattr(agent, 'user_id', None):
        base_filter |= Q(created_by=agent.user)

    return Loan.objects.filter(base_filter).filter(
        Q(assigned_employee=employee_user) |
        Q(assigned_agent__under_employee=employee_user) |
        Q(assigned_agent__created_by=employee_user) |
        Q(created_by=employee_user)
    ).select_related(
        'created_by',
        'assigned_employee',
        'assigned_agent',
        'assigned_agent__user',
    ).prefetch_related('documents').order_by('-created_at').distinct()


def _employee_customer_row_from_loan(loan, source):
    creator = loan.created_by
    creator_name = _display_user(creator, '-')
    creator_role = _employee_role_label(creator)
    status_key = _employee_effective_status_key(loan)
    partner_under = _partner_under_for(creator, loan.assigned_agent)

    if loan.assigned_employee:
        assigned_to = f"Employee - {_display_user(loan.assigned_employee, '-')}"
    elif loan.assigned_agent:
        assigned_to = f"Channel Partner - {loan.assigned_agent.name}"
    else:
        assigned_to = '-'

    return {
        'id': loan.id,
        'loan_id': display_loan_id(legacy_loan=loan),
        'loan_uid': display_loan_id(legacy_loan=loan),
        'customer_name': loan.full_name or '-',
        'mobile': loan.mobile_number or '-',
        'email': loan.email or '-',
        'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else (loan.loan_type or '-'),
        'loan_amount': float(loan.loan_amount or 0),
        'status': status_key,
        'status_raw': loan.status,
        'status_display': _employee_status_label(status_key),
        'source': source,
        'assigned_to': assigned_to,
        'under_whom': f"{creator_role} - {creator_name}",
        'assigned_by': partner_under if partner_under != '-' else f"{creator_role} - {creator_name}",
        'partner_under': partner_under,
        'bank_remark': _employee_clean_remark(loan.remarks, '-'),
        'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else '',
        'detail_url': reverse('employee_loan_detail', kwargs={'loan_id': loan.id}),
    }


def _build_employee_agent_payload(employee_user, agent, include_customers=True):
    scoped_loans_qs = _employee_agent_scope_loans(employee_user, agent)
    loans_list = list(scoped_loans_qs)
    submitted_count = sum(1 for loan in loans_list if agent.user and loan.created_by_id == agent.user.id)
    assigned_count = sum(1 for loan in loans_list if loan.assigned_agent_id == agent.id)

    customers = []
    if include_customers:
        for loan in loans_list[:250]:
            source = 'Submitted' if (agent.user and loan.created_by_id == agent.user.id) else 'Assigned'
            customers.append(_employee_customer_row_from_loan(loan, source))

    summary = {
        'total_submitted_applications': submitted_count,
        'total_assigned_applications': assigned_count,
        'total_applications': len(loans_list),
        'approved': sum(1 for loan in loans_list if _employee_effective_status_key(loan) == 'approved'),
        'rejected': sum(1 for loan in loans_list if _employee_effective_status_key(loan) == 'rejected'),
        'banking_processing': sum(1 for loan in loans_list if _employee_effective_status_key(loan) == 'follow_up'),
        'follow_up_pending': sum(1 for loan in loans_list if _employee_effective_status_key(loan) == 'follow_up_pending'),
        'waiting': sum(1 for loan in loans_list if _employee_effective_status_key(loan) == 'waiting'),
        'updated_document': sum(1 for loan in loans_list if _employee_effective_status_key(loan) == UPDATED_DOCUMENT_STATUS_KEY),
        'disbursed': sum(1 for loan in loans_list if _employee_effective_status_key(loan) == 'disbursed'),
        'total_customers': len(loans_list),
    }

    creator = agent.created_by
    created_under = 'System'
    if creator:
        created_under = f"{_employee_role_label(creator)} - {_display_user(creator, '-')}"

    user_documents = collect_user_document_payload(agent.user) if getattr(agent, 'user', None) else []
    document_lookup = {doc.get('type'): doc.get('url') for doc in user_documents if doc.get('url')}

    return {
        'agent': {
            'id': agent.id,
            'agent_id': agent.agent_id or f'EDC-SCP-{agent.id:04d}',
            'name': agent.name or _display_user(getattr(agent, 'user', None), 'Channel Partner'),
            'email': agent.email or (getattr(agent.user, 'email', '') if getattr(agent, 'user', None) else ''),
            'phone': agent.phone or (getattr(agent.user, 'phone', '') if getattr(agent, 'user', None) else ''),
            'gender': agent.gender or (getattr(agent.user, 'gender', '') if getattr(agent, 'user', None) else '') or 'Other',
            'address': agent.address or (getattr(agent.user, 'address', '') if getattr(agent, 'user', None) else ''),
            'city': agent.city or '',
            'state': agent.state or '',
            'pin_code': agent.pin_code or '',
            'status': agent.status or 'active',
            'photo_url': _employee_agent_photo_url(agent),
            'created_under': created_under,
            'created_by_label': _employee_role_label(creator) if creator else 'System',
            'under_employee': _display_user(agent.under_employee, 'Not Assigned') if getattr(agent, 'under_employee', None) else 'Not Assigned',
            'created_at': agent.created_at.strftime('%Y-%m-%d %H:%M') if agent.created_at else '',
            'documents': user_documents,
            'pan_card_url': document_lookup.get('pan_card', ''),
            'aadhar_card_url': document_lookup.get('aadhaar_card', ''),
            'bank_details_url': document_lookup.get('bank_statement', ''),
            'can_manage': agent.created_by_id == employee_user.id,
        },
        'summary': summary,
        'customers': customers,
    }


@login_required
@require_http_methods(["GET"])
def employee_all_loans(request):
    """Employee: View all loans assigned to them"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    return render(request, 'core/employee/all_loans.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_all_loans_api(request):
    """API endpoint for all loans assigned to employee
    
    Returns:
    - All loans assigned to this employee
    - Summary counts at top (Total, Approved, Rejected, Disbursed)
    - Table data with all required columns
    
    Query Params:
    - search: Search by applicant name, phone, email
    - status: Filter by status
    - page: Pagination
    - limit: Records per page
    """
    if request.user.role != 'employee':
        return Response({
            'success': False,
            'role_mismatch': True,
            'message': 'Employee context not active',
            'summary': {
                'total_loans': 0,
                'approved': 0,
                'rejected': 0,
                'disbursed': 0,
            },
            'loans': [],
            'pagination': {
                'current_page': 1,
                'total_pages': 0,
                'total_items': 0,
                'items_per_page': 0,
            }
        }, status=status.HTTP_200_OK)
    
    try:
        auto_move_overdue_to_follow_up()

        # Get filter parameters
        search = request.GET.get('search', '').strip()
        status_filter = request.GET.get('status', '').strip()
        page = int(request.GET.get('page', 1))
        raw_limit = request.GET.get('limit')
        try:
            limit = int(raw_limit) if raw_limit not in [None, ''] else 2000
        except (TypeError, ValueError):
            limit = 2000
        limit = max(1, min(limit, 5000))
        follow_up_pending_label = 'follow_up_pending'
        follow_up_pending_text = 'Revert Remark '

        # Primary source: Loan table
        queryset = Loan.objects.filter(
            assigned_employee=request.user
        ).select_related('assigned_agent', 'created_by').order_by('-updated_at', '-created_at')

        new_entry_count = 0
        waiting_count = 0
        banking_count = 0
        follow_up_pending_count = 0

        # If no legacy loans, fallback to LoanApplication workflow table
        if not queryset.exists():
            workflow_status_map = {
                'new_entry': 'New Entry',
                'waiting': 'Waiting for Processing',
                UPDATED_DOCUMENT_STATUS_KEY: 'Waiting for Processing',
                'follow_up': 'Required Follow-up',
                follow_up_pending_label: 'New Entry',
                'approved': 'Approved',
                'rejected': 'Rejected',
                'disbursed': 'Disbursed',
            }
            reverse_workflow_status_map = {v: k for k, v in workflow_status_map.items()}
            follow_up_pending_q = Q(status__in=['New Entry', 'Waiting for Processing']) & Q(approval_notes__icontains=follow_up_pending_text)

            app_qs = LoanApplication.objects.filter(
                assigned_employee=request.user
            ).select_related('applicant', 'assigned_agent', 'assigned_by').order_by('-updated_at', '-created_at')

            if search:
                app_qs = app_qs.filter(
                    Q(applicant__full_name__icontains=search) |
                    Q(applicant__mobile__icontains=search) |
                    Q(applicant__email__icontains=search)
                )

            if status_filter == follow_up_pending_label:
                app_qs = app_qs.filter(follow_up_pending_q)
            elif status_filter == UPDATED_DOCUMENT_STATUS_KEY:
                app_qs = app_qs.filter(status='Waiting for Processing').exclude(approval_notes__icontains=follow_up_pending_text)
            elif status_filter:
                mapped_status = workflow_status_map.get(status_filter)
                if mapped_status:
                    app_qs = app_qs.filter(status=mapped_status)
                    if mapped_status in ['New Entry', 'Waiting for Processing']:
                        app_qs = app_qs.exclude(approval_notes__icontains=follow_up_pending_text)

            total_loans = app_qs.count()
            new_entry_count = app_qs.filter(status='New Entry').exclude(approval_notes__icontains=follow_up_pending_text).count()
            waiting_apps = list(app_qs.filter(status='Waiting for Processing').exclude(approval_notes__icontains=follow_up_pending_text))
            updated_document_count = sum(1 for app in waiting_apps if application_has_updated_documents(app))
            waiting_count = len(waiting_apps) - updated_document_count
            banking_count = app_qs.filter(status='Required Follow-up').count()
            follow_up_pending_count = app_qs.filter(follow_up_pending_q).count()
            approved_count = app_qs.filter(status='Approved').count()
            rejected_count = app_qs.filter(status='Rejected').count()
            disbursed_count = app_qs.filter(status='Disbursed').count()

            from django.core.paginator import Paginator
            paginator = Paginator(app_qs, limit)
            page_obj = paginator.get_page(page)

            loans_data = []
            for app in page_obj:
                applicant = app.applicant
                submitted_by = app.assigned_agent.name if app.assigned_agent else 'Unknown'
                processed_by = _display_user(app.assigned_employee, '-')
                partner_under = _partner_under_for(getattr(app, 'assigned_by', None), app.assigned_agent)
                is_follow_up_pending = (
                    app.status in ['New Entry', 'Waiting for Processing']
                    and follow_up_pending_text.lower() in str(app.approval_notes or '').lower()
                )
                is_updated_document = (
                    app.status == 'Waiting for Processing'
                    and not is_follow_up_pending
                    and application_has_updated_documents(app)
                )
                compact_status = (
                    follow_up_pending_label
                    if is_follow_up_pending
                    else (
                        UPDATED_DOCUMENT_STATUS_KEY
                        if is_updated_document
                        else reverse_workflow_status_map.get(app.status, status_filter or 'waiting')
                    )
                )
                status_display = (
                    'Follow Up'
                    if is_follow_up_pending
                    else (
                        UPDATED_DOCUMENT_LABEL
                        if is_updated_document
                        else ('Bank Login Process' if app.status == 'Required Follow-up' else app.status)
                    )
                )
                related_legacy = find_related_loan(app)
                loans_data.append({
                    'id': app.id,
                    'loan_id': display_loan_id(legacy_loan=related_legacy, loan_application=app),
                    'applicant_name': applicant.full_name or 'N/A',
                    'mobile': applicant.mobile or '',
                    'loan_type': applicant.loan_type or 'N/A',
                    'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                    'tenure_months': applicant.tenure_months or 0,
                    'remarks': _employee_clean_remark(app.approval_notes or app.rejection_reason or '', ''),
                    'submitted_by': submitted_by,
                    'processed_by': processed_by,
                    'partner_under': partner_under,
                    'assigned_date': app.assigned_at.strftime('%Y-%m-%d') if app.assigned_at else '-',
                    'created_date': app.created_at.strftime('%Y-%m-%d') if app.created_at else '-',
                    'created_time': app.created_at.strftime('%H:%M') if app.created_at else '',
                    'status': compact_status,
                    'status_display': status_display,
                    'follow_up_pending': is_follow_up_pending,
                    'updated_document': is_updated_document,
                    'entity_type': 'application',
                })
        else:
            if search:
                queryset = queryset.filter(
                    Q(full_name__icontains=search) |
                    Q(mobile_number__icontains=search) |
                    Q(email__icontains=search)
                )

            legacy_loans = list(queryset)
            follow_up_marker = follow_up_pending_text.lower()
            follow_up_pending_cache = {}

            def is_follow_up_pending_loan(loan_obj):
                cached = follow_up_pending_cache.get(loan_obj.id)
                if cached is not None:
                    return cached
                if loan_obj.status not in ['new_entry', 'waiting']:
                    follow_up_pending_cache[loan_obj.id] = False
                    return False

                legacy_has_marker = follow_up_marker in str(loan_obj.remarks or '').lower()
                if legacy_has_marker:
                    follow_up_pending_cache[loan_obj.id] = True
                    return True

                related_app = find_related_loan_application(loan_obj)
                app_has_marker = follow_up_marker in str(getattr(related_app, 'approval_notes', '') or '').lower()
                follow_up_pending_cache[loan_obj.id] = app_has_marker
                return app_has_marker

            def is_updated_document_loan(loan_obj):
                if not loan_obj or loan_obj.status != 'waiting':
                    return False
                if is_follow_up_pending_loan(loan_obj):
                    return False
                return loan_has_updated_documents(loan_obj)

            linked_application_ids = set()
            for legacy_loan in legacy_loans:
                related_app = find_related_loan_application(legacy_loan)
                if related_app:
                    linked_application_ids.add(related_app.id)

            workflow_status_reverse_map = {
                'New Entry': 'new_entry',
                'Waiting for Processing': 'waiting',
                'Required Follow-up': 'follow_up',
                'Approved': 'approved',
                'Rejected': 'rejected',
                'Disbursed': 'disbursed',
            }
            workflow_rows = []
            workflow_only_qs = LoanApplication.objects.filter(
                assigned_employee=request.user
            ).select_related('applicant', 'assigned_agent').exclude(id__in=linked_application_ids).order_by('-updated_at', '-created_at')

            search_lower = search.lower() if search else ''
            follow_up_pending_marker = follow_up_pending_text.lower()
            for app in workflow_only_qs:
                applicant = app.applicant
                related_legacy = find_related_loan(app)
                loan_identifier = display_loan_id(legacy_loan=related_legacy, loan_application=app)
                name_value = applicant.full_name or ''
                mobile_value = applicant.mobile or ''
                email_value = applicant.email or ''

                if search_lower:
                    if (
                        search_lower not in name_value.lower()
                        and search_lower not in mobile_value.lower()
                        and search_lower not in email_value.lower()
                        and search_lower not in loan_identifier.lower()
                    ):
                        continue

                is_follow_up_pending = (
                    app.status in ['New Entry', 'Waiting for Processing']
                    and follow_up_pending_marker in str(app.approval_notes or '').lower()
                )
                is_updated_document = (
                    app.status == 'Waiting for Processing'
                    and not is_follow_up_pending
                    and application_has_updated_documents(app)
                )
                compact_status = (
                    follow_up_pending_label
                    if is_follow_up_pending
                    else (
                        UPDATED_DOCUMENT_STATUS_KEY
                        if is_updated_document
                        else workflow_status_reverse_map.get(app.status, '')
                    )
                )
                if not compact_status:
                    continue

                if status_filter == follow_up_pending_label and not is_follow_up_pending:
                    continue
                if status_filter and status_filter != follow_up_pending_label:
                    if status_filter == UPDATED_DOCUMENT_STATUS_KEY:
                        if not is_updated_document:
                            continue
                    else:
                        if compact_status != status_filter:
                            continue
                        if compact_status in ['new_entry', 'waiting'] and is_follow_up_pending:
                            continue

                submitted_by = app.assigned_agent.name if app.assigned_agent else 'Unknown'
                processed_by = _display_user(app.assigned_employee, '-')
                partner_under = _partner_under_for(getattr(app, 'assigned_by', None), app.assigned_agent)
                workflow_rows.append({
                    'id': app.id,
                    'loan_id': loan_identifier,
                    'applicant_name': name_value or 'N/A',
                    'mobile': mobile_value,
                    'loan_type': applicant.loan_type or 'N/A',
                    'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                    'tenure_months': applicant.tenure_months or 0,
                    'remarks': _employee_clean_remark(app.approval_notes or app.rejection_reason or '', ''),
                    'submitted_by': submitted_by,
                    'processed_by': processed_by,
                    'partner_under': partner_under,
                    'assigned_date': app.assigned_at.strftime('%Y-%m-%d') if app.assigned_at else '-',
                    'created_date': app.created_at.strftime('%Y-%m-%d') if app.created_at else '-',
                    'created_time': app.created_at.strftime('%H:%M') if app.created_at else '',
                    'status': compact_status,
                    'status_display': (
                        'Follow Up'
                        if is_follow_up_pending
                        else (
                            UPDATED_DOCUMENT_LABEL
                            if is_updated_document
                            else ('Bank Login Process' if app.status == 'Required Follow-up' else app.status)
                        )
                    ),
                    'follow_up_pending': is_follow_up_pending,
                    'updated_document': is_updated_document,
                    'entity_type': 'application',
                    '_sort_ts': app.updated_at or app.created_at,
                })

            if status_filter == follow_up_pending_label:
                legacy_loans = [loan for loan in legacy_loans if is_follow_up_pending_loan(loan)]
            elif status_filter == UPDATED_DOCUMENT_STATUS_KEY:
                legacy_loans = [loan for loan in legacy_loans if is_updated_document_loan(loan)]
            elif status_filter:
                legacy_loans = [
                    loan for loan in legacy_loans
                    if loan.status == status_filter and not (
                        status_filter in ['new_entry', 'waiting'] and is_follow_up_pending_loan(loan)
                    )
                ]

            legacy_rows = []
            for loan in legacy_loans:
                submitted_by = 'Unknown'
                if loan.assigned_agent:
                    submitted_by = (
                        loan.assigned_agent.name
                        or (loan.assigned_agent.user.get_full_name() if loan.assigned_agent.user else '')
                        or 'Unknown'
                    )
                processed_by = _display_user(loan.assigned_employee, '-')
                partner_under = _partner_under_for(loan.created_by, loan.assigned_agent)
                is_follow_up_pending = is_follow_up_pending_loan(loan)
                is_updated_document = is_updated_document_loan(loan)
                status_key = (
                    follow_up_pending_label
                    if is_follow_up_pending
                    else (UPDATED_DOCUMENT_STATUS_KEY if is_updated_document else loan.status)
                )
                status_display = (
                    'Follow Up'
                    if is_follow_up_pending
                    else (
                        UPDATED_DOCUMENT_LABEL
                        if is_updated_document
                        else ('Bank Login Process' if loan.status == 'follow_up' else loan.get_status_display())
                    )
                )
                legacy_rows.append({
                    'id': loan.id,
                    'loan_id': display_loan_id(legacy_loan=loan),
                    'applicant_name': loan.full_name or 'N/A',
                    'mobile': loan.mobile_number or '',
                    'loan_type': loan.loan_type or 'N/A',
                    'loan_amount': float(loan.loan_amount) if loan.loan_amount else 0,
                    'tenure_months': loan.tenure_months or 0,
                    'remarks': _employee_clean_remark(loan.remarks, ''),
                    'submitted_by': submitted_by,
                    'processed_by': processed_by,
                    'partner_under': partner_under,
                    'assigned_date': loan.assigned_at.strftime('%Y-%m-%d') if loan.assigned_at else '-',
                    'created_date': loan.created_at.strftime('%Y-%m-%d') if loan.created_at else '-',
                    'created_time': loan.created_at.strftime('%H:%M') if loan.created_at else '',
                    'status': status_key,
                    'status_display': status_display,
                    'follow_up_pending': is_follow_up_pending,
                    'updated_document': is_updated_document,
                    'entity_type': 'legacy',
                    '_sort_ts': loan.updated_at or loan.created_at,
                })

            combined_rows = legacy_rows + workflow_rows
            combined_rows.sort(key=lambda row: row.get('_sort_ts') or timezone.now(), reverse=True)

            total_loans = len(combined_rows)
            new_entry_count = sum(1 for row in combined_rows if row['status'] == 'new_entry')
            waiting_count = sum(1 for row in combined_rows if row['status'] == 'waiting')
            updated_document_count = sum(1 for row in combined_rows if row['status'] == UPDATED_DOCUMENT_STATUS_KEY)
            banking_count = sum(1 for row in combined_rows if row['status'] == 'follow_up')
            follow_up_pending_count = sum(1 for row in combined_rows if row['status'] == follow_up_pending_label)
            approved_count = sum(1 for row in combined_rows if row['status'] == 'approved')
            rejected_count = sum(1 for row in combined_rows if row['status'] == 'rejected')
            disbursed_count = sum(1 for row in combined_rows if row['status'] == 'disbursed')

            from django.core.paginator import Paginator
            paginator = Paginator(combined_rows, limit)
            page_obj = paginator.get_page(page)

            loans_data = []
            for row in page_obj:
                row_payload = dict(row)
                row_payload.pop('_sort_ts', None)
                loans_data.append(row_payload)
        
        return Response({
            'success': True,
            'summary': {
                'total_loans': total_loans,
                'new_entry': new_entry_count,
                'waiting': waiting_count,
                'updated_document': updated_document_count,
                'banking_processing': banking_count,
                'follow_up_pending': follow_up_pending_count,
                'approved': approved_count,
                'rejected': rejected_count,
                'disbursed': disbursed_count,
            },
            'loans': loans_data,
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_items': total_loans,
                'items_per_page': limit,
            }
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# EMPLOYEE NEW ENTRY REQUEST PAGE
# ============================================================

@login_required
@require_http_methods(["GET"])
def employee_new_entry_request_page(request):
    """Render new entry request page for employee"""
    if request.user.role != 'employee':
        return redirect('dashboard')
    
    return render(request, 'core/employee/new_entry_request.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_new_entry_requests_api(request):
    """API endpoint for new entry requests (loans in WAITING or FOLLOWUP status)
    
    Returns:
    - Only loans assigned to this employee
    - Only status = WAITING or FOLLOWUP
    - With Hours Pending calculated
    - All required columns for table
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        auto_move_overdue_to_follow_up()

        # Get filter parameters
        search = request.GET.get('search', '').strip()
        page = int(request.GET.get('page', 1))
        limit = int(request.GET.get('limit', 20))
        
        # Base queryset: ONLY loans assigned to employee with WAITING or FOLLOW_UP status
        queryset = Loan.objects.filter(
            assigned_employee=request.user,
            status__in=['waiting', 'follow_up']
        ).select_related('assigned_agent', 'created_by').order_by('-assigned_at')
        
        # Apply search
        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search) |
                Q(mobile_number__icontains=search) |
                Q(email__icontains=search)
            )
        
        total_count = queryset.count()
        
        # Pagination
        from django.core.paginator import Paginator
        paginator = Paginator(queryset, limit)
        page_obj = paginator.get_page(page)
        
        # Build loan data
        loans_data = []
        for loan in page_obj:
            hours_pending = loan.get_hours_since_assignment() if hasattr(loan, 'get_hours_since_assignment') else 0
            status_key = _employee_effective_status_key(loan)
            
            loans_data.append({
                'id': loan.id,
                    'loan_id': display_loan_id(legacy_loan=loan),
                'applicant_name': loan.full_name or 'N/A',
                'loan_type': loan.loan_type or 'N/A',
                'loan_amount': float(loan.loan_amount) if loan.loan_amount else 0,
                'assigned_date': loan.assigned_at.strftime('%Y-%m-%d %H:%M') if loan.assigned_at else '-',
                'hours_pending': hours_pending,
                'status': status_key,
                'status_display': _employee_status_label(status_key),
            })
        
        return Response({
            'success': True,
            'loans': loans_data,
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_items': total_count,
                'items_per_page': limit,
            }
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# EMPLOYEE LOAN DETAIL PAGE
# ============================================================

def _normalize_detail_source(raw_source):
    source = str(raw_source or '').strip().lower()
    if source in ['application', 'loan_application', 'app']:
        return 'application'
    if source in ['legacy', 'loan']:
        return 'legacy'
    return ''


def _employee_has_assigned_loan(user, loan_id, source=''):
    """Check assignment in both LoanApplication and legacy Loan tables."""
    if source == 'application':
        return LoanApplication.objects.filter(id=loan_id, assigned_employee=user).exists()
    if source == 'legacy':
        return Loan.objects.filter(id=loan_id, assigned_employee=user).exists()
    return _employee_has_assigned_loan(user, loan_id, 'application') or _employee_has_assigned_loan(user, loan_id, 'legacy')


def _subadmin_has_workflow_application(user, loan_id):
    try:
        from .subadmin_views import _subadmin_managed_agents_qs, _subadmin_managed_employees_qs

        managed_employee_ids = list(_subadmin_managed_employees_qs(user).values_list('id', flat=True))
        managed_agent_ids = list(_subadmin_managed_agents_qs(user).values_list('id', flat=True))
        filters = Q(assigned_by=user)
        if managed_employee_ids:
            filters |= Q(assigned_employee_id__in=managed_employee_ids)
        if managed_agent_ids:
            filters |= Q(assigned_agent_id__in=managed_agent_ids)
        return LoanApplication.objects.filter(filters, id=loan_id).exists()
    except Exception:
        return LoanApplication.objects.filter(id=loan_id, assigned_by=user).exists()


def _user_can_open_loan_detail(user, loan_id, source=''):
    source = _normalize_detail_source(source)
    role = getattr(user, 'role', '')
    if role == 'employee':
        return _employee_has_assigned_loan(user, loan_id, source)
    if role == 'agent':
        try:
            agent_profile = Agent.objects.get(user=user)
        except Agent.DoesNotExist:
            return False
        if source == 'application':
            return LoanApplication.objects.filter(Q(assigned_agent=agent_profile) | Q(assigned_by=user), id=loan_id).exists()
        if source == 'legacy':
            return Loan.objects.filter(id=loan_id, assigned_agent=agent_profile).exists()
        return _user_can_open_loan_detail(user, loan_id, 'application') or _user_can_open_loan_detail(user, loan_id, 'legacy')
    if role == 'admin':
        if source == 'application':
            return LoanApplication.objects.filter(id=loan_id).exists()
        if source == 'legacy':
            return Loan.objects.filter(id=loan_id).exists()
        return Loan.objects.filter(id=loan_id).exists() or LoanApplication.objects.filter(id=loan_id).exists()
    if role == 'subadmin':
        try:
            from .subadmin_views import _subadmin_scoped_loans_qs

            if source == 'application':
                return _subadmin_has_workflow_application(user, loan_id)
            if source == 'legacy':
                return _subadmin_scoped_loans_qs(user).filter(id=loan_id).exists()
            return _subadmin_scoped_loans_qs(user).filter(id=loan_id).exists() or _subadmin_has_workflow_application(user, loan_id)
        except Exception:
            return False
    return False


def _resolve_loan_detail_source(user, loan_id, requested_source=''):
    source = _normalize_detail_source(requested_source)
    if source and _user_can_open_loan_detail(user, loan_id, source):
        return source
    if _user_can_open_loan_detail(user, loan_id, 'legacy'):
        return 'legacy'
    if _user_can_open_loan_detail(user, loan_id, 'application'):
        return 'application'
    return source


def _safe_back_path(raw_path):
    back_path = str(raw_path or '').strip()
    if not back_path:
        return ''
    if not back_path.startswith('/'):
        return ''
    if back_path.startswith('//'):
        return ''
    return back_path


def _loan_detail_layout_context(request):
    role = getattr(request.user, 'role', '')
    query_back = _safe_back_path(request.GET.get('back'))

    if role == 'admin':
        return {
            'base_template': 'core/admin/admin_base.html',
            'back_url': query_back or reverse('admin_all_loans'),
            'back_label': 'Back to All Loans',
        }
    if role == 'subadmin':
        return {
            'base_template': 'core/base.html',
            'back_url': query_back or reverse('subadmin_all_loans'),
            'back_label': 'Back to All Loans',
        }
    if role == 'agent':
        return {
            'base_template': 'core/base.html',
            'back_url': query_back or reverse('agent_my_applications'),
            'back_label': 'Back to My Applications',
        }
    return {
        'base_template': 'core/base.html',
        'back_url': query_back or reverse('employee_new_entry_request'),
        'back_label': 'Back',
    }


@login_required
@require_http_methods(["GET"])
def employee_loan_detail_page(request, loan_id):
    """Render loan detail page for employee"""
    if request.user.role not in ['employee', 'agent', 'admin', 'subadmin']:
        return redirect('dashboard')

    entity_type = _resolve_loan_detail_source(
        request.user,
        loan_id,
        request.GET.get('entity_type') or request.GET.get('source'),
    )

    if not entity_type or not _user_can_open_loan_detail(request.user, loan_id, entity_type):
        messages.error(request, 'Loan not found or access denied')
        if request.user.role == 'admin':
            return redirect('admin_all_loans')
        if request.user.role == 'subadmin':
            return redirect('subadmin_all_loans')
        if request.user.role == 'agent':
            return redirect('agent_my_applications')
        return redirect('employee_new_entry_request')

    context = {
        'loan_id': loan_id,
        'entity_type': entity_type,
        'hide_banker_details': is_channel_partner(request.user),
        **_loan_detail_layout_context(request),
    }
    return render(request, 'core/employee/loan_detail.html', context)


@login_required
@require_http_methods(["GET"])
def employee_bank_processing_page(request, loan_id):
    """Dedicated bank processing page for an assigned loan."""
    if request.user.role not in ['employee', 'agent', 'admin', 'subadmin']:
        return redirect('dashboard')

    entity_type = _resolve_loan_detail_source(
        request.user,
        loan_id,
        request.GET.get('entity_type') or request.GET.get('source'),
    )

    if not entity_type or not _user_can_open_loan_detail(request.user, loan_id, entity_type):
        messages.error(request, 'Loan not found or access denied')
        if request.user.role == 'admin':
            return redirect('admin_all_loans')
        if request.user.role == 'subadmin':
            return redirect('subadmin_all_loans')
        if request.user.role == 'agent':
            return redirect('agent_my_applications')
        return redirect('employee_new_entry_request')

    context = {
        'loan_id': loan_id,
        'entity_type': entity_type,
        'is_bank_processing_page': True,
        **_loan_detail_layout_context(request),
    }
    return render(request, 'core/employee/loan_detail.html', context)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_loan_detail_api(request, loan_id):
    """API endpoint for full loan detail
    
    Shows:
    - Full application details (read-only)
    - All uploaded documents
    - Current status
    - Action buttons based on status
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Verify loan is assigned to this employee
        loan = Loan.objects.select_related(
            'assigned_agent', 'assigned_employee', 'created_by'
        ).prefetch_related('documents').get(
            id=loan_id,
            assigned_employee=request.user
        )
        
        # Get documents
        documents = []
        for doc in loan.documents.all():
            documents.append({
                'id': doc.id,
                'type': doc.get_document_type_display(),
                'file_url': doc.file.url if doc.file else None,
                'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M'),
            })
        
        # Get agent info
        agent_name = 'Unknown'
        if loan.assigned_agent:
            agent_name = loan.assigned_agent.name
        
        # Determine available actions based on status
        available_actions = []
        if loan.status in ['waiting', 'follow_up']:
            available_actions = ['approve', 'reject']
        elif loan.status == 'approved':
            available_actions = ['disburse']
        
        hours_pending = loan.get_hours_since_assignment() if hasattr(loan, 'get_hours_since_assignment') else 0
        status_key = _employee_effective_status_key(loan)
        
        return Response({
            'success': True,
            'loan': {
                'id': loan.id,
                'loan_id': display_loan_id(legacy_loan=loan),
                'applicant': {
                    'full_name': loan.full_name,
                    'mobile_number': loan.mobile_number,
                    'email': loan.email,
                    'city': loan.city,
                    'state': loan.state,
                    'pin_code': loan.pin_code,
                },
                'loan_details': {
                    'type': loan.loan_type,
                    'amount': float(loan.loan_amount),
                    'tenure_months': loan.tenure_months,
                    'interest_rate': float(loan.interest_rate) if loan.interest_rate else 0,
                    'emi': float(loan.emi) if loan.emi else 0,
                    'purpose': loan.loan_purpose,
                },
                'bank_details': {
                    'bank_name': loan.bank_name,
                    'account_number': loan.bank_account_number,
                    'ifsc_code': loan.bank_ifsc_code,
                    'type': loan.bank_type,
                },
                'status': status_key,
                'status_display': _employee_status_label(status_key),
                'assigned_date': loan.assigned_at.strftime('%Y-%m-%d %H:%M') if loan.assigned_at else '-',
                'assigned_by_name': loan.created_by.get_full_name() if loan.created_by else 'System',
                'hours_pending': hours_pending,
                'agent_name': agent_name,
                'documents': documents,
                'available_actions': available_actions,
                'remarks': _employee_clean_remark(loan.remarks, ''),
            }
        }, status=status.HTTP_200_OK)
    
    except Loan.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Loan not found or not assigned to you'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# EMPLOYEE LOAN ACTIONS (Approve/Reject/Disburse)
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_approve_loan_api(request, loan_id):
    """Employee approves a loan
    
    - Changes status to APPROVED
    - Sets action_taken_at timestamp
    - Immediately visible in Admin panel
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        loan = Loan.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify status allows approval
        if loan.status not in ['waiting', 'follow_up']:
            return Response({
                'success': False,
                'error': f'Cannot approve loan in {loan.status} status'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Perform approval
        loan.status = 'approved'
        loan.action_taken_at = timezone.now()
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_approved',
            description=f"Employee {request.user.get_full_name()} approved loan for {loan.full_name}",
            user=request.user,
            related_loan=loan
        )
        
        return Response({
            'success': True,
            'message': 'Loan approved successfully',
            'new_status': 'approved'
        }, status=status.HTTP_200_OK)
    
    except Loan.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Loan not found or not assigned to you'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_reject_loan_api(request, loan_id):
    """Employee rejects a loan
    
    - Changes status to REJECTED
    - Sets action_taken_at timestamp
    - Stores rejection reason if provided
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        loan = Loan.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify status allows rejection
        if loan.status not in ['waiting', 'follow_up']:
            return Response({
                'success': False,
                'error': f'Cannot reject loan in {loan.status} status'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get rejection reason
        data = request.data if hasattr(request, 'data') else {}
        rejection_reason = data.get('reason', '').strip() if isinstance(data, dict) else ''
        
        # Perform rejection
        loan.status = 'rejected'
        loan.action_taken_at = timezone.now()
        if rejection_reason:
            loan.remarks = f"Rejection reason: {rejection_reason}"
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_rejected',
            description=f"Employee {request.user.get_full_name()} rejected loan for {loan.full_name}",
            user=request.user,
            related_loan=loan
        )
        
        return Response({
            'success': True,
            'message': 'Loan rejected successfully',
            'new_status': 'rejected'
        }, status=status.HTTP_200_OK)
    
    except Loan.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Loan not found or not assigned to you'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_disburse_loan_api(request, loan_id):
    """Employee marks loan as disbursed
    
    - Changes status to DISBURSED
    - Sets action_taken_at and disbursed_at timestamp
    - Stores disbursement amount if different from loan amount
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        loan = Loan.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify status allows disbursement (must be approved first)
        if loan.status != 'approved':
            return Response({
                'success': False,
                'error': f'Loan must be approved before disbursement. Current status: {loan.status}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get disbursement details
        data = request.data if hasattr(request, 'data') else {}
        disbursement_amount = data.get('amount', str(loan.loan_amount)) if isinstance(data, dict) else str(loan.loan_amount)
        
        try:
            disbursement_amount = Decimal(disbursement_amount)
        except:
            disbursement_amount = loan.loan_amount
        
        # Perform disbursement
        loan.status = 'disbursed'
        loan.action_taken_at = timezone.now()
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_disbursed',
            description=f"Employee {request.user.get_full_name()} disbursed loan for {loan.full_name} - Amount: {disbursement_amount}",
            user=request.user,
            related_loan=loan
        )
        
        return Response({
            'success': True,
            'message': 'Loan disbursed successfully',
            'new_status': 'disbursed'
        }, status=status.HTTP_200_OK)
    
    except Loan.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Loan not found or not assigned to you'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# EMPLOYEE MY AGENTS PAGE
# ============================================================

@login_required
@require_http_methods(["GET"])
def employee_my_agents_page(request):
    """Render my agents page for employee"""
    if request.user.role != 'employee':
        return redirect('dashboard')
    
    return render(request, 'core/employee/my_agents.html')


@login_required
@require_http_methods(["GET"])
def employee_add_channel_partner_page(request):
    """Standalone page for employee-created channel partners."""
    if request.user.role != 'employee':
        return redirect('dashboard')

    return render(request, 'core/employee/add_channel_partner.html')


def _employee_report_queryset(user):
    return Loan.objects.filter(
        Q(assigned_employee=user) | Q(created_by=user)
    ).select_related('assigned_agent', 'assigned_employee', 'created_by').order_by('-updated_at', '-created_at').distinct()


def _employee_report_row(loan):
    status_key = _employee_effective_status_key(loan)
    return {
        'id': loan.id,
        'loan_id': display_loan_id(legacy_loan=loan),
        'applicant_name': loan.full_name or '-',
        'mobile': loan.mobile_number or '-',
        'email': loan.email or '-',
        'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else (loan.loan_type or '-'),
        'loan_amount': float(loan.loan_amount or 0),
        'status': status_key,
        'status_display': _employee_status_label(status_key),
        'channel_partner': _employee_channel_partner_name_for_loan(loan),
        'created_by': _display_user(loan.created_by, 'System'),
        'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else '-',
        'updated_at': loan.updated_at.strftime('%Y-%m-%d %H:%M') if loan.updated_at else '-',
        'view_url': reverse('employee_loan_detail', kwargs={'loan_id': loan.id}),
    }


def _write_employee_report_csv(rows, filename):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow([
        'Loan ID',
        'Applicant Name',
        'Mobile',
        'Email',
        'Loan Type',
        'Loan Amount',
        'Status',
        'Channel Partner',
        'Created By',
        'Created At',
        'Updated At',
    ])
    for row in rows:
        writer.writerow([
            row['loan_id'],
            row['applicant_name'],
            row['mobile'],
            row['email'],
            row['loan_type'],
            row['loan_amount'],
            row['status_display'],
            row['channel_partner'],
            row['created_by'],
            row['created_at'],
            row['updated_at'],
        ])
    return response


@login_required
@require_http_methods(["GET"])
def employee_reports_page(request):
    """Employee reports table with row and full-table downloads."""
    if request.user.role != 'employee':
        return redirect('dashboard')

    rows = [_employee_report_row(loan) for loan in _employee_report_queryset(request.user)]
    loan_id = request.GET.get('loan_id')
    if request.GET.get('download') == 'application' and loan_id:
        selected_rows = [row for row in rows if str(row['id']) == str(loan_id)]
        return _write_employee_report_csv(selected_rows, f'employee-application-{loan_id}.csv')
    if request.GET.get('download') == 'table':
        return _write_employee_report_csv(rows, 'employee-reports.csv')

    status_summary = {
        'total': len(rows),
        'approved': sum(1 for row in rows if row['status'] == 'approved'),
        'rejected': sum(1 for row in rows if row['status'] == 'rejected'),
        'disbursed': sum(1 for row in rows if row['status'] == 'disbursed'),
    }
    return render(request, 'core/employee/reports.html', {
        'rows': rows,
        'status_summary': status_summary,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_my_agents_api(request):
    """Realtime list of channel partners visible under the current employee."""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        search_query = str(request.GET.get('q') or request.GET.get('search') or '').strip()
        status_filter = str(request.GET.get('status') or '').strip().lower()

        agents_qs = Agent.objects.filter(
            Q(created_by=request.user) |
            Q(under_employee=request.user) |
            Q(employee_assignments__employee=request.user)
        ).select_related('user', 'created_by', 'under_employee').order_by('-created_at').distinct()

        if search_query:
            agents_qs = agents_qs.filter(
                Q(agent_id__icontains=search_query) |
                Q(name__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(phone__icontains=search_query) |
                Q(city__icontains=search_query) |
                Q(state__icontains=search_query)
            )

        if status_filter in {'active', 'blocked'}:
            agents_qs = agents_qs.filter(status=status_filter)

        agents_data = []
        totals = {
            'total_agents': 0,
            'active_agents': 0,
            'blocked_agents': 0,
            'total_applications': 0,
            'approved_applications': 0,
            'rejected_applications': 0,
            'disbursed_applications': 0,
            'banking_processing': 0,
            'follow_up_pending': 0,
            'pending_document_cleared': 0,
        }

        for agent in agents_qs:
            payload = _build_employee_agent_payload(request.user, agent, include_customers=False)
            agent_data = payload['agent']
            summary = payload['summary']

            agents_data.append({
                **agent_data,
                'total_loans': summary['total_applications'],
                'approved_count': summary['approved'],
                'rejected_count': summary['rejected'],
                'disbursed_count': summary['disbursed'],
                'banking_processing': summary['banking_processing'],
                'follow_up_pending_count': summary['follow_up_pending'],
                'updated_document_count': summary['updated_document'],
                'waiting_count': summary['waiting'],
            })

            totals['total_agents'] += 1
            if agent_data['status'] == 'active':
                totals['active_agents'] += 1
            else:
                totals['blocked_agents'] += 1
            totals['total_applications'] += summary['total_applications']
            totals['approved_applications'] += summary['approved']
            totals['rejected_applications'] += summary['rejected']
            totals['disbursed_applications'] += summary['disbursed']
            totals['banking_processing'] += summary['banking_processing']
            totals['follow_up_pending'] += summary['follow_up_pending']
            totals['pending_document_cleared'] += summary['updated_document']

        return Response({
            'success': True,
            'stats': totals,
            'agents': agents_data,
            'total': len(agents_data)
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_agent_detail_api(request, agent_id):
    """Detailed employee-scope channel partner payload for modal/table views."""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)

    try:
        agent = get_object_or_404(
            Agent.objects.select_related('user', 'created_by', 'under_employee'),
            Q(id=agent_id) & (
                Q(created_by=request.user) |
                Q(under_employee=request.user) |
                Q(employee_assignments__employee=request.user)
            )
        )
        payload = _build_employee_agent_payload(request.user, agent, include_customers=True)
        return Response({'success': True, **payload}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_add_agent_api(request):
    """Employee adds a new agent under themselves
    
    - Creates new User with role=agent
    - Creates Agent profile linked to employee
    - Agent is marked as Employee-Created
    - Agent also visible in Admin panel
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can add agents'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Get form data
        name = request.data.get('name', '').strip()
        phone = request.data.get('phone', '').strip()
        email = request.data.get('email', '').strip()
        password = request.data.get('password', '').strip()
        city = request.data.get('city', '').strip()
        state = request.data.get('state', '').strip()
        gender = request.data.get('gender', '').strip()
        address = request.data.get('address', '').strip()
        pin_code = request.data.get('pin_code', '').strip()
        photo = request.FILES.get('photo') or request.FILES.get('profile_photo')
        
        # Validate required fields
        if not all([name, phone, email, password]):
            return Response({
                'success': False,
                'error': 'Name, Phone, Email, and Password are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate phone format
        if not phone.isdigit() or len(phone) < 10:
            return Response({
                'success': False,
                'error': 'Invalid phone number. Must be at least 10 digits'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Reuse contact details from deleted/blocked accounts, but block active duplicates.
        if (
            User.objects.filter(email__iexact=email, is_active=True).exists()
            or Agent.objects.filter(email__iexact=email, status='active').exists()
        ):
            return Response({
                'success': False,
                'error': 'Email already exists for an active channel partner'
            }, status=status.HTTP_400_BAD_REQUEST)

        if (
            User.objects.filter(phone=phone, is_active=True).exists()
            or Agent.objects.filter(phone=phone, status='active').exists()
        ):
            return Response({
                'success': False,
                'error': 'Phone number already exists for an active channel partner'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create User account for agent
        username = email.split('@')[0]
        # Make username unique
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role='agent',
            phone=phone,
            first_name=name.split()[0] if name else 'Agent',
            last_name=' '.join(name.split()[1:]) if len(name.split()) > 1 else '',
            gender=gender if gender in ['Male', 'Female', 'Other'] else None,
            address=address,
        )

        if photo:
            user.profile_photo = photo
            user.save(update_fields=['profile_photo', 'updated_at'])
        
        # Create Agent profile
        generated_agent_id = generate_agent_sequence_id(is_sub_channel_partner=False)
        agent = Agent.objects.create(
            user=user,
            agent_id=generated_agent_id,
            name=name,
            phone=phone,
            email=email,
            city=city,
            state=state,
            gender=gender if gender in ['Male', 'Female', 'Other'] else None,
            address=address,
            pin_code=pin_code,
            status='active',
            created_by=request.user,
            under_employee=request.user,
            profile_photo=photo if photo else None,
        )

        AgentAssignment.objects.get_or_create(
            agent=agent,
            employee=request.user,
            defaults={'assigned_by': request.user},
        )
        
        # Log activity
        ActivityLog.objects.create(
            action='agent_created',
            description=f"Employee {request.user.get_full_name()} created agent {name}",
            user=request.user,
            related_agent=agent
        )

        created_payload = _build_employee_agent_payload(request.user, agent, include_customers=False)
        
        return Response({
            'success': True,
            'message': f'Channel partner {name} created successfully',
            'agent_id': agent.id,
            'agent_code': generated_agent_id,
            'agent': created_payload.get('agent', {}),
            'summary': created_payload.get('summary', {}),
        }, status=status.HTTP_201_CREATED)
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_update_agent_api(request, agent_id):
    """Employee updates an agent they created"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can update agents'}, status=status.HTTP_403_FORBIDDEN)

    try:
        agent = get_object_or_404(Agent, id=agent_id, created_by=request.user)
        data = request.data

        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        email = data.get('email', '').strip()
        status_value = data.get('status', '').strip() or agent.status
        gender = data.get('gender', '').strip()
        address = data.get('address', '').strip()
        pin_code = data.get('pin_code', '').strip()
        state = data.get('state', '').strip()
        city = data.get('city', '').strip()

        if name:
            agent.name = name
        if phone:
            phone_exists = (
                User.objects.filter(phone=phone, is_active=True)
                .exclude(id=getattr(agent.user, 'id', None))
                .exists()
                or Agent.objects.filter(phone=phone, status='active').exclude(id=agent.id).exists()
            )
            if phone_exists:
                return Response({
                    'success': False,
                    'error': 'Phone number already exists for an active channel partner'
                }, status=status.HTTP_400_BAD_REQUEST)
            agent.phone = phone
        if email:
            email_exists = (
                User.objects.filter(email__iexact=email, is_active=True)
                .exclude(id=getattr(agent.user, 'id', None))
                .exists()
                or Agent.objects.filter(email__iexact=email, status='active').exclude(id=agent.id).exists()
            )
            if email_exists:
                return Response({
                    'success': False,
                    'error': 'Email already exists for an active channel partner'
                }, status=status.HTTP_400_BAD_REQUEST)
            agent.email = email
        if status_value:
            agent.status = status_value
        agent.gender = gender if gender else agent.gender
        agent.address = address if address else agent.address
        agent.pin_code = pin_code if pin_code else agent.pin_code
        agent.state = state if state else agent.state
        agent.city = city if city else agent.city

        if 'photo' in request.FILES:
            agent.profile_photo = request.FILES.get('photo')

        if not agent.under_employee_id:
            agent.under_employee = request.user

        agent.save()

        if agent.user:
            if name:
                parts = name.split()
                agent.user.first_name = parts[0]
                agent.user.last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''
            if phone:
                agent.user.phone = phone
            if email:
                agent.user.email = email
            if 'photo' in request.FILES:
                agent.user.profile_photo = request.FILES.get('photo')
            agent.user.save()

        return Response({
            'success': True,
            'message': 'Agent updated successfully'
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_delete_agent_api(request, agent_id):
    """Employee deletes (blocks) an agent they created"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can delete agents'}, status=status.HTTP_403_FORBIDDEN)

    try:
        agent = get_object_or_404(Agent, id=agent_id, created_by=request.user)

        agent.status = 'blocked'
        agent.save()

        if agent.user:
            agent.user.is_active = False
            agent.user.save()

        return Response({
            'success': True,
            'message': 'Channel partner removed successfully'
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_update_loan_api(request, loan_id):
    """Employee updates basic loan fields for assigned loan"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can update loans'}, status=status.HTTP_403_FORBIDDEN)

    try:
        loan = get_object_or_404(Loan, id=loan_id, assigned_employee=request.user)
        data = request.data

        if loan.status == 'rejected':
            return Response(
                {'success': False, 'error': 'Rejected loans are view-only.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if 'loan_amount' in data:
            try:
                loan.loan_amount = float(data.get('loan_amount') or 0)
            except (TypeError, ValueError):
                pass
        if 'tenure_months' in data:
            try:
                loan.tenure_months = int(data.get('tenure_months') or 0)
            except (TypeError, ValueError):
                pass
        if 'loan_type' in data and data.get('loan_type'):
            loan.loan_type = str(data.get('loan_type')).lower()
        if 'remarks' in data:
            loan.remarks = upsert_manual_remark(loan.remarks, data.get('remarks'))

        loan.save()

        ActivityLog.objects.create(
            action='loan_updated',
            description=f"Employee {request.user.get_full_name()} updated loan #{loan.id}",
            user=request.user,
            related_loan=loan
        )

        return Response({
            'success': True,
            'message': 'Loan updated successfully'
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_delete_loan_api(request, loan_id):
    """Employee deletes (rejects) an assigned loan"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can delete loans'}, status=status.HTTP_403_FORBIDDEN)

    try:
        from .loan_helpers import delete_loan_by_primary_key

        reason = request.data.get('reason', '').strip() if isinstance(request.data, dict) else ''
        if not reason:
            reason = 'Deleted by employee'

        entity_type = ''
        if isinstance(request.data, dict):
            entity_type = request.data.get('entity_type') or request.data.get('source') or ''

        loan_app = LoanApplication.objects.filter(
            id=loan_id,
            assigned_employee=request.user,
        ).first()
        legacy = Loan.objects.filter(
            id=loan_id,
            assigned_employee=request.user,
        ).first()

        if not loan_app and not legacy:
            return Response(
                {'success': False, 'error': 'Loan already deleted or not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if loan_app and str(loan_app.status or '').strip().lower() == 'rejected':
            return Response(
                {'success': False, 'error': 'Rejected loans can only be removed by admin/partner.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if legacy and str(legacy.status or '').strip().lower() == 'rejected':
            return Response(
                {'success': False, 'error': 'Rejected loans can only be removed by admin/partner.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = delete_loan_by_primary_key(
            loan_id,
            entity_type=entity_type or ('application' if loan_app else 'legacy'),
        )
        if not result.get('success'):
            status_code = result.get('status_code', status.HTTP_400_BAD_REQUEST)
            return Response(
                {'success': False, 'error': result.get('error') or 'Failed to delete loan.'},
                status=status_code,
            )

        ActivityLog.objects.create(
            action='status_updated',
            description=f"Employee {request.user.get_full_name()} deleted loan #{loan_id}. Reason: {reason}",
            user=request.user,
        )

        return Response({
            'success': True,
            'message': result.get('message') or 'Loan removed successfully',
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# LEGACY COMPATIBILITY - Keep old function names
# ============================================================

def employee_assigned_loans(request):
    """Redirect to new entry request page"""
    return employee_new_entry_request_page(request)


def employee_profile(request):
    """Employee profile view"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    context = {'user': request.user}
    return render(request, 'core/employee/profile.html', context)


def employee_settings(request):
    """Employee settings view"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    context = {'user': request.user}
    return render(request, 'core/shared/panel_settings.html', context)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_assigned_loans(request):
    """Legacy API endpoint - redirect to new endpoint"""
    return employee_new_entry_requests_api(request)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_loan_action(request):
    """Legacy endpoint for loan actions"""
    action = request.data.get('action', '').strip()
    loan_id = request.data.get('loan_id')
    
    if action == 'approve':
        return employee_approve_loan_api(request, loan_id)
    elif action == 'reject':
        return employee_reject_loan_api(request, loan_id)
    elif action == 'disburse':
        return employee_disburse_loan_api(request, loan_id)
    else:
        return Response({'error': 'Invalid action'}, status=status.HTTP_400_BAD_REQUEST)

# ============================================================
# EMPLOYEE PROFILE PHOTO UPLOAD
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_upload_profile_photo(request):
    """Upload profile photo for employee
    
    Returns:
    - success: True/False
    - message: Success/error message
    - photo_url: URL of uploaded photo
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        if 'profile_photo' not in request.FILES:
            return Response({'error': 'No photo provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        photo = request.FILES['profile_photo']
        
        # Update user profile photo
        request.user.profile_photo = photo
        request.user.save()
        
        return Response({
            'success': True,
            'message': 'Photo uploaded successfully',
            'photo_url': request.user.profile_photo.url if request.user.profile_photo else None
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
