"""
SubAdmin Panel Views - Production-Grade Implementation
Provides complete visibility and management for SubAdmin role
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum, F, Prefetch, Value, CharField
from django.db.models.functions import Concat
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from .decorators import subadmin_required
from .models import (
    User,
    LoanApplication,
    LoanStatusHistory,
    Complaint,
    SubAdminEntry,
    Loan,
    Agent,
    LoanDocument,
    EmployeeProfile,
    ActivityLog,
)
from .loan_sync import (
    application_status_to_loan_status,
    extract_assignment_context,
    sync_loan_to_application,
)
from django.utils import timezone
from datetime import timedelta
import json
import logging

logger = logging.getLogger(__name__)


def _parse_request_data(request):
    if request.content_type and request.content_type.startswith('application/json'):
        try:
            return json.loads(request.body)
        except json.JSONDecodeError:
            return {}
    return request.POST


def _subadmin_tag(subadmin_user):
    return f"[subadmin:{subadmin_user.id}]"


def _status_label(status_key):
    labels = {
        'draft': 'Draft',
        'new_entry': 'New Entry',
        'waiting': 'In Processing',
        'follow_up': 'Banking Processing',
        'approved': 'Approved',
        'rejected': 'Rejected',
        'disbursed': 'Disbursed',
        'forclose': 'For Close',
        'disputed': 'Disputed',
    }
    return labels.get(status_key, status_key)


def _role_label(user_obj):
    if not user_obj:
        return 'System'
    return {
        'admin': 'Admin',
        'subadmin': 'SubAdmin',
        'employee': 'Employee',
        'agent': 'Agent',
        'dsa': 'DSA',
    }.get(user_obj.role, (user_obj.role or 'User').title())


def _extract_assignment_marker(loan_obj):
    if not loan_obj:
        return '-'

    assignment_context = extract_assignment_context(loan_obj)
    display = assignment_context.get('assigned_by_display', '-')
    return display or '-'


def _latest_bank_remark(loan_obj):
    remarks = []
    if loan_obj.remarks:
        remarks.append(str(loan_obj.remarks).strip())

    related_app = None
    if loan_obj.email and loan_obj.mobile_number:
        related_app = LoanApplication.objects.filter(
            applicant__email__iexact=loan_obj.email,
            applicant__mobile=loan_obj.mobile_number,
        ).first()
    if not related_app and loan_obj.full_name and loan_obj.mobile_number:
        related_app = LoanApplication.objects.filter(
            applicant__full_name__iexact=loan_obj.full_name,
            applicant__mobile=loan_obj.mobile_number,
        ).first()

    if related_app:
        if related_app.approval_notes:
            remarks.append(str(related_app.approval_notes).strip())
        if related_app.rejection_reason:
            remarks.append(str(related_app.rejection_reason).strip())
        reasons = list(
            related_app.status_history.exclude(reason__isnull=True)
            .exclude(reason__exact='')
            .values_list('reason', flat=True)[:5]
        )
        remarks.extend([str(item).strip() for item in reasons if item])

    unique = []
    seen = set()
    for item in remarks:
        clean = (item or '').strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(clean)
    return " | ".join(unique)[:700] if unique else '-'


def _find_related_loan_application(loan_obj):
    if not loan_obj:
        return None

    if loan_obj.email and loan_obj.mobile_number:
        app = LoanApplication.objects.filter(
            applicant__email__iexact=loan_obj.email,
            applicant__mobile=loan_obj.mobile_number,
        ).select_related('applicant').first()
        if app:
            return app

    if loan_obj.full_name and loan_obj.mobile_number:
        app = LoanApplication.objects.filter(
            applicant__full_name__iexact=loan_obj.full_name,
            applicant__mobile=loan_obj.mobile_number,
        ).select_related('applicant').first()
        if app:
            return app

    if loan_obj.email and loan_obj.full_name:
        app = LoanApplication.objects.filter(
            applicant__email__iexact=loan_obj.email,
            applicant__full_name__iexact=loan_obj.full_name,
        ).select_related('applicant').first()
        if app:
            return app

    return None


def _serialize_subadmin_loan_details(loan_obj):
    loan_app = _find_related_loan_application(loan_obj)
    applicant = loan_app.applicant if loan_app else None

    created_by = loan_obj.created_by
    created_by_name = (
        (created_by.get_full_name() or created_by.username) if created_by else '-'
    )
    created_by_display = f"{_role_label(created_by)} - {created_by_name}" if created_by else 'System'
    assigned_employee_name = (
        loan_obj.assigned_employee.get_full_name() or loan_obj.assigned_employee.username
        if loan_obj.assigned_employee else '-'
    )
    assigned_agent_name = loan_obj.assigned_agent.name if loan_obj.assigned_agent else '-'

    # Build document list from both Loan and LoanApplication sources
    documents = []
    seen_urls = set()

    for doc in LoanDocument.objects.filter(loan=loan_obj).order_by('-uploaded_at'):
        file_url = doc.file.url if doc.file else ''
        if not file_url or file_url in seen_urls:
            continue
        seen_urls.add(file_url)
        documents.append({
            'name': doc.get_document_type_display() if hasattr(doc, 'get_document_type_display') else (doc.document_type or 'Document'),
            'url': file_url,
            'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else '',
            'source': 'Loan',
        })

    if loan_app:
        for doc in loan_app.documents.all().order_by('-uploaded_at'):
            file_url = doc.file.url if doc.file else ''
            if not file_url or file_url in seen_urls:
                continue
            seen_urls.add(file_url)
            documents.append({
                'name': doc.get_document_type_display() if hasattr(doc, 'get_document_type_display') else (doc.document_type or 'Document'),
                'url': file_url,
                'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else '',
                'source': 'Application',
            })

    timeline = []
    if loan_app:
        for row in loan_app.status_history.select_related('changed_by').order_by('-changed_at')[:50]:
            changed_by = row.changed_by.get_full_name() if row.changed_by else 'System'
            timeline.append({
                'from_status': _status_label(row.from_status) if row.from_status else '-',
                'to_status': _status_label(row.to_status),
                'reason': row.reason or '-',
                'changed_by': changed_by,
                'changed_at': row.changed_at.strftime('%Y-%m-%d %H:%M') if row.changed_at else '',
            })

    return {
        'id': loan_obj.id,
        'loan_id': loan_obj.user_id or f"LOAN-{loan_obj.id:06d}",
        'status': loan_obj.status,
        'status_display': _status_label(loan_obj.status),
        'created_at': loan_obj.created_at.strftime('%Y-%m-%d %H:%M') if loan_obj.created_at else '',
        'updated_at': loan_obj.updated_at.strftime('%Y-%m-%d %H:%M') if loan_obj.updated_at else '',
        'created_under': created_by_display,
        'assigned_employee': assigned_employee_name,
        'assigned_agent': assigned_agent_name,
        'assigned_by': _extract_assignment_marker(loan_obj),

        'full_name': loan_obj.full_name or '-',
        'mobile_number': loan_obj.mobile_number or '-',
        'email': loan_obj.email or '-',
        'city': loan_obj.city or '-',
        'state': loan_obj.state or '-',
        'pin_code': loan_obj.pin_code or '-',
        'permanent_address': loan_obj.permanent_address or '-',
        'current_address': loan_obj.current_address or '-',

        'loan_type': loan_obj.get_loan_type_display() if hasattr(loan_obj, 'get_loan_type_display') else (loan_obj.loan_type or '-'),
        'loan_amount': float(loan_obj.loan_amount or 0),
        'tenure_months': loan_obj.tenure_months or '-',
        'interest_rate': float(loan_obj.interest_rate or 0) if loan_obj.interest_rate is not None else '-',
        'emi': float(loan_obj.emi or 0) if loan_obj.emi is not None else '-',
        'loan_purpose': loan_obj.loan_purpose or '-',

        'bank_name': loan_obj.bank_name or '-',
        'bank_account_number': loan_obj.bank_account_number or '-',
        'bank_ifsc_code': loan_obj.bank_ifsc_code or '-',
        'bank_type': loan_obj.bank_type or '-',
        'bank_remark': _latest_bank_remark(loan_obj),

        'co_applicant_name': loan_obj.co_applicant_name or '-',
        'co_applicant_phone': loan_obj.co_applicant_phone or '-',
        'co_applicant_email': loan_obj.co_applicant_email or '-',
        'guarantor_name': loan_obj.guarantor_name or '-',
        'guarantor_phone': loan_obj.guarantor_phone or '-',
        'guarantor_email': loan_obj.guarantor_email or '-',

        'remarks': loan_obj.remarks or '-',
        'remarks_lines': [line.strip() for line in str(loan_obj.remarks or '').splitlines() if line.strip()],
        'documents': documents,
        'status_timeline': timeline,

        # Extra enrichment from LoanApplication/Applicant where available
        'applicant_name_from_application': getattr(applicant, 'full_name', '-') if applicant else '-',
        'applicant_mobile_from_application': getattr(applicant, 'mobile', '-') if applicant else '-',
        'applicant_email_from_application': getattr(applicant, 'email', '-') if applicant else '-',
    }


def _mark_employee_under_subadmin(employee, subadmin_user):
    profile, _ = EmployeeProfile.objects.get_or_create(user=employee)
    tag = _subadmin_tag(subadmin_user)
    notes = (profile.notes or '').strip()
    if tag not in notes:
        profile.notes = f"{notes}\n{tag}".strip() if notes else tag
        profile.save(update_fields=['notes', 'updated_at'])
    return profile


def _subadmin_managed_employees_qs(subadmin_user):
    tag = _subadmin_tag(subadmin_user)
    return User.objects.filter(role='employee').filter(
        Q(employee_profile__notes__icontains=tag) |
        Q(loans_as_employee__assigned_agent__created_by=subadmin_user) |
        Q(loans_as_employee__created_by=subadmin_user) |
        Q(created_loans__assigned_agent__created_by=subadmin_user)
    ).distinct()


def _subadmin_managed_agents_qs(subadmin_user):
    managed_employee_ids = list(
        _subadmin_managed_employees_qs(subadmin_user).values_list('id', flat=True)
    )
    filters = Q(created_by=subadmin_user)
    if managed_employee_ids:
        filters |= Q(loans__assigned_employee_id__in=managed_employee_ids)
    return Agent.objects.filter(filters).distinct()


def _subadmin_scoped_loans_qs(subadmin_user):
    managed_employee_ids = list(
        _subadmin_managed_employees_qs(subadmin_user).values_list('id', flat=True)
    )
    managed_agent_ids = list(
        _subadmin_managed_agents_qs(subadmin_user).values_list('id', flat=True)
    )

    filters = Q(created_by=subadmin_user)
    if managed_agent_ids:
        filters |= Q(assigned_agent_id__in=managed_agent_ids)
        filters |= Q(created_by__agent_profile__id__in=managed_agent_ids)
    if managed_employee_ids:
        filters |= Q(assigned_employee_id__in=managed_employee_ids)
        filters |= Q(created_by_id__in=managed_employee_ids)

    return Loan.objects.filter(filters).distinct()


# ============ DASHBOARD ============

@login_required(login_url='login')
@subadmin_required
def subadmin_dashboard(request):
    """
    SubAdmin Dashboard - Overview of all managed loans and team
    Shows:
    - Total loans by status
    - Team metrics (agents, employees)
    - Recent activities
    - Quick action cards
    """
    user = request.user
    
    # Get all loans under this subadmin scope
    all_loans = _subadmin_scoped_loans_qs(user).select_related(
        'assigned_employee', 'assigned_agent', 'created_by'
    )
    
    # Calculate statistics
    total_loans = all_loans.count()
    
    # Loan status breakdown
    status_stats = {
        'total': total_loans,
        'new_entry': all_loans.filter(status='new_entry').count(),
        'waiting': all_loans.filter(status='waiting').count(),
        'follow_up': all_loans.filter(status='follow_up').count(),
        'approved': all_loans.filter(status='approved').count(),
        'rejected': all_loans.filter(status='rejected').count(),
        'disbursed': all_loans.filter(status='disbursed').count(),
    }
    
    # Calculate percentages
    total_for_percent = total_loans if total_loans > 0 else 1
    status_stats['new_entry_pct'] = int((status_stats['new_entry'] / total_for_percent) * 100)
    status_stats['waiting_pct'] = int((status_stats['waiting'] / total_for_percent) * 100)
    status_stats['follow_up_pct'] = int((status_stats['follow_up'] / total_for_percent) * 100)
    status_stats['approved_pct'] = int((status_stats['approved'] / total_for_percent) * 100)
    status_stats['rejected_pct'] = int((status_stats['rejected'] / total_for_percent) * 100)
    status_stats['disbursed_pct'] = int((status_stats['disbursed'] / total_for_percent) * 100)
    
    # Loan amount statistics
    status_stats['total_value'] = all_loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    status_stats['approved_value'] = all_loans.filter(status='approved').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    status_stats['disbursed_value'] = all_loans.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    
    # Team statistics
    managed_agents_qs = _subadmin_managed_agents_qs(user)
    managed_employees_qs = _subadmin_managed_employees_qs(user)
    active_agents = managed_agents_qs.filter(status='active').count()
    all_agents = managed_agents_qs.count()
    active_employees = managed_employees_qs.filter(is_active=True).count()
    all_employees = managed_employees_qs.count()
    
    team_stats = {
        'active_agents': active_agents,
        'all_agents': all_agents,
        'active_employees': active_employees,
        'all_employees': all_employees,
        'total_team': active_agents + active_employees,
    }
    
    # Monthly loan trend (last 6 months)
    from datetime import datetime, timedelta
    monthly_data = []
    for i in range(5, -1, -1):
        start_date = timezone.now().replace(day=1) - timedelta(days=30*i)
        end_date = start_date + timedelta(days=30)
        
        month_loans = all_loans.filter(
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        
        monthly_data.append({
            'month': start_date.strftime('%b %Y'),
            'total': month_loans.count(),
            'approved': month_loans.filter(status='approved').count(),
            'disbursed': month_loans.filter(status='disbursed').count(),
        })
    
    context = {
        'page_title': 'SubAdmin Dashboard',
        'status_stats': status_stats,
        'team_stats': team_stats,
        'monthly_data': monthly_data,
    }
    
    return render(request, 'subadmin/subadmin_dashboard.html', context)


@login_required(login_url='login')
@subadmin_required
@require_http_methods(['GET'])
def api_subadmin_dashboard_stats(request):
    """
    SubAdmin Dashboard Stats API
    Returns JSON with dashboard statistics for dynamic loading
    """
    try:
        subadmin_user = request.user
        all_loans = _subadmin_scoped_loans_qs(subadmin_user)
        
        # Loan status breakdown
        status_stats = {
            'total': all_loans.count(),
            'new_entry': all_loans.filter(status='new_entry').count(),
            'waiting': all_loans.filter(status='waiting').count(),
            'follow_up': all_loans.filter(status='follow_up').count(),
            'approved': all_loans.filter(status='approved').count(),
            'rejected': all_loans.filter(status='rejected').count(),
            'disbursed': all_loans.filter(status='disbursed').count(),
        }
        
        # Calculate percentages
        total_for_percent = status_stats['total'] if status_stats['total'] > 0 else 1
        status_stats['new_entry_pct'] = int((status_stats['new_entry'] / total_for_percent) * 100)
        status_stats['waiting_pct'] = int((status_stats['waiting'] / total_for_percent) * 100)
        status_stats['follow_up_pct'] = int((status_stats['follow_up'] / total_for_percent) * 100)
        status_stats['approved_pct'] = int((status_stats['approved'] / total_for_percent) * 100)
        status_stats['rejected_pct'] = int((status_stats['rejected'] / total_for_percent) * 100)
        status_stats['disbursed_pct'] = int((status_stats['disbursed'] / total_for_percent) * 100)
        
        # Loan amount statistics
        status_stats['total_value'] = all_loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
        
        # Team statistics (subadmin scope)
        managed_agents_qs = _subadmin_managed_agents_qs(subadmin_user)
        managed_employees_qs = _subadmin_managed_employees_qs(subadmin_user)
        active_agents = managed_agents_qs.filter(status='active').count()
        all_agents = managed_agents_qs.count()
        active_employees = managed_employees_qs.filter(is_active=True).count()
        all_employees = managed_employees_qs.count()
        
        team_stats = {
            'active_agents': active_agents,
            'all_agents': all_agents,
            'active_employees': active_employees,
            'all_employees': all_employees,
            'total_team': active_agents + active_employees,
        }
        
        # Backward + forward compatible payload
        return JsonResponse({
            'success': True,
            'status_stats': status_stats,
            'team_stats': team_stats,
            'stats': status_stats,
            'total': status_stats['total'],
            'new_entry': status_stats['new_entry'],
            'waiting': status_stats['waiting'],
            'in_processing': status_stats['waiting'],
            'follow_up': status_stats['follow_up'],
            'banking_processing': status_stats['follow_up'],
            'approved': status_stats['approved'],
            'rejected': status_stats['rejected'],
            'disbursed': status_stats['disbursed'],
        })
    except Exception as e:
        logger.error(f"Error in api_subadmin_dashboard_stats: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


@login_required(login_url='login')
@subadmin_required
@require_http_methods(['GET'])
def api_subadmin_recent_loans(request):
    """Return recent scoped loans for subadmin dashboard table."""
    try:
        loans_qs = _subadmin_scoped_loans_qs(request.user).select_related(
            'created_by',
            'assigned_employee',
            'assigned_agent',
        ).order_by('-created_at')[:25]

        rows = []
        for loan in loans_qs:
            creator = loan.created_by
            creator_name = (creator.get_full_name() or creator.username) if creator else '-'
            creator_role = _role_label(creator)
            rows.append({
                'id': loan.id,
                'loan_id': loan.user_id or f"LOAN-{loan.id}",
                'full_name': loan.full_name or '-',
                'mobile_number': loan.mobile_number or '-',
                'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else (loan.loan_type or '-'),
                'loan_amount': float(loan.loan_amount or 0),
                'status': loan.status,
                'status_display': _status_label(loan.status),
                'created_under': f"{creator_role} - {creator_name}",
                'assigned_to': (
                    f"Employee - {loan.assigned_employee.get_full_name() or loan.assigned_employee.username}"
                    if loan.assigned_employee else (
                        f"Agent - {loan.assigned_agent.name}" if loan.assigned_agent else '-'
                    )
                ),
                'created_at': loan.created_at.isoformat() if loan.created_at else '',
            })

        return JsonResponse({'success': True, 'results': rows})
    except Exception as e:
        logger.error(f"Error in api_subadmin_recent_loans: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============ MY ALL LOANS ============

@login_required(login_url='login')
@subadmin_required
def subadmin_all_loans(request):
    """
    SubAdmin - All Loans Page
    Shows ALL loans in system with advanced filtering
    
    Features:
    - Search by Loan ID, Name, Phone
    - Filter by Status
    - Filter by Agent / Employee
    - Date range filter
    - Sortable columns
    - Real-time counts
    """
    # Start with scoped loans only
    scoped_loans = _subadmin_scoped_loans_qs(request.user).select_related(
        'assigned_employee', 'assigned_agent', 'created_by'
    )
    loans_qs = scoped_loans
    
    # Apply filters
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    agent_filter = request.GET.get('agent', '')
    employee_filter = request.GET.get('employee', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # Search filter
    if search_query:
        loans_qs = loans_qs.filter(
            Q(full_name__icontains=search_query) |
            Q(mobile_number__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(user_id__icontains=search_query)
        )
    
    # Status filter
    if status_filter and status_filter != 'all':
        loans_qs = loans_qs.filter(status=status_filter)
    
    managed_agents_qs = _subadmin_managed_agents_qs(request.user)
    managed_employees_qs = _subadmin_managed_employees_qs(request.user)
    managed_agent_ids = list(managed_agents_qs.values_list('id', flat=True))
    managed_employee_ids = list(managed_employees_qs.values_list('id', flat=True))

    # Agent filter
    if agent_filter:
        loans_qs = loans_qs.filter(assigned_agent_id=agent_filter)
    
    # Employee filter
    if employee_filter:
        loans_qs = loans_qs.filter(assigned_employee_id=employee_filter)
    
    # Date range filter
    if date_from:
        try:
            from datetime import datetime
            start_date = datetime.strptime(date_from, '%Y-%m-%d')
            loans_qs = loans_qs.filter(created_at__gte=start_date)
        except:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            end_date = datetime.strptime(date_to, '%Y-%m-%d')
            loans_qs = loans_qs.filter(created_at__lte=end_date)
        except:
            pass
    
    # Order by latest first
    loans_qs = loans_qs.order_by('-created_at')
    
    # Get filter options (scoped)
    agents = managed_agents_qs.values('id', 'name').distinct()
    employees = managed_employees_qs.values('id', 'first_name', 'last_name').distinct()

    # Real-time counts (scoped)
    all_loans_count = scoped_loans.count()
    status_counts = {
        'new_entry': scoped_loans.filter(status='new_entry').count(),
        'waiting': scoped_loans.filter(status='waiting').count(),
        'follow_up': scoped_loans.filter(status='follow_up').count(),
        'approved': scoped_loans.filter(status='approved').count(),
        'rejected': scoped_loans.filter(status='rejected').count(),
        'disbursed': scoped_loans.filter(status='disbursed').count(),
    }
    
    # Pagination
    paginator = Paginator(loans_qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Format loans for display
    loans_list = []
    for loan in page_obj:
        creator_role = _role_label(loan.created_by)
        creator_name = (loan.created_by.get_full_name() or loan.created_by.username) if loan.created_by else '-'
        assigned_to = '-'
        if loan.assigned_employee:
            assigned_to = f"Employee - {loan.assigned_employee.get_full_name() or loan.assigned_employee.username}"
        elif loan.assigned_agent:
            assigned_to = f"Agent - {loan.assigned_agent.name}"

        loans_list.append({
            'id': loan.id,
            'loan_id': loan.user_id or f'LOAN-{loan.id:06d}',
            'applicant_name': loan.full_name,
            'phone': loan.mobile_number,
            'email': loan.email or '-',
            'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else loan.loan_type,
            'amount': loan.loan_amount,
            'agent': loan.assigned_agent.name if loan.assigned_agent else 'Unassigned',
            'employee': loan.assigned_employee.get_full_name() if loan.assigned_employee else 'Unassigned',
            'assigned_to': assigned_to,
            'status': loan.status,
            'status_display': _status_label(loan.status),
            'created_under': f"{creator_role} - {creator_name}",
            'assigned_by': _extract_assignment_marker(loan),
            'created_date': loan.created_at,
        })
    
    context = {
        'page_title': 'All Loans',
        'loans': loans_list,
        'paginator': paginator,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'total_loans': all_loans_count,
        'status_counts': status_counts,
        'agents': agents,
        'employees': employees,
        'search_query': search_query,
        'status_filter': status_filter,
        'agent_filter': agent_filter,
        'employee_filter': employee_filter,
        'date_from': date_from,
        'date_to': date_to,
        'stats': {
            'total': all_loans_count,
            'new_entry': status_counts['new_entry'],
            'processing': status_counts['waiting'],
            'follow_up': status_counts['follow_up'],
            'approved': status_counts['approved'],
            'rejected': status_counts['rejected'],
            'disbursed': status_counts['disbursed'],
        },
        'employees_for_assign': managed_employees_qs.order_by('first_name', 'last_name'),
    }
    
    return render(request, 'subadmin/subadmin_all_loans.html', context)


# ============ LOAN DETAIL ============

@login_required(login_url='login')
@subadmin_required
def subadmin_loan_detail(request, loan_id):
    """
    SubAdmin Loan Detail Page
    Shows:
    - Full loan application (read-only)
    - All uploaded documents
    - Assignment section (can reassign)
    - Status history timeline
    - Internal remarks
    """
    loan = get_object_or_404(_subadmin_scoped_loans_qs(request.user), id=loan_id)
    
    # Get loan documents
    documents = LoanDocument.objects.filter(loan=loan).order_by('-uploaded_at')

    # LoanStatusHistory is linked with LoanApplication, so map through related application
    history_timeline = []
    loan_application = _find_related_loan_application(loan)
    if loan_application:
        for history in loan_application.status_history.select_related('changed_by').order_by('-changed_at')[:60]:
            history_timeline.append({
                'status': _status_label(history.to_status),
                'timestamp': history.changed_at,
                'changed_by': history.changed_by.get_full_name() if history.changed_by else 'System',
                'remarks': history.reason,
            })

    # Get available employees for reassignment (subadmin scope only)
    available_employees = _subadmin_managed_employees_qs(request.user).filter(is_active=True)
    
    context = {
        'page_title': f'Loan Detail - {loan.full_name}',
        'loan': loan,
        'documents': documents,
        'history_timeline': history_timeline,
        'available_employees': available_employees,
        'loan_payload': _serialize_subadmin_loan_details(loan),
    }
    
    return render(request, 'subadmin/subadmin_loan_detail.html', context)


@login_required(login_url='login')
@subadmin_required
@require_GET
def api_subadmin_loan_details(request, loan_id):
    """Scoped full loan details for subadmin loan view modal/page."""
    try:
        loan = get_object_or_404(
            _subadmin_scoped_loans_qs(request.user).select_related(
                'created_by',
                'assigned_employee',
                'assigned_agent',
            ),
            id=loan_id,
        )
        payload = _serialize_subadmin_loan_details(loan)
        return JsonResponse({'success': True, 'data': payload})
    except Exception as e:
        logger.error(f"Error in api_subadmin_loan_details: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required(login_url='login')
@subadmin_required
@require_POST
def subadmin_assign_employee_api(request, loan_id):
    """
    API: Assign/Reassign employee to loan
    """
    try:
        loan = get_object_or_404(_subadmin_scoped_loans_qs(request.user), id=loan_id)
        payload = _parse_request_data(request)
        employee_id = str(payload.get('employee_id', '')).strip()
        remarks = str(payload.get('remarks', '')).strip()
        
        if not employee_id:
            return JsonResponse({'error': 'Employee ID required'}, status=400)
        
        employee = get_object_or_404(_subadmin_managed_employees_qs(request.user), id=employee_id)
        related_application = _find_related_loan_application(loan)
        previous_app_status_key = application_status_to_loan_status(related_application.status) if related_application else None
        previous_assigned_employee_id = related_application.assigned_employee_id if related_application else None

        # Update loan assignment + workflow status
        old_employee = loan.assigned_employee
        old_status = loan.status
        loan.assigned_employee = employee
        loan.assigned_at = timezone.now()
        if loan.status in ['new_entry', 'draft']:
            loan.status = 'waiting'

        subadmin_name = request.user.get_full_name() or request.user.username
        employee_name = employee.get_full_name() or employee.username
        assignment_line = f"Assigned By SubAdmin: {subadmin_name} -> Employee: {employee_name}"
        if remarks:
            assignment_line = f"{assignment_line} | Remark: {remarks}"

        if loan.remarks:
            loan.remarks = f"{loan.remarks}\n{assignment_line}"
        else:
            loan.remarks = assignment_line
        loan.save()

        # Ensure employee appears under this subadmin ownership
        _mark_employee_under_subadmin(employee, request.user)

        synced_application = sync_loan_to_application(
            loan,
            assigned_by_user=request.user,
            create_if_missing=True,
        )

        if synced_application:
            current_app_status_key = application_status_to_loan_status(synced_application.status)
            if previous_app_status_key != current_app_status_key or previous_assigned_employee_id != employee.id:
                LoanStatusHistory.objects.create(
                    loan_application=synced_application,
                    from_status=previous_app_status_key,
                    to_status=current_app_status_key,
                    changed_by=request.user,
                    reason=remarks or f'Assigned to {employee_name} by subadmin',
                    is_auto_triggered=False,
                )

        try:
            from_name = old_employee.get_full_name() if old_employee else 'Unassigned'
            ActivityLog.objects.create(
                action='status_updated',
                description=(
                    f"SubAdmin assigned loan {loan.user_id or loan.id} from {from_name} "
                    f"to {employee_name} (status: {_status_label(old_status)} -> {_status_label(loan.status)})"
                ),
                user=request.user,
                related_loan=loan,
            )
        except Exception:
            pass
        
        return JsonResponse({
            'success': True,
            'message': f'Loan assigned to {employee_name}',
            'status': loan.status,
            'status_display': _status_label(loan.status),
        })
    
    except Exception as e:
        logger.error(f"Error assigning employee: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


# ============ MY AGENTS ============

@login_required(login_url='login')
@subadmin_required
def subadmin_my_agents(request):
    """
    SubAdmin - My Agents Page
    Shows ALL agents and sub-agents with stats
    
    Columns:
    - Name
    - Email
    - Phone
    - Created By
    - Total Loans
    - Status
    - Action: View
    """
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        agent_id = request.POST.get('agent_id', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        gender = request.POST.get('gender', '').strip()
        address = request.POST.get('address', '').strip()
        password = request.POST.get('password', '').strip()
        profile_photo = request.FILES.get('profile_photo')

        # Basic validation
        if not all([name, agent_id, email, phone, password]):
            messages.error(request, 'Please fill all required agent fields.')
            return redirect('subadmin_my_agents')

        if '@' not in email:
            messages.error(request, 'Invalid email address.')
            return redirect('subadmin_my_agents')

        if len(password) < 6:
            messages.error(request, 'Password must be at least 6 characters.')
            return redirect('subadmin_my_agents')

        phone_digits = phone.replace('+', '')
        if not phone_digits.isdigit() or len(phone_digits) < 10 or len(phone_digits) > 15:
            messages.error(request, 'Phone number must be 10-15 digits.')
            return redirect('subadmin_my_agents')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists.')
            return redirect('subadmin_my_agents')

        if User.objects.filter(username=agent_id).exists() or Agent.objects.filter(agent_id=agent_id).exists():
            messages.error(request, 'Agent ID already exists.')
            return redirect('subadmin_my_agents')

        if User.objects.filter(phone=phone).exists() or Agent.objects.filter(phone=phone).exists():
            messages.error(request, 'Phone number already exists.')
            return redirect('subadmin_my_agents')

        if profile_photo and profile_photo.size > 5 * 1024 * 1024:
            messages.error(request, 'Profile photo must be less than 5MB.')
            return redirect('subadmin_my_agents')

        gender_value = gender if gender in ['Male', 'Female', 'Other'] else None
        name_parts = name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        try:
            with transaction.atomic():
                agent_user = User.objects.create_user(
                    username=agent_id,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    role='agent',
                    phone=phone,
                    gender=gender_value,
                    address=address,
                    is_active=True,
                )

                if profile_photo:
                    agent_user.profile_photo = profile_photo
                    agent_user.save()

                agent = Agent.objects.create(
                    user=agent_user,
                    agent_id=agent_id,
                    name=name,
                    phone=phone,
                    email=email,
                    address=address,
                    gender=gender_value,
                    status='active',
                    created_by=request.user,
                )

                if profile_photo and not agent.profile_photo:
                    agent.profile_photo = agent_user.profile_photo or profile_photo
                    agent.save()

            messages.success(request, f'Agent {name} created successfully. Login ID: {agent_id}')
        except Exception as e:
            logger.error(f"Error creating agent: {str(e)}")
            messages.error(request, f'Error creating agent: {str(e)}')

        return redirect('subadmin_my_agents')

    agents_qs = _subadmin_managed_agents_qs(request.user).select_related('user', 'created_by')
    
    # Search filter
    search_query = request.GET.get('q', '').strip()
    if search_query:
        agents_qs = agents_qs.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(agent_id__icontains=search_query)
        )
    
    # Status filter
    status_filter = request.GET.get('status', '')
    if status_filter:
        agents_qs = agents_qs.filter(status=status_filter)
    
    # Add loan counts
    agents_qs = agents_qs.annotate(
        agent_total_loans=Count('loans'),
        agent_approved_count=Count('loans', filter=Q(loans__status='approved')),
    )
    
    agents_qs = agents_qs.order_by('-created_at')
    
    # Real-time counts (scoped)
    total_agents = agents_qs.count()
    active_agents = agents_qs.filter(status='active').count()
    blocked_agents = agents_qs.filter(status='blocked').count()
    
    # Pagination
    paginator = Paginator(agents_qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    agents_list = []
    for agent in page_obj:
        photo_url = ''
        if agent.profile_photo:
            photo_url = agent.profile_photo.url
        elif agent.user and agent.user.profile_photo:
            photo_url = agent.user.profile_photo.url

        agents_list.append({
            'id': agent.id,
            'agent_id': agent.agent_id or f'AG{agent.id:04d}',
            'name': agent.name,
            'email': agent.email or 'N/A',
            'phone': agent.phone,
            'gender': agent.gender or 'N/A',
            'address': agent.address or 'N/A',
            'created_by': agent.created_by.get_full_name() if agent.created_by else 'Admin',
            'total_loans': agent.agent_total_loans,
            'approved_count': agent.agent_approved_count,
            'status': agent.status,
            'created_date': agent.created_at.strftime('%Y-%m-%d'),
            'photo_url': photo_url,
        })
    
    context = {
        'page_title': 'All Agents',
        'agents': agents_list,
        'paginator': paginator,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'total_agents': total_agents,
        'active_agents': active_agents,
        'blocked_agents': blocked_agents,
        'search_query': search_query,
        'status_filter': status_filter,
    }
    
    return render(request, 'subadmin/subadmin_my_staff.html', context)


@login_required(login_url='login')
@subadmin_required
def subadmin_agent_detail(request, agent_id):
    """
    SubAdmin Agent Detail Page
    Shows:
    - Agent profile
    - Loans submitted by agent
    - Loan status summary
    """
    agent = get_object_or_404(_subadmin_managed_agents_qs(request.user), id=agent_id)
    
    # Get scoped loans from this agent
    loans = _subadmin_scoped_loans_qs(request.user).filter(
        Q(assigned_agent=agent) | (Q(created_by=agent.user) if agent.user else Q(id__in=[]))
    ).select_related('assigned_employee')
    
    # Status breakdown
    loan_stats = {
        'total': loans.count(),
        'new_entry': loans.filter(status='new_entry').count(),
        'waiting': loans.filter(status='waiting').count(),
        'follow_up': loans.filter(status='follow_up').count(),
        'approved': loans.filter(status='approved').count(),
        'rejected': loans.filter(status='rejected').count(),
        'disbursed': loans.filter(status='disbursed').count(),
    }
    
    # Amount stats
    loan_stats['total_amount'] = loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    loan_stats['disbursed_amount'] = loans.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    
    context = {
        'page_title': f'Agent Detail - {agent.name}',
        'agent': agent,
        'loan_stats': loan_stats,
        'loans': loans[:10],  # Latest 10
    }
    
    return render(request, 'subadmin/subadmin_my_staff.html', context)


@login_required(login_url='login')
@subadmin_required
@require_GET
def subadmin_get_agent(request, agent_id):
    try:
        agent = get_object_or_404(_subadmin_managed_agents_qs(request.user), id=agent_id)
        photo_url = ''
        if agent.profile_photo:
            photo_url = agent.profile_photo.url
        elif agent.user and agent.user.profile_photo:
            photo_url = agent.user.profile_photo.url

        scoped_loans_qs = _subadmin_scoped_loans_qs(request.user).filter(
            Q(assigned_agent=agent) | (Q(created_by=agent.user) if agent.user else Q(id__in=[]))
        ).select_related('created_by', 'assigned_employee', 'assigned_agent').order_by('-created_at').distinct()

        submitted_qs = Loan.objects.none()
        if agent.user:
            submitted_qs = scoped_loans_qs.filter(created_by=agent.user)
        assigned_qs = scoped_loans_qs.filter(assigned_agent=agent)

        customers = []
        for loan in scoped_loans_qs[:250]:
            owner = loan.created_by
            owner_role = _role_label(owner)
            owner_name = (owner.get_full_name() or owner.username) if owner else '-'
            source = 'Submitted' if (agent.user and loan.created_by_id == agent.user.id) else 'Assigned'
            assigned_to = '-'
            if loan.assigned_employee:
                assigned_to = f"Employee - {loan.assigned_employee.get_full_name() or loan.assigned_employee.username}"
            elif loan.assigned_agent:
                assigned_to = f"Agent - {loan.assigned_agent.name}"

            customers.append({
                'loan_id': loan.id,
                'loan_uid': loan.user_id or f'LOAN-{loan.id}',
                'customer_name': loan.full_name or '-',
                'mobile': loan.mobile_number or '-',
                'email': loan.email or '-',
                'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else (loan.loan_type or '-'),
                'loan_amount': float(loan.loan_amount or 0),
                'status': loan.status,
                'status_display': _status_label(loan.status),
                'source': source,
                'assigned_to': assigned_to,
                'under_whom': f"{owner_role} - {owner_name}",
                'owner_role': owner_role,
                'owner_name': owner_name,
                'assigned_by': _extract_assignment_marker(loan),
                'bank_remark': _latest_bank_remark(loan),
                'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else '',
            })

        summary = {
            'total_submitted_applications': submitted_qs.count(),
            'total_assigned_applications': assigned_qs.count(),
            'total_applications': scoped_loans_qs.count(),
            'approved': scoped_loans_qs.filter(status='approved').count(),
            'rejected': scoped_loans_qs.filter(status='rejected').count(),
            'banking_processing': scoped_loans_qs.filter(status='follow_up').count(),
            'waiting': scoped_loans_qs.filter(status='waiting').count(),
            'disbursed': scoped_loans_qs.filter(status='disbursed').count(),
            'total_customers': scoped_loans_qs.count(),
        }

        return JsonResponse({
            'success': True,
            'agent': {
                'id': agent.id,
                'agent_id': agent.agent_id or f'AG{agent.id:04d}',
                'name': agent.name,
                'email': agent.email or '',
                'phone': agent.phone or '',
                'gender': agent.gender or 'Other',
                'address': agent.address or '',
                'status': agent.status or 'active',
                'photo_url': photo_url,
            },
            'summary': summary,
            'customers': customers,
        })
    except Exception as e:
        logger.error(f"Error fetching agent: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required(login_url='login')
@subadmin_required
@require_POST
def subadmin_update_agent(request, agent_id):
    try:
        agent = get_object_or_404(_subadmin_managed_agents_qs(request.user), id=agent_id)
        data = _parse_request_data(request)
        profile_photo = request.FILES.get('profile_photo')

        name = data.get('name', '').strip()
        agent_id_val = data.get('agent_id', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        gender = data.get('gender', '').strip()
        address = data.get('address', '').strip()
        password = data.get('password', '').strip()
        status_val = data.get('status', '').strip() or agent.status

        if email:
            if User.objects.filter(email=email).exclude(id=getattr(agent.user, 'id', None)).exists():
                return JsonResponse({'success': False, 'error': 'Email already exists'}, status=400)

        if agent_id_val:
            if Agent.objects.filter(agent_id=agent_id_val).exclude(id=agent.id).exists():
                return JsonResponse({'success': False, 'error': 'Agent ID already exists'}, status=400)
            if User.objects.filter(username=agent_id_val).exclude(id=getattr(agent.user, 'id', None)).exists():
                return JsonResponse({'success': False, 'error': 'Agent ID already exists'}, status=400)

        if phone:
            phone_exists = (
                User.objects.filter(phone=phone).exclude(id=getattr(agent.user, 'id', None)).exists() or
                Agent.objects.filter(phone=phone).exclude(id=agent.id).exists()
            )
            if phone_exists:
                return JsonResponse({'success': False, 'error': 'Phone number already exists'}, status=400)

        gender_value = gender if gender in ['Male', 'Female', 'Other'] else None

        with transaction.atomic():
            if name:
                agent.name = name
                if agent.user:
                    parts = name.split(' ', 1)
                    agent.user.first_name = parts[0]
                    agent.user.last_name = parts[1] if len(parts) > 1 else ''

            if agent_id_val:
                agent.agent_id = agent_id_val
                if agent.user:
                    agent.user.username = agent_id_val

            if email:
                agent.email = email
                if agent.user:
                    agent.user.email = email

            if phone:
                agent.phone = phone
                if agent.user:
                    agent.user.phone = phone

            if address is not None:
                agent.address = address
                if agent.user:
                    agent.user.address = address

            if gender_value:
                agent.gender = gender_value
                if agent.user:
                    agent.user.gender = gender_value

            if status_val in ['active', 'blocked']:
                agent.status = status_val
                if agent.user:
                    agent.user.is_active = status_val == 'active'

            if profile_photo:
                if agent.user:
                    agent.user.profile_photo = profile_photo
                agent.profile_photo = profile_photo

            if agent.user:
                if password:
                    agent.user.set_password(password)
                agent.user.save()

            agent.save()

        return JsonResponse({'success': True, 'message': 'Agent updated successfully'})
    except Exception as e:
        logger.error(f"Error updating agent: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required(login_url='login')
@subadmin_required
@require_POST
def subadmin_delete_agent(request, agent_id):
    try:
        agent = get_object_or_404(_subadmin_managed_agents_qs(request.user), id=agent_id)
        agent.status = 'blocked'
        agent.save()

        if agent.user:
            agent.user.is_active = False
            agent.user.save()

        return JsonResponse({'success': True, 'message': 'Agent deleted successfully'})
    except Exception as e:
        logger.error(f"Error deleting agent: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============ MY EMPLOYEES ============

@login_required(login_url='login')
@subadmin_required
def subadmin_my_employees(request):
    """
    SubAdmin - My Employees Page
    Shows ALL employees with performance stats
    
    Columns:
    - Employee ID
    - Name
    - Email
    - Phone
    - Assigned Loans
    - Approved
    - Rejected
    - Status
    - Action: View
    """
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        employee_id = request.POST.get('employee_id', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        gender = request.POST.get('gender', '').strip()
        address = request.POST.get('address', '').strip()
        password = request.POST.get('password', '').strip()
        profile_photo = request.FILES.get('profile_photo')

        # Basic validation
        if not all([name, employee_id, email, phone, password]):
            messages.error(request, 'Please fill all required employee fields.')
            return redirect('subadmin_my_employees')

        if '@' not in email:
            messages.error(request, 'Invalid email address.')
            return redirect('subadmin_my_employees')

        if len(password) < 6:
            messages.error(request, 'Password must be at least 6 characters.')
            return redirect('subadmin_my_employees')

        phone_digits = phone.replace('+', '')
        if not phone_digits.isdigit() or len(phone_digits) < 10 or len(phone_digits) > 15:
            messages.error(request, 'Phone number must be 10-15 digits.')
            return redirect('subadmin_my_employees')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists.')
            return redirect('subadmin_my_employees')

        if User.objects.filter(employee_id=employee_id).exists():
            messages.error(request, 'Employee ID already exists.')
            return redirect('subadmin_my_employees')

        if User.objects.filter(phone=phone).exists():
            messages.error(request, 'Phone number already exists.')
            return redirect('subadmin_my_employees')

        if profile_photo and profile_photo.size > 5 * 1024 * 1024:
            messages.error(request, 'Profile photo must be less than 5MB.')
            return redirect('subadmin_my_employees')

        gender_value = gender if gender in ['Male', 'Female', 'Other'] else None
        name_parts = name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        # Generate unique username from email
        base_username = email.split('@')[0]
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        try:
            with transaction.atomic():
                employee = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    role='employee',
                    employee_id=employee_id,
                    phone=phone,
                    gender=gender_value,
                    address=address,
                    is_active=True,
                )

                if profile_photo:
                    employee.profile_photo = profile_photo
                    employee.save()

                EmployeeProfile.objects.get_or_create(user=employee)
                _mark_employee_under_subadmin(employee, request.user)

            messages.success(request, f'Employee {name} created successfully.')
        except Exception as e:
            logger.error(f"Error creating employee: {str(e)}")
            messages.error(request, f'Error creating employee: {str(e)}')

        return redirect('subadmin_my_employees')

    employees_qs = _subadmin_managed_employees_qs(request.user)
    
    # Search filter
    search_query = request.GET.get('q', '').strip()
    if search_query:
        employees_qs = employees_qs.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(employee_id__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    
    # Status filter
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        employees_qs = employees_qs.filter(is_active=True)
    elif status_filter == 'inactive':
        employees_qs = employees_qs.filter(is_active=False)
    
    scoped_loan_ids = list(_subadmin_scoped_loans_qs(request.user).values_list('id', flat=True))
    # Add scoped loan counts
    employees_qs = employees_qs.annotate(
        total_assigned_loans=Count('loans_as_employee', filter=Q(loans_as_employee__id__in=scoped_loan_ids)),
        total_approved_count=Count('loans_as_employee', filter=Q(loans_as_employee__id__in=scoped_loan_ids, loans_as_employee__status='approved')),
        total_rejected_count=Count('loans_as_employee', filter=Q(loans_as_employee__id__in=scoped_loan_ids, loans_as_employee__status='rejected')),
    )
    
    employees_qs = employees_qs.order_by('-created_at')
    
    # Real-time counts (scoped)
    total_employees = employees_qs.count()
    active_employees = employees_qs.filter(is_active=True).count()
    
    # Pagination
    paginator = Paginator(employees_qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    employees_list = []
    for emp in page_obj:
        photo_url = emp.profile_photo.url if emp.profile_photo else ''
        employees_list.append({
            'id': emp.id,
            'employee_id': emp.employee_id or f'EMP{emp.id:04d}',
            'name': emp.get_full_name() or emp.username,
            'email': emp.email,
            'phone': emp.phone or 'N/A',
            'gender': emp.gender or 'N/A',
            'address': emp.address or 'N/A',
            'assigned_loans': emp.total_assigned_loans,
            'approved': emp.total_approved_count,
            'rejected': emp.total_rejected_count,
            'status': 'Active' if emp.is_active else 'Inactive',
            'created_date': emp.created_at.strftime('%Y-%m-%d'),
            'photo_url': photo_url,
        })
    
    context = {
        'page_title': 'All Employees',
        'employees': employees_list,
        'paginator': paginator,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'total_employees': total_employees,
        'active_employees': active_employees,
        'search_query': search_query,
        'status_filter': status_filter,
    }
    
    return render(request, 'subadmin/subadmin_my_employee.html', context)


@login_required(login_url='login')
@subadmin_required
def subadmin_employee_detail(request, employee_id):
    """
    SubAdmin Employee Detail Page
    Shows:
    - Employee profile
    - Assigned loans
    - Performance summary
    - Agents under this employee (if any)
    """
    employee = get_object_or_404(_subadmin_managed_employees_qs(request.user), id=employee_id)
    
    # Get assigned loans
    loans = _subadmin_scoped_loans_qs(request.user).filter(
        Q(assigned_employee=employee) | Q(created_by=employee)
    )
    
    # Performance stats
    perf_stats = {
        'total': loans.count(),
        'approved': loans.filter(status='approved').count(),
        'rejected': loans.filter(status='rejected').count(),
        'pending': loans.filter(status__in=['waiting', 'follow_up']).count(),
        'disbursed': loans.filter(status='disbursed').count(),
    }
    
    # Calculate approval rate
    if perf_stats['total'] > 0:
        perf_stats['approval_rate'] = int((perf_stats['approved'] / perf_stats['total']) * 100)
    else:
        perf_stats['approval_rate'] = 0
    
    context = {
        'page_title': f'Employee Detail - {employee.get_full_name()}',
        'employee': employee,
        'perf_stats': perf_stats,
        'loans': loans[:10],  # Latest 10
    }
    
    return render(request, 'subadmin/subadmin_my_employee.html', context)


@login_required(login_url='login')
@subadmin_required
@require_GET
def subadmin_get_employee(request, employee_id):
    try:
        user = get_object_or_404(_subadmin_managed_employees_qs(request.user), id=employee_id)
        profile = getattr(user, 'employee_profile', None)

        scoped_loans_qs = _subadmin_scoped_loans_qs(request.user).filter(
            Q(assigned_employee=user) | Q(created_by=user)
        ).select_related('created_by', 'assigned_employee', 'assigned_agent').order_by('-created_at').distinct()

        submitted_qs = scoped_loans_qs.filter(created_by=user)
        assigned_qs = scoped_loans_qs.filter(assigned_employee=user)

        customers = []
        for loan in scoped_loans_qs[:250]:
            owner = loan.created_by
            owner_role = _role_label(owner)
            owner_name = (owner.get_full_name() or owner.username) if owner else '-'
            source = 'Submitted' if loan.created_by_id == user.id else 'Assigned'
            assigned_to = '-'
            if loan.assigned_employee:
                assigned_to = f"Employee - {loan.assigned_employee.get_full_name() or loan.assigned_employee.username}"
            elif loan.assigned_agent:
                assigned_to = f"Agent - {loan.assigned_agent.name}"

            customers.append({
                'loan_id': loan.id,
                'loan_uid': loan.user_id or f'LOAN-{loan.id}',
                'customer_name': loan.full_name or '-',
                'mobile': loan.mobile_number or '-',
                'email': loan.email or '-',
                'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else (loan.loan_type or '-'),
                'loan_amount': float(loan.loan_amount or 0),
                'status': loan.status,
                'status_display': _status_label(loan.status),
                'source': source,
                'assigned_to': assigned_to,
                'under_whom': f"{owner_role} - {owner_name}",
                'owner_role': owner_role,
                'owner_name': owner_name,
                'assigned_by': _extract_assignment_marker(loan),
                'bank_remark': _latest_bank_remark(loan),
                'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else '',
            })

        summary = {
            'total_submitted_applications': submitted_qs.count(),
            'total_assigned_applications': assigned_qs.count(),
            'total_applications': scoped_loans_qs.count(),
            'approved': scoped_loans_qs.filter(status='approved').count(),
            'rejected': scoped_loans_qs.filter(status='rejected').count(),
            'banking_processing': scoped_loans_qs.filter(status='follow_up').count(),
            'waiting': scoped_loans_qs.filter(status='waiting').count(),
            'disbursed': scoped_loans_qs.filter(status='disbursed').count(),
            'total_customers': scoped_loans_qs.count(),
        }

        return JsonResponse({
            'success': True,
            'employee': {
                'id': user.id,
                'employee_id': user.employee_id or f'EMP{user.id:04d}',
                'name': user.get_full_name() or user.username,
                'email': user.email or '',
                'phone': user.phone or '',
                'gender': user.gender or 'Other',
                'address': user.address or '',
                'status': 'active' if user.is_active else 'inactive',
                'photo_url': user.profile_photo.url if user.profile_photo else '',
                'role': profile.employee_role if profile else 'loan_processor',
            },
            'summary': summary,
            'customers': customers,
        })
    except Exception as e:
        logger.error(f"Error fetching employee: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required(login_url='login')
@subadmin_required
@require_POST
def subadmin_update_employee(request, employee_id):
    try:
        user = get_object_or_404(_subadmin_managed_employees_qs(request.user), id=employee_id)
        data = _parse_request_data(request)
        profile_photo = request.FILES.get('profile_photo')

        name = data.get('name', '').strip()
        employee_id_val = data.get('employee_id', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        gender = data.get('gender', '').strip()
        address = data.get('address', '').strip()
        password = data.get('password', '').strip()
        status_val = data.get('status', '').strip()

        if email:
            if User.objects.filter(email=email).exclude(id=user.id).exists():
                return JsonResponse({'success': False, 'error': 'Email already exists'}, status=400)

        if employee_id_val:
            if User.objects.filter(employee_id=employee_id_val).exclude(id=user.id).exists():
                return JsonResponse({'success': False, 'error': 'Employee ID already exists'}, status=400)

        if phone:
            if User.objects.filter(phone=phone).exclude(id=user.id).exists():
                return JsonResponse({'success': False, 'error': 'Phone number already exists'}, status=400)

        gender_value = gender if gender in ['Male', 'Female', 'Other'] else None

        with transaction.atomic():
            if name:
                parts = name.split(' ', 1)
                user.first_name = parts[0]
                user.last_name = parts[1] if len(parts) > 1 else ''

            if employee_id_val:
                user.employee_id = employee_id_val

            if email:
                user.email = email

            if phone:
                user.phone = phone

            if address is not None:
                user.address = address

            if gender_value:
                user.gender = gender_value

            if status_val in ['active', 'inactive']:
                user.is_active = status_val == 'active'

            if password:
                user.set_password(password)

            if profile_photo:
                user.profile_photo = profile_photo

            user.save()

            EmployeeProfile.objects.get_or_create(user=user)

        return JsonResponse({'success': True, 'message': 'Employee updated successfully'})
    except Exception as e:
        logger.error(f"Error updating employee: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required(login_url='login')
@subadmin_required
@require_POST
def subadmin_delete_employee(request, employee_id):
    try:
        user = get_object_or_404(_subadmin_managed_employees_qs(request.user), id=employee_id)
        user.is_active = False
        user.save()
        return JsonResponse({'success': True, 'message': 'Employee deleted successfully'})
    except Exception as e:
        logger.error(f"Error deleting employee: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============ REPORTS ============

@login_required(login_url='login')
@subadmin_required
def subadmin_reports(request):
    """
    SubAdmin Reports Page
    Shows:
    - Loan count by status
    - Monthly disbursement
    - Employee performance
    - Agent performance
    - Charts and analytics
    """
    all_loans = _subadmin_scoped_loans_qs(request.user)
    managed_employees_qs = _subadmin_managed_employees_qs(request.user)
    managed_agents_qs = _subadmin_managed_agents_qs(request.user)
    
    # Overall statistics
    report_stats = {
        'total_applications': all_loans.count(),
        'total_approved': all_loans.filter(status='approved').count(),
        'total_rejected': all_loans.filter(status='rejected').count(),
        'total_disbursed': all_loans.filter(status='disbursed').count(),
        'total_value': all_loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
        'disbursed_value': all_loans.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
    }
    
    # Calculate approval rate
    if report_stats['total_applications'] > 0:
        report_stats['approval_rate'] = int((report_stats['total_approved'] / report_stats['total_applications']) * 100)
    else:
        report_stats['approval_rate'] = 0
    
    # Employee performance
    scoped_loan_ids = list(all_loans.values_list('id', flat=True))
    top_employees = managed_employees_qs.annotate(
        emp_total_loans=Count('loans_as_employee', filter=Q(loans_as_employee__id__in=scoped_loan_ids)),
        emp_approved_count=Count(
            'loans_as_employee',
            filter=Q(loans_as_employee__id__in=scoped_loan_ids, loans_as_employee__status='approved')
        ),
    ).order_by('-emp_approved_count')[:10]
    
    employee_performance = []
    for emp in top_employees:
        if emp.emp_total_loans > 0:
            rate = int((emp.emp_approved_count / emp.emp_total_loans) * 100)
        else:
            rate = 0
        
        employee_performance.append({
            'name': emp.get_full_name(),
            'total': emp.emp_total_loans,
            'approved': emp.emp_approved_count,
            'rate': rate,
        })
    
    # Agent performance
    top_agents = managed_agents_qs.annotate(
        agent_total_loans=Count('loans', filter=Q(loans__id__in=scoped_loan_ids)),
        agent_approved_count=Count('loans', filter=Q(loans__id__in=scoped_loan_ids, loans__status='approved')),
    ).order_by('-agent_total_loans')[:10]
    
    agent_performance = []
    for agent in top_agents:
        if agent.agent_total_loans > 0:
            rate = int((agent.agent_approved_count / agent.agent_total_loans) * 100)
        else:
            rate = 0
        
        agent_performance.append({
            'name': agent.name,
            'total': agent.agent_total_loans,
            'approved': agent.agent_approved_count,
            'rate': rate,
        })
    
    # Monthly trend
    monthly_trend = []
    for i in range(11, -1, -1):
        month_date = timezone.now() - timedelta(days=30*i)
        month_start = month_date.replace(day=1)
        month_end = (month_date + timedelta(days=30)).replace(day=1)
        
        month_loans = all_loans.filter(created_at__gte=month_start, created_at__lt=month_end)
        
        monthly_trend.append({
            'month': month_start.strftime('%b %Y'),
            'applications': month_loans.count(),
            'approved': month_loans.filter(status='approved').count(),
            'rejected': month_loans.filter(status='rejected').count(),
            'disbursed': month_loans.filter(status='disbursed').count(),
            'value': month_loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
        })
    reports = {
        'total_applications': report_stats['total_applications'],
        'approval_rate': report_stats['approval_rate'],
        'avg_processing_days': 0,
        'total_disbursed': report_stats['disbursed_value'],
        'loans_processed': report_stats['total_applications'],
        'loans_approved': report_stats['total_approved'],
        'loans_rejected': report_stats['total_rejected'],
        'loans_pending': all_loans.filter(status__in=['new_entry', 'waiting', 'follow_up']).count(),
        'loans_disbursed': report_stats['total_disbursed'],
        'total_employees': managed_employees_qs.count(),
        'active_employees': managed_employees_qs.filter(is_active=True).count(),
        'avg_loans_per_employee': (
            round(report_stats['total_applications'] / managed_employees_qs.count(), 2)
            if managed_employees_qs.count() > 0 else 0
        ),
        'top_performer': employee_performance[0]['name'] if employee_performance else '-',
        'performance_score': report_stats['approval_rate'] / 10,
        'monthly_trend': [
            {
                'month': row['month'],
                'new': row['applications'],
                'approved': row['approved'],
                'rejected': row['rejected'],
                'disbursed': row['disbursed'],
            } for row in monthly_trend
        ],
    }

    context = {
        'page_title': 'Reports & Analytics',
        'report_stats': report_stats,
        'employee_performance': employee_performance,
        'agent_performance': agent_performance,
        'monthly_trend': monthly_trend,
        'reports': reports,
    }
    
    return render(request, 'subadmin/subadmin_reports.html', context)


# ============ COMPLAINTS ============

@login_required(login_url='login')
@subadmin_required
def subadmin_complaints(request):
    """
    SubAdmin Complaints Page
    Shows:
    - All complaints with status
    - Ability to add remarks
    - Update status
    - Track resolution
    """
    scoped_loans_qs = _subadmin_scoped_loans_qs(request.user)
    managed_employees_qs = _subadmin_managed_employees_qs(request.user)
    managed_agents_qs = _subadmin_managed_agents_qs(request.user)

    base_complaints_qs = Complaint.objects.filter(
        Q(loan__in=scoped_loans_qs) |
        Q(filed_by_employee__in=managed_employees_qs) |
        Q(filed_by_agent__in=managed_agents_qs) |
        Q(created_by=request.user)
    ).select_related('loan', 'filed_by_employee', 'filed_by_agent')
    complaints_qs = base_complaints_qs
    
    # Search filter
    search_query = request.GET.get('q', '').strip()
    if search_query:
        complaints_qs = complaints_qs.filter(
            Q(complaint_id__icontains=search_query) |
            Q(customer_name__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    # Status filter
    status_filter = request.GET.get('status', '')
    if status_filter:
        complaints_qs = complaints_qs.filter(status=status_filter)
    
    complaints_qs = complaints_qs.order_by('-created_at')
    
    # Status counts
    complaint_counts = {
        'total': base_complaints_qs.count(),
        'open': base_complaints_qs.filter(status='open').count(),
        'in_progress': base_complaints_qs.filter(status='in_progress').count(),
        'resolved': base_complaints_qs.filter(status='resolved').count(),
    }
    
    # Pagination
    paginator = Paginator(complaints_qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    complaints_list = []
    for complaint in page_obj:
        status_label = complaint.get_status_display() if hasattr(complaint, 'get_status_display') else complaint.status
        priority_label = complaint.get_priority_display() if hasattr(complaint, 'get_priority_display') else complaint.priority
        category_label = complaint.get_complaint_type_display() if hasattr(complaint, 'get_complaint_type_display') else complaint.complaint_type
        complainant = complaint.customer_name or '-'
        if complaint.filed_by_employee:
            complainant = complaint.filed_by_employee.get_full_name() or complaint.filed_by_employee.username or complaint.customer_name
        elif complaint.filed_by_agent:
            complainant = complaint.filed_by_agent.name or complaint.customer_name

        complaints_list.append({
            'id': complaint.complaint_id or complaint.id,
            'subject': complaint.description,
            'description': complaint.description,
            'status': status_label,
            'status_key': complaint.status,
            'priority': priority_label,
            'priority_key': complaint.priority,
            'category': category_label,
            'complainant_name': complainant,
            'date': complaint.created_at,
            'created_date': complaint.created_at.strftime('%Y-%m-%d'),
            'loan_id': complaint.loan.id if complaint.loan else None,
        })
    
    context = {
        'page_title': 'Complaints Management',
        'complaints': complaints_list,
        'paginator': paginator,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'complaint_counts': complaint_counts,
        'stats': complaint_counts,
        'search_query': search_query,
        'status_filter': status_filter,
    }
    
    return render(request, 'subadmin/subadmin_complaints.html', context)


# ============ SETTINGS ============

@login_required(login_url='login')
@subadmin_required
def subadmin_settings(request):
    """
    SubAdmin Settings Page
    - Profile update
    - Password change
    - Notification preferences
    """
    user = request.user
    
    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        if action == 'upload_photo':
            profile_photo = request.FILES.get('profile_photo')
            if not profile_photo:
                return JsonResponse({'success': False, 'message': 'Please select a photo to upload.'}, status=400)

            if profile_photo.size > 5 * 1024 * 1024:
                return JsonResponse({'success': False, 'message': 'Profile photo must be less than 5MB.'}, status=400)

            content_type = getattr(profile_photo, 'content_type', '') or ''
            if content_type and not content_type.startswith('image/'):
                return JsonResponse({'success': False, 'message': 'Only image files are allowed.'}, status=400)

            user.profile_photo = profile_photo
            user.save(update_fields=['profile_photo', 'updated_at'])
            return JsonResponse({
                'success': True,
                'message': 'Profile photo updated successfully.',
                'photo_url': user.profile_photo.url if user.profile_photo else '',
            })
        
        if action == 'update_profile':
            first_name = (request.POST.get('first_name') or '').strip()
            last_name = (request.POST.get('last_name') or '').strip()
            email = (request.POST.get('email') or '').strip()
            phone = (request.POST.get('phone') or '').strip()

            if email and User.objects.filter(email__iexact=email).exclude(id=user.id).exists():
                return JsonResponse({'success': False, 'message': 'Email is already in use.'}, status=400)

            user.first_name = first_name
            user.last_name = last_name
            user.email = email
            user.phone = phone
            user.save(update_fields=['first_name', 'last_name', 'email', 'phone', 'updated_at'])
            return JsonResponse({'success': True, 'message': 'Profile updated successfully.'})
        
        if action == 'change_password':
            old_password = (request.POST.get('old_password') or '').strip()
            new_password = (request.POST.get('new_password') or '').strip()

            if not old_password or not new_password:
                return JsonResponse({'success': False, 'message': 'Current and new password are required.'}, status=400)

            if len(new_password) < 6:
                return JsonResponse({'success': False, 'message': 'New password must be at least 6 characters.'}, status=400)

            if not user.check_password(old_password):
                return JsonResponse({'success': False, 'message': 'Current password is incorrect.'}, status=400)

            user.set_password(new_password)
            user.save()
            update_session_auth_hash(request, user)
            return JsonResponse({'success': True, 'message': 'Password changed successfully.'})

        return JsonResponse({'success': False, 'message': 'Invalid action.'}, status=400)
    
    context = {
        'page_title': 'Settings',
        'user': user,
    }
    
    return render(request, 'subadmin/subadmin_settings.html', context)


# ============ ADD NEW LOAN ============

@login_required(login_url='login')
@subadmin_required
@require_http_methods(['GET', 'POST'])
def subadmin_add_loan(request):
    """
    SubAdmin Add New Loan - Create new loan applications
    """
    if request.method == 'POST':
        try:
            # Extract form data
            applicant_name = request.POST.get('applicant_name')
            applicant_email = request.POST.get('applicant_email')
            applicant_mobile = request.POST.get('applicant_mobile')
            fathers_name = request.POST.get('fathers_name')
            dob = request.POST.get('dob')
            gender = request.POST.get('gender')
            
            permanent_address = request.POST.get('permanent_address')
            permanent_city = request.POST.get('permanent_city')
            permanent_pin = request.POST.get('permanent_pin')
            
            occupation = request.POST.get('occupation')
            year_of_experience = request.POST.get('year_of_experience')
            monthly_income = request.POST.get('monthly_income')
            
            # Optional employment fields
            company_name = request.POST.get('company_name', '')
            designation = request.POST.get('designation', '')
            nature_of_business = request.POST.get('nature_of_business', '')
            
            loan_type = request.POST.get('loan_type')
            loan_amount_required = request.POST.get('loan_amount_required')
            loan_tenure = request.POST.get('loan_tenure')
            
            bank_name = request.POST.get('bank_name')
            account_number = request.POST.get('account_number')
            ifsc_code = request.POST.get('ifsc_code')
            
            aadhar_number = request.POST.get('aadhar_number')
            pan_number = request.POST.get('pan_number')
            cibil_score = request.POST.get('cibil_score', 0)
            
            ref1_name = request.POST.get('ref1_name')
            ref1_mobile = request.POST.get('ref1_mobile')
            ref2_name = request.POST.get('ref2_name')
            ref2_mobile = request.POST.get('ref2_mobile')
            
            # Create LoanApplication entry
            loan_application = LoanApplication.objects.create(
                name=applicant_name,
                email=applicant_email,
                mobile_no=applicant_mobile,
                fathers_name=fathers_name,
                dob=dob,
                gender=gender,
                permanent_address=permanent_address,
                permanent_city=permanent_city,
                permanent_pin=permanent_pin,
                occupation=occupation,
                year_of_experience=int(year_of_experience) if year_of_experience else 0,
                monthly_income=float(monthly_income) if monthly_income else 0,
                company_name=company_name,
                designation=designation,
                nature_of_business=nature_of_business,
                loan_type=loan_type,
                loan_amount_required=float(loan_amount_required) if loan_amount_required else 0,
                loan_tenure=int(loan_tenure) if loan_tenure else 0,
                bank_name=bank_name,
                account_number=account_number,
                ifsc_code=ifsc_code,
                aadhar_number=aadhar_number,
                pan_number=pan_number,
                cibil_score=int(cibil_score) if cibil_score else 0,
                reference1_name=ref1_name,
                reference1_mobile=ref1_mobile,
                reference2_name=ref2_name,
                reference2_mobile=ref2_mobile,
                status='new_entry',
                created_by=request.user,
            )
            
            # Handle document uploads
            documents_names = request.POST.getlist('document_name[]')
            documents_files = request.FILES.getlist('document_file[]')
            
            for name, file in zip(documents_names, documents_files):
                if file:
                    LoanDocument.objects.create(
                        loan_application=loan_application,
                        document_name=name,
                        document_file=file,
                        uploaded_by=request.user,
                    )
            
            # Create corresponding Loan entry
            Loan.objects.create(
                applicant_name=applicant_name,
                applicant_email=applicant_email,
                applicant_mobile=applicant_mobile,
                loan_type=loan_type,
                loan_amount=float(loan_amount_required) if loan_amount_required else 0,
                status='new_entry',
                created_by=request.user,
            )
            
            from django.contrib import messages
            messages.success(request, 'Loan application created successfully!')
            return redirect('subadmin_all_loans')
            
        except Exception as e:
            logger.error(f"Error creating loan: {str(e)}")
            from django.contrib import messages
            messages.error(request, f'Error creating loan: {str(e)}')
            return render(request, 'subadmin/subadmin_entries.html')
    
    context = {
        'page_title': 'Add New Loan Application',
    }
    return render(request, 'subadmin/subadmin_entries.html', context)

