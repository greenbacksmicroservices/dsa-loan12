# ============ ADMIN DASHBOARD & ALL LOANS VIEWS ============

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.db.models import Q, Sum, Count, F, Prefetch
from django.core.paginator import Paginator
from django.utils import timezone
import json
import logging

from .models import LoanApplication, Applicant, ApplicantDocument, LoanAssignment, LoanStatusHistory, User, Agent, Loan, LoanDocument, ActivityLog, SubAdminEntry, UserOnboardingProfile, UserOnboardingDocument
from .decorators import admin_required
from .loan_sync import extract_assignment_context, role_label, find_related_loan, find_related_loan_application
from .onboarding_utils import collect_onboarding_payload, collect_onboarding_documents, collect_onboarding_payload_from_source
from .followup_utils import auto_move_overdue_to_follow_up

logger = logging.getLogger(__name__)

FOLLOW_UP_PENDING_LABEL = 'Follow Up'
APP_STATUS_TO_LOAN_KEY = {
    'New Entry': 'new_entry',
    'Waiting for Processing': 'waiting',
    'Required Follow-up': 'follow_up',
    'Approved': 'approved',
    'Rejected': 'rejected',
    'Disbursed': 'disbursed',
}


def _has_revert_marker(value):
    return 'revert remark' in str(value or '').lower()


def _follow_up_pending_q():
    return Q(status__in=['new_entry', 'waiting']) & Q(remarks__icontains='Revert Remark')


def _is_follow_up_pending_loan(loan_obj, related_app=None):
    return _effective_status_key_for_loan(loan_obj, related_app=related_app) == 'follow_up_pending'


def _status_key_to_display_text(status_key, fallback_text=''):
    key = str(status_key or '').strip().lower()
    if key == 'follow_up_pending':
        return FOLLOW_UP_PENDING_LABEL
    mapping = {
        'new_entry': 'New Entry',
        'waiting': 'Waiting for Processing',
        'follow_up': 'Required Follow-up',
        'approved': 'Approved',
        'rejected': 'Rejected',
        'disbursed': 'Disbursed',
    }
    return _ui_status_label(mapping.get(key, fallback_text or key))


def _effective_status_key_for_loan(loan_obj, related_app=None):
    if not loan_obj:
        return ''

    legacy_key = (loan_obj.status or '').strip().lower()

    # Legacy follow-up pending marker (source of truth in many records)
    if legacy_key in ['new_entry', 'waiting'] and _has_revert_marker(loan_obj.remarks):
        return 'follow_up_pending'

    if related_app is None:
        related_app = find_related_loan_application(loan_obj)
    if not related_app:
        return legacy_key

    app_key = APP_STATUS_TO_LOAN_KEY.get(getattr(related_app, 'status', ''), '')
    app_follow_up_pending = app_key in ['new_entry', 'waiting'] and _has_revert_marker(getattr(related_app, 'approval_notes', ''))
    if app_follow_up_pending:
        return 'follow_up_pending'

    # If application has progressed, prefer it over stale legacy states.
    if app_key in ['follow_up', 'approved', 'rejected', 'disbursed']:
        return app_key

    return legacy_key


def _compute_status_breakdown(loans_qs):
    counts = {
        'new_entry': 0,
        'waiting': 0,
        'follow_up': 0,
        'follow_up_pending': 0,
        'approved': 0,
        'rejected': 0,
        'disbursed': 0,
        'total': 0,
    }

    for loan in loans_qs:
        status_key = _effective_status_key_for_loan(loan)
        if status_key in ['new_entry', 'waiting', 'follow_up', 'approved', 'rejected', 'disbursed', 'follow_up_pending']:
            counts[status_key] += 1
        counts['total'] += 1

    return counts


def _ui_status_label(status_text):
    normalized = str(status_text or '').strip().lower()
    if normalized in ['new entry', 'new_entry', 'draft']:
        return 'New Application'
    if normalized in ['waiting for processing', 'in processing', 'waiting', 'processing']:
        return 'Document Pending'
    if normalized in ['required follow-up', 'required follow up']:
        return 'Banking Processing'
    return status_text


def _split_name(full_name):
    clean_name = (full_name or "").strip()
    if not clean_name:
        return "User", ""
    parts = clean_name.split()
    first_name = parts[0]
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
    return first_name, last_name


def _build_unique_username(base_value):
    base = (base_value or "user").strip().lower()
    base = ''.join(ch for ch in base if ch.isalnum() or ch in ['_', '.'])[:80]
    if not base:
        base = "user"

    username = base
    counter = 1
    while User.objects.filter(username=username).exists():
        counter += 1
        username = f"{base}{counter}"
    return username


def _normalize_user_gender(raw_gender):
    value = (raw_gender or "").strip().lower()
    mapping = {
        "male": "Male",
        "female": "Female",
        "other": "Other",
    }
    return mapping.get(value, "Other")


def _merge_join_documents(app_documents, loan_documents):
    merged = []
    seen_urls = set()

    for doc in app_documents:
        if not getattr(doc, "file", None):
            continue
        file_url = doc.file.url
        if not file_url or file_url in seen_urls:
            continue
        seen_urls.add(file_url)
        merged.append({
            "name": doc.get_document_type_display() if hasattr(doc, "get_document_type_display") else str(doc.document_type),
            "url": file_url,
        })

    for doc in loan_documents:
        if not getattr(doc, "file", None):
            continue
        file_url = doc.file.url
        if not file_url or file_url in seen_urls:
            continue
        seen_urls.add(file_url)
        merged.append({
            "name": doc.get_document_type_display() if hasattr(doc, "get_document_type_display") else str(doc.document_type or "Document"),
            "url": file_url,
        })

    return merged


def _build_join_request_detail_payload(application):
    # Reuse shared parsing helpers used by employee/admin detail APIs.
    from .views import (
        _extract_existing_loans_from_parsed,
        _extract_manual_remark,
        _extract_references_from_parsed,
        _get_parsed_value,
        _parse_colon_details,
    )

    applicant = application.applicant
    related_loan = find_related_loan(application)
    parsed_details = _parse_colon_details(related_loan.remarks if related_loan else "")

    documents = _merge_join_documents(
        application.documents.all(),
        related_loan.documents.all() if related_loan else [],
    )

    permanent_address = (
        getattr(applicant, "permanent_address", None)
        or (related_loan.permanent_address if related_loan else "")
        or _get_parsed_value(parsed_details, "permanent address")
    )
    present_address = (
        getattr(applicant, "current_address", None)
        or (related_loan.current_address if related_loan else "")
        or _get_parsed_value(parsed_details, "present address")
    )
    same_as_permanent = (
        "Yes"
        if permanent_address and present_address and str(permanent_address).strip() == str(present_address).strip()
        else "No"
    )

    return {
        "id": application.id,
        "application_id": application.id,
        "request_date": application.created_at.strftime("%Y-%m-%d %H:%M") if application.created_at else "-",
        "updated_at": application.updated_at.strftime("%Y-%m-%d %H:%M") if application.updated_at else "-",
        "status": application.status,
        "assigned_employee": application.assigned_employee.get_full_name() if application.assigned_employee else "-",
        "assigned_agent": application.assigned_agent.name if application.assigned_agent else "-",
        "assigned_by": application.assigned_by.get_full_name() if application.assigned_by else "-",
        "assigned_at": application.assigned_at.strftime("%Y-%m-%d %H:%M") if application.assigned_at else "-",
        "role": applicant.role or "-",
        "applicant_name": applicant.full_name or "-",
        "username": applicant.username or "-",
        "mobile": applicant.mobile or "-",
        "alternate_mobile": _get_parsed_value(parsed_details, "alternate mobile"),
        "email": applicant.email or "-",
        "father_name": _get_parsed_value(parsed_details, "father name", "father's name"),
        "mother_name": _get_parsed_value(parsed_details, "mother name", "mother's name"),
        "date_of_birth": _get_parsed_value(parsed_details, "date of birth", "dob"),
        "gender": applicant.gender or _get_parsed_value(parsed_details, "gender"),
        "marital_status": _get_parsed_value(parsed_details, "marital status"),
        "permanent_address": permanent_address or "-",
        "permanent_landmark": _get_parsed_value(parsed_details, "permanent landmark"),
        "permanent_city": _get_parsed_value(parsed_details, "permanent city") or applicant.city or "-",
        "permanent_pin": _get_parsed_value(parsed_details, "permanent pin") or applicant.pin_code or "-",
        "present_same_as_permanent": same_as_permanent,
        "present_address": present_address or "-",
        "present_landmark": _get_parsed_value(parsed_details, "present landmark"),
        "present_city": _get_parsed_value(parsed_details, "present city") or applicant.city or "-",
        "present_pin": _get_parsed_value(parsed_details, "present pin") or applicant.pin_code or "-",
        "occupation": _get_parsed_value(parsed_details, "occupation"),
        "employment_date": _get_parsed_value(parsed_details, "date of joining"),
        "experience_years": _get_parsed_value(parsed_details, "experience (years)", "year of experience"),
        "additional_income": _get_parsed_value(parsed_details, "additional income", "extra income"),
        "extra_income_details": _get_parsed_value(parsed_details, "extra income details"),
        "existing_loans": _extract_existing_loans_from_parsed(parsed_details),
        "loan_type": applicant.get_loan_type_display() if hasattr(applicant, "get_loan_type_display") else (applicant.loan_type or "-"),
        "loan_amount": float(applicant.loan_amount) if applicant.loan_amount else 0,
        "tenure_months": applicant.tenure_months or "-",
        "charges_applicable": _get_parsed_value(
            parsed_details,
            "charges fee",
            "charges or fee",
            "any charges or fee",
            default="No charges",
        ),
        "loan_purpose": applicant.loan_purpose or _get_parsed_value(parsed_details, "loan purpose"),
        "references": _extract_references_from_parsed(parsed_details),
        "cibil_score": _get_parsed_value(parsed_details, "cibil score"),
        "aadhar_number": _get_parsed_value(parsed_details, "aadhar number", "aadhaar number"),
        "pan_number": _get_parsed_value(parsed_details, "pan number"),
        "bank_name": applicant.bank_name or (related_loan.bank_name if related_loan else "") or _get_parsed_value(parsed_details, "bank name"),
        "account_number": applicant.account_number or _get_parsed_value(parsed_details, "account number"),
        "ifsc_code": applicant.ifsc_code or _get_parsed_value(parsed_details, "ifsc code", "ifsc"),
        "bank_type": applicant.bank_type or (related_loan.bank_type if related_loan else "") or _get_parsed_value(parsed_details, "bank type"),
        "remarks": _extract_manual_remark(related_loan.remarks, parsed_details) if related_loan else _get_parsed_value(parsed_details, "remarks suggestions", "remark"),
        "declaration": "I hereby declare that the above information given by me is true and correct.",
        "documents": documents,
        "documents_count": len(documents),
    }


@login_required(login_url='admin_login')
@admin_required
def admin_dashboard(request):
    """
    ADMIN DASHBOARD - Shows real statistics and summary
    """
    try:
        auto_move_overdue_to_follow_up()

        # Get all Loan counts by status (real-time)
        all_loans = Loan.objects.all()
        status_counts = _compute_status_breakdown(all_loans)
        follow_up_pending_count = status_counts['follow_up_pending']
        new_entry_count = status_counts['new_entry']
        in_processing_count = status_counts['waiting']
        followup_count = status_counts['follow_up']
        approved_count = status_counts['approved']
        rejected_count = status_counts['rejected']
        disbursed_count = status_counts['disbursed']
        
        # Team counts
        total_agents = Agent.objects.count()
        active_agents = Agent.objects.filter(status='active').count()
        total_employees = User.objects.filter(role='employee').count()
        active_employees = User.objects.filter(role='employee', is_active=True).count()
        total_subadmins = User.objects.filter(role='subadmin').count()
        
        # Calculate statistics
        total_applications = status_counts['total']
        
        approval_rate = 0
        if total_applications > 0:
            approval_rate = int((approved_count / total_applications) * 100)
        
        rejection_rate = 0
        if total_applications > 0:
            rejection_rate = int((rejected_count / total_applications) * 100)
        
        disbursement_rate = 0
        if total_applications > 0:
            disbursement_rate = int((disbursed_count / total_applications) * 100)
        
        context = {
            'page_title': 'Admin Dashboard',
            'new_entry_count': new_entry_count,
            'in_processing_count': in_processing_count,
            'followup_count': followup_count,
            'follow_up_pending_count': follow_up_pending_count,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'disbursed_count': disbursed_count,
            'total_applications': total_applications,
            'total_agents': total_agents,
            'active_agents': active_agents,
            'total_employees': total_employees,
            'active_employees': active_employees,
            'total_subadmins': total_subadmins,
            'approval_rate': approval_rate,
            'rejection_rate': rejection_rate,
            'disbursement_rate': disbursement_rate,
        }
        return render(request, 'core/admin/admin_dashboard.html', context)
    except Exception as e:
        logger.error(f"Error loading admin dashboard: {str(e)}")
        context = {'page_title': 'Admin Dashboard', 'error': str(e)}
        return render(request, 'core/admin/admin_dashboard.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_all_loans(request):
    """
    ADMIN ALL LOANS - Shows comprehensive table with all loan details
    Displays loans in table format with 10 required columns
    """
    from django.db.models import Q
    
    # Get search and status filter parameters
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    auto_move_overdue_to_follow_up()
    
    # Start with all loans ordered by creation date (newest first)
    loans = Loan.objects.select_related(
        'created_by', 'assigned_employee', 'assigned_agent'
    ).all().order_by('-created_at')
    
    # Apply search filter if provided
    if search_query:
        loans = loans.filter(
            Q(full_name__icontains=search_query) |
            Q(mobile_number__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(user_id__icontains=search_query)
        )

    # Apply coarse DB filter (final status filtering happens after effective-status resolution)
    if status_filter == 'follow_up_pending':
        loans = loans.filter(status__in=['new_entry', 'waiting', 'follow_up'])
    elif status_filter in ['new_entry', 'waiting', 'follow_up']:
        loans = loans.filter(status__in=['new_entry', 'waiting', 'follow_up'])
    elif status_filter in ['approved', 'rejected', 'disbursed']:
        loans = loans.filter(status__in=[status_filter, 'follow_up'])

    enriched_loans = []
    for loan in loans:
        related_app = find_related_loan_application(loan)
        effective_status_key = _effective_status_key_for_loan(loan, related_app=related_app)
        follow_up_pending = effective_status_key == 'follow_up_pending'

        if status_filter == 'follow_up_pending' and effective_status_key != 'follow_up_pending':
            continue
        if status_filter and status_filter != 'follow_up_pending' and effective_status_key != status_filter:
            continue

        creator = loan.created_by
        creator_name = (creator.get_full_name() or creator.username) if creator else '-'
        loan.created_under_display = f"{role_label(creator)} - {creator_name}" if creator else 'System'
        if loan.assigned_employee:
            loan.assigned_to_display = f"Employee - {loan.assigned_employee.get_full_name() or loan.assigned_employee.username}"
        elif loan.assigned_agent:
            loan.assigned_to_display = f"Agent - {loan.assigned_agent.name}"
        else:
            loan.assigned_to_display = '-'
        loan.follow_up_pending = follow_up_pending
        loan.status_key_display = effective_status_key or loan.status
        loan.status_display_text = _status_key_to_display_text(effective_status_key, fallback_text=loan.get_status_display())
        loan.assigned_by_display = extract_assignment_context(loan).get('assigned_by_display', '-')
        enriched_loans.append(loan)
    
    context = {
        'page_title': 'All Loans - Master Database',
        'loans': enriched_loans,
        'search_query': search_query,
        'status_filter': status_filter,
        'status_filter_display': FOLLOW_UP_PENDING_LABEL if status_filter == 'follow_up_pending' else (status_filter.replace('_', ' ').title() if status_filter else ''),
        'total_loans': len(enriched_loans),
    }
    return render(request, 'core/admin/all_loans.html', context)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_dashboard_stats(request):
    """
    DASHBOARD STATS API - Returns stats ONLY (no loans data)
    Called by admin_dashboard template
    """
    try:
        all_loans = Loan.objects.all()
        status_counts = _compute_status_breakdown(all_loans)
        stats = {
            'total': status_counts['total'],
            'new_entry': status_counts['new_entry'],
            'processing': status_counts['waiting'],
            'follow_up': status_counts['follow_up'],
            'follow_up_pending': status_counts['follow_up_pending'],
            'approved': status_counts['approved'],
            'rejected': status_counts['rejected'],
            'disbursed': status_counts['disbursed'],
            'total_value': all_loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
            'approved_value': all_loans.filter(status='approved').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
            'disbursed_value': all_loans.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
            'pending_value': all_loans.exclude(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
        }
        return JsonResponse(stats)
    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_all_loans(request):
    """
    LOANS LISTING API - Returns loans ONLY (no stats data)
    Called by all_loans template
    """
    try:
        status_filter = request.GET.get('status', 'all')
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 25))
        search = request.GET.get('search', '').strip()
        
        query = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
        ).prefetch_related(
            'documents',
            'status_history'
        )
        
        status_map = {
            'approved': 'Approved',
            'rejected': 'Rejected',
            'disbursed': 'Disbursed',
            'new_entry': 'New Entry',
            'waiting': 'Waiting for Processing',
            'follow_up': 'Required Follow-up',
        }
        
        if status_filter != 'all' and status_filter in status_map:
            query = query.filter(status=status_map[status_filter])
        
        if search:
            query = query.filter(
                Q(applicant__full_name__icontains=search) |
                Q(applicant__email__icontains=search) |
                Q(applicant__mobile__icontains=search) |
                Q(id__icontains=search)
            )
        
        total_count = query.count()
        query = query.order_by('-created_at')
        
        paginator = Paginator(query, per_page)
        page_obj = paginator.get_page(page)
        
        loans_data = []
        for loan in page_obj:
            agent_name = ''
            if loan.assigned_agent:
                agent_name = loan.assigned_agent.name
            
            employee_name = ''
            if loan.assigned_employee:
                employee_name = loan.assigned_employee.get_full_name()
            
            loans_data.append({
                'id': loan.id,
                'loan_id': loan.user_id or f'LOAN-{loan.id:06d}',
                'applicant_name': loan.applicant.full_name if loan.applicant else 'N/A',
                'applicant_email': loan.applicant.email if loan.applicant else 'N/A',
                'loan_type': loan.applicant.loan_type if loan.applicant else 'N/A',
                'loan_amount': str(loan.applicant.loan_amount) if loan.applicant and loan.applicant.loan_amount else '0',
                'agent_name': agent_name,
                'employee_name': employee_name,
                'status': loan.status,
                'status_display': _ui_status_label(loan.get_status_display()),
                'submitted_date': loan.created_at.strftime('%Y-%m-%d'),
                'last_updated_date': loan.updated_at.strftime('%Y-%m-%d'),
            })
        
        return JsonResponse({
            'success': True,
            'loans': loans_data,
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_count': total_count,
                'per_page': per_page
            }
        })
    
    except Exception as e:
        logger.error(f"Error fetching loans: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
def admin_loan_detail(request, loan_id):
    """
    Detailed view page for a single loan
    """
    try:
        loan = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
        ).prefetch_related(
            'documents',
            'status_history'
        ).get(id=loan_id)
        
        context = {
            'page_title': f'Loan Details - {loan.applicant.full_name if loan.applicant else "Loan"}',
            'loan': loan,
            'applicant': loan.applicant,
            'documents': loan.documents.all(),
            'status_history': loan.status_history.all(),
        }
        
        return render(request, 'core/admin/all_loans_detail.html', context)
    
    except LoanApplication.DoesNotExist:
        return redirect('admin_all_loans')


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_loan_detail(request, loan_id):
    """
    API endpoint to fetch full loan details in JSON format
    """
    try:
        loan = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
        ).prefetch_related(
            'documents',
            'status_history'
        ).get(id=loan_id)
        
        applicant_data = {
            'full_name': loan.applicant.full_name if loan.applicant else 'N/A',
            'email': loan.applicant.email if loan.applicant else 'N/A',
            'mobile': loan.applicant.mobile if loan.applicant else 'N/A',
            'city': loan.applicant.city if loan.applicant else 'N/A',
            'state': loan.applicant.state if loan.applicant else 'N/A',
            'pin_code': loan.applicant.pin_code if loan.applicant else 'N/A',
        }
        
        loan_data = {
            'loan_type': loan.applicant.loan_type if loan.applicant else 'N/A',
            'loan_amount': str(loan.applicant.loan_amount) if loan.applicant and loan.applicant.loan_amount else '0.00',
            'tenure_months': loan.applicant.tenure_months if loan.applicant else 'N/A',
            'interest_rate': str(loan.applicant.interest_rate) if loan.applicant and loan.applicant.interest_rate else 'N/A',
            'loan_purpose': loan.applicant.loan_purpose if loan.applicant else 'N/A',
            'bank_name': loan.applicant.bank_name if loan.applicant else 'N/A',
        }
        
        documents_data = []
        for doc in loan.documents.all():
            documents_data.append({
                'id': doc.id,
                'type': doc.get_document_type_display() if hasattr(doc, 'get_document_type_display') else str(doc.document_type),
                'file_url': doc.file.url if doc.file else '#',
                'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else 'N/A',
            })
        
        return JsonResponse({
            'success': True,
            'loan_id': loan.id,
            'status': loan.status,
            'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'applicant': applicant_data,
            'loan_details': loan_data,
            'documents': documents_data,
            'agent_name': loan.assigned_agent.name if loan.assigned_agent else 'N/A',
            'employee_name': loan.assigned_employee.get_full_name() if loan.assigned_employee else 'N/A',
        })
    
    except LoanApplication.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Loan not found'
        }, status=404)


@login_required(login_url='admin_login')
@admin_required
def admin_edit_loan(request, loan_id):
    """
    Edit loan page
    """
    loan = get_object_or_404(LoanApplication, id=loan_id)
    context = {
        'page_title': f'Edit Loan - {loan.applicant.full_name if loan.applicant else "Loan"}',
        'loan': loan,
    }
    return render(request, 'core/admin/all_loans_edit.html', context)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_delete_loan(request, loan_id):
    """
    Soft delete a loan
    """
    try:
        loan = get_object_or_404(LoanApplication, id=loan_id)
        loan.is_deleted = True
        loan.deleted_at = timezone.now()
        loan.save()
        
        logger.info(f"Loan {loan_id} soft deleted by {request.user.username}")
        return JsonResponse({
            'success': True,
            'message': 'Loan deleted successfully'
        })
    
    except Exception as e:
        logger.error(f"Error deleting loan: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_reassign_loan(request, loan_id):
    """
    Reassign loan to different employee
    """
    try:
        data = json.loads(request.body)
        new_employee_id = data.get('employee_id')
        
        loan = get_object_or_404(LoanApplication, id=loan_id)
        new_employee = get_object_or_404(User, id=new_employee_id, role='employee')
        
        loan.assigned_employee = new_employee
        loan.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Loan reassigned to {new_employee.get_full_name()}'
        })
    
    except Exception as e:
        logger.error(f"Error reassigning loan: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_loan_stats(request):
    """
    Get statistics for all loans
    """
    try:
        total_loans = LoanApplication.objects.filter(is_deleted=False).count()
        approved = LoanApplication.objects.filter(status='Approved', is_deleted=False).count()
        rejected = LoanApplication.objects.filter(status='Rejected', is_deleted=False).count()
        disbursed = LoanApplication.objects.filter(status='Disbursed', is_deleted=False).count()
        
        return JsonResponse({
            'success': True,
            'stats': {
                'total_loans': total_loans,
                'approved': approved,
                'rejected': rejected,
                'disbursed': disbursed,
                'pending': total_loans - approved - rejected - disbursed,
            }
        })
    
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_all_loans(request):
    """
    API endpoint returning all loans for admin all-loans page
    """
    try:
        status_filter = request.GET.get('status', '').strip()
        search = request.GET.get('search', '').strip()
        
        query = Loan.objects.all().select_related(
            'assigned_employee',
            'assigned_agent',
        )
        
        # Coarse filter by status (final status decision is computed using related workflow record)
        if status_filter == 'follow_up_pending':
            query = query.filter(status__in=['new_entry', 'waiting', 'follow_up'])
        elif status_filter in ['new_entry', 'waiting', 'follow_up']:
            query = query.filter(status__in=['new_entry', 'waiting', 'follow_up'])
        elif status_filter in ['approved', 'rejected', 'disbursed']:
            query = query.filter(status__in=[status_filter, 'follow_up'])
        
        # Filter by search term
        if search:
            query = query.filter(
                Q(full_name__icontains=search) |
                Q(mobile_number__icontains=search) |
                Q(email__icontains=search) |
                Q(id__icontains=search)
            )
        
        # Get loans data
        loans_data = []
        for loan in query.order_by('-created_at')[:100]:
            related_app = find_related_loan_application(loan)
            effective_status_key = _effective_status_key_for_loan(loan, related_app=related_app)
            is_follow_up_pending = effective_status_key == 'follow_up_pending'

            if status_filter == 'follow_up_pending' and effective_status_key != 'follow_up_pending':
                continue
            if status_filter and status_filter != 'follow_up_pending' and effective_status_key != status_filter:
                continue
            status_key = effective_status_key or loan.status
            status_display = _status_key_to_display_text(effective_status_key, fallback_text=loan.get_status_display())
            loans_data.append({
                'id': loan.id,
                'applicant_name': loan.full_name or 'N/A',
                'phone': loan.mobile_number or 'N/A',
                'email': loan.email or 'N/A',
                'loan_amount': float(loan.loan_amount) if loan.loan_amount else 0,
                'status': status_key,
                'status_display': status_display,
                'status_raw': loan.status,
                'follow_up_pending': is_follow_up_pending,
                'agent': loan.assigned_agent.user.get_full_name() if loan.assigned_agent else '-',
                'employee': loan.assigned_employee.get_full_name() if loan.assigned_employee else '-',
                'date_applied': loan.created_at.strftime('%Y-%m-%d') if loan.created_at else '-',
            })
        
        return JsonResponse({
            'success': True,
            'loans': loans_data
        })
    
    except Exception as e:
        logger.error(f"Error in api_admin_all_loans: {str(e)}")
        return JsonResponse({
            'success': False,
            'loans': [],
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
def admin_subadmin_management(request):
    """Admin page to manage SubAdmins"""
    try:
        from .subadmin_views import _subadmin_managed_agents_qs, _subadmin_managed_employees_qs

        subadmins = User.objects.filter(role='subadmin').order_by('-date_joined')
        subadmin_list = []
        for subadmin in subadmins:
            managed_agents_count = _subadmin_managed_agents_qs(subadmin).count()
            managed_employees_count = _subadmin_managed_employees_qs(subadmin).count()
            entries_count = SubAdminEntry.objects.filter(subadmin=subadmin).count()
            subadmin.total_agents = managed_agents_count
            subadmin.total_employees = managed_employees_count
            subadmin.total_entries = entries_count
            subadmin_list.append({
                'id': subadmin.id,
                'name': subadmin.get_full_name(),
                'email': subadmin.email,
                'username': subadmin.username,
                'phone': subadmin.phone or '-',
                'address': subadmin.address or '-',
                'joined_on': subadmin.date_joined.strftime('%Y-%m-%d') if subadmin.date_joined else '-',
                'total_agents': managed_agents_count,
                'total_employees': managed_employees_count,
                'total_entries': entries_count,
                'is_active': subadmin.is_active,
                'date_joined': subadmin.date_joined
            })
        
        context = {
            'page_title': 'Partner Management',
            'subadmins': subadmins,
            'subadmin_count': subadmins.count(),
            'subadmin_rows': subadmin_list,
        }
        return render(request, 'core/admin/subadmin_management_new.html', context)
    except Exception as e:
        logger.error(f"Error loading subadmin management: {str(e)}")
        return render(request, 'core/admin/subadmin_management_new.html', {'error': str(e)})


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_subadmin_full_details(request, subadmin_id):
    """Return full performance + customer detail for a SubAdmin."""
    try:
        subadmin = get_object_or_404(User, id=subadmin_id, role='subadmin')
        from .subadmin_views import (
            _extract_assignment_marker,
            _latest_bank_remark,
            _role_label,
            _subadmin_managed_agents_qs,
            _subadmin_managed_employees_qs,
            _subadmin_scoped_loans_qs,
        )

        managed_agents_qs = _subadmin_managed_agents_qs(subadmin)
        managed_employees_qs = _subadmin_managed_employees_qs(subadmin)
        loans_qs = _subadmin_scoped_loans_qs(subadmin).select_related(
            'assigned_employee', 'assigned_agent', 'created_by'
        ).order_by('-created_at')
        entries_qs = SubAdminEntry.objects.filter(subadmin=subadmin)

        customers = []
        for loan in loans_qs[:250]:
            assigned_to = '-'
            if loan.assigned_employee:
                assigned_to = f"Employee - {loan.assigned_employee.get_full_name() or loan.assigned_employee.username}"
            elif loan.assigned_agent:
                assigned_to = f"Agent - {loan.assigned_agent.name}"

            if loan.created_by:
                owner_name = f"{_role_label(loan.created_by)} - {loan.created_by.get_full_name() or loan.created_by.username}"
            else:
                owner_name = f"Partner - {subadmin.get_full_name() or subadmin.username}"

            customers.append({
                'loan_id': loan.id,
                'loan_uid': loan.user_id or f'LOAN-{loan.id:06d}',
                'customer_name': loan.full_name or '-',
                'mobile': loan.mobile_number or '-',
                'email': loan.email or '-',
                'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else loan.loan_type,
                'loan_amount': float(loan.loan_amount or 0),
                'status': loan.status,
                'status_display': _ui_status_label(loan.get_status_display()),
                'assigned_to': assigned_to,
                'assigned_by': _extract_assignment_marker(loan),
                'owner_name': owner_name,
                'bank_remark': _latest_bank_remark(loan),
                'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else '',
            })

        summary = {
            'total_applications': loans_qs.count(),
            'subadmin_entries': entries_qs.count(),
            'managed_agents': managed_agents_qs.count(),
            'managed_employees': managed_employees_qs.count(),
            'new_entry': loans_qs.filter(status='new_entry').count(),
            'waiting': loans_qs.filter(status='waiting').count(),
            'banking_processing': loans_qs.filter(status='follow_up').count(),
            'approved': loans_qs.filter(status='approved').count(),
            'rejected': loans_qs.filter(status='rejected').count(),
            'disbursed': loans_qs.filter(status='disbursed').count(),
            'total_customers': loans_qs.count(),
        }

        onboarding = {}
        documents = []
        if hasattr(subadmin, 'onboarding_profile') and subadmin.onboarding_profile:
            onboarding = subadmin.onboarding_profile.data or {}
        if hasattr(subadmin, 'onboarding_documents'):
            documents = [
                {
                    'type': doc.document_type or 'other',
                    'url': doc.file.url if doc.file else '',
                    'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else '',
                }
                for doc in subadmin.onboarding_documents.all()
            ]

        return JsonResponse({
            'success': True,
            'subadmin': {
                'id': subadmin.id,
                'name': subadmin.get_full_name() or subadmin.username,
                'username': subadmin.username,
                'email': subadmin.email or '-',
                'phone': subadmin.phone or '-',
                'address': subadmin.address or '-',
                'joined_on': subadmin.date_joined.strftime('%Y-%m-%d') if subadmin.date_joined else '-',
                'status': 'Active' if subadmin.is_active else 'Inactive',
            },
            'summary': summary,
            'customers': customers,
            'onboarding': onboarding,
            'documents': documents,
        })
    except Exception as e:
        logger.error(f"Error in api_admin_subadmin_full_details: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_http_methods(['POST'])
def api_create_subadmin(request):
    """API to create new SubAdmin"""
    try:
        import json
        from django.core.files.base import ContentFile
        import base64

        is_json = bool(request.content_type and 'application/json' in request.content_type)
        if is_json:
            raw_body = (request.body or b'').decode('utf-8').strip()
            if not raw_body:
                return JsonResponse({
                    'success': False,
                    'error': 'Request body is empty'
                }, status=400)
            try:
                data = json.loads(raw_body)
            except json.JSONDecodeError:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid JSON payload'
                }, status=400)
        else:
            data = request.POST
        
        # Required fields
        username = (data.get('username') or '').strip()
        email = (data.get('email') or '').strip()
        password = (data.get('password') or '').strip()
        name = (data.get('name') or '').strip()
        first_name = (data.get('first_name') or '').strip()
        last_name = (data.get('last_name') or '').strip()
        phone = (data.get('phone') or '').strip()
        address = (data.get('address') or '').strip()
        pin = (data.get('pin') or '').strip()
        state = (data.get('state') or '').strip()
        photo_base64 = data.get('photo', '') if isinstance(data, dict) else ''
        photo_file = request.FILES.get('photo') if not is_json else None

        if not name:
            name = f"{first_name} {last_name}".strip()
        if not username and email:
            username = email.split('@')[0]
        
        # Validation
        if not all([username, email, password, name, phone]):
            return JsonResponse({
                'success': False,
                'error': 'Name, Email, Username, Phone, and Password are required'
            }, status=400)
        
        # Check if username exists
        if User.objects.filter(username=username).exists():
            return JsonResponse({
                'success': False,
                'error': 'Username already exists'
            }, status=400)
        
        # Check if email exists
        if User.objects.filter(email=email).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already exists'
            }, status=400)

        if User.objects.filter(phone=phone).exists():
            return JsonResponse({
                'success': False,
                'error': 'Phone already exists'
            }, status=400)
        
        # Create SubAdmin user
        subadmin = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=name.split()[0] if name else '',
            last_name=' '.join(name.split()[1:]) if len(name.split()) > 1 else '',
            role='subadmin',
            phone=phone,
            address=address,
        )
        
        # Add state if field exists
        if hasattr(subadmin, 'state'):
            subadmin.state = state
        
        # Add pin if field exists
        if hasattr(subadmin, 'pin'):
            subadmin.pin = pin
        
        # Handle photo upload
        if photo_file:
            subadmin.profile_photo = photo_file
        elif photo_base64:
            try:
                format, imgstr = photo_base64.split(';base64,')
                ext = format.split('/')[-1]
                photo_data = ContentFile(base64.b64decode(imgstr), name=f'subadmin_{username}.{ext}')
                if hasattr(subadmin, 'photo'):
                    subadmin.photo = photo_data
                elif hasattr(subadmin, 'profile_photo'):
                    subadmin.profile_photo = photo_data
            except:
                pass
        
        subadmin.save()

        onboarding_payload = collect_onboarding_payload_from_source(data) if is_json else collect_onboarding_payload(request)
        if onboarding_payload:
            profile, _ = UserOnboardingProfile.objects.get_or_create(
                user=subadmin,
                defaults={'role': subadmin.role, 'data': onboarding_payload},
            )
            if profile.data != onboarding_payload or profile.role != subadmin.role:
                profile.data = onboarding_payload
                profile.role = subadmin.role
                profile.save()

        if not is_json:
            for doc_type, doc_file in collect_onboarding_documents(request):
                if not doc_file:
                    continue
                if doc_file.size > 10 * 1024 * 1024:
                    continue
                UserOnboardingDocument.objects.create(
                    user=subadmin,
                    document_type=doc_type or 'other',
                    file=doc_file,
                )
        
        return JsonResponse({
            'success': True,
            'message': 'Partner created successfully',
            'subadmin': {
                'id': subadmin.id,
                'username': subadmin.username,
                'email': subadmin.email,
                'name': subadmin.get_full_name() or subadmin.username,
                'phone': getattr(subadmin, 'phone', ''),
                'address': getattr(subadmin, 'address', ''),
            }
        })
    
    except Exception as e:
        logger.error(f"Error creating SubAdmin: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_subadmins(request):
    """Get all SubAdmins"""
    try:
        subadmins = User.objects.filter(role='subadmin').values(
            'id', 'username', 'email', 'first_name', 'last_name', 
            'phone', 'address', 'created_at'
        )
        
        subadmin_list = []
        for sub in subadmins:
            subadmin_list.append({
                'id': sub['id'],
                'username': sub['username'],
                'email': sub['email'],
                'name': f"{sub['first_name']} {sub['last_name']}".strip() or sub['username'],
                'phone': sub['phone'] or '-',
                'address': sub['address'] or '-',
                'created': sub['created_at'].strftime('%Y-%m-%d') if sub['created_at'] else '-',
            })
        
        return JsonResponse({
            'success': True,
            'count': len(subadmin_list),
            'subadmins': subadmin_list
        })
    
    except Exception as e:
        logger.error(f"Error fetching SubAdmins: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_http_methods(['POST'])
def api_update_subadmin(request, subadmin_id):
    """Update a subadmin account."""
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)

    subadmin = get_object_or_404(User, id=subadmin_id, role='subadmin')

    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip()
    phone = (data.get('phone') or '').strip()

    if not username or not email or not phone:
        return JsonResponse({
            'success': False,
            'error': 'Username, Email, and Phone are required.'
        }, status=400)

    if User.objects.filter(username=username).exclude(id=subadmin.id).exists():
        return JsonResponse({'success': False, 'error': 'Username already exists'}, status=400)
    if User.objects.filter(email=email).exclude(id=subadmin.id).exists():
        return JsonResponse({'success': False, 'error': 'Email already exists'}, status=400)
    if User.objects.filter(phone=phone).exclude(id=subadmin.id).exists():
        return JsonResponse({'success': False, 'error': 'Phone already exists'}, status=400)

    subadmin.username = username
    subadmin.email = email
    subadmin.phone = phone
    subadmin.first_name = (data.get('first_name') or '').strip()
    subadmin.last_name = (data.get('last_name') or '').strip()
    subadmin.address = (data.get('address') or '').strip() or None

    status_value = (data.get('status') or '').strip().lower()
    if status_value in ['active', 'inactive']:
        subadmin.is_active = status_value == 'active'

    if data.get('password'):
        subadmin.set_password(str(data.get('password')))

    subadmin.save()

    return JsonResponse({
        'success': True,
        'message': 'Partner updated successfully',
        'subadmin': {
            'id': subadmin.id,
            'name': subadmin.get_full_name() or subadmin.username,
            'username': subadmin.username,
            'email': subadmin.email,
            'phone': subadmin.phone or '',
            'address': subadmin.address or '',
            'status': 'Active' if subadmin.is_active else 'Inactive',
        }
    })


@login_required(login_url='admin_login')
@admin_required
@require_http_methods(['DELETE', 'POST'])
def api_delete_subadmin(request, subadmin_id):
    """Delete a subadmin account and return JSON response."""
    try:
        subadmin = get_object_or_404(User, id=subadmin_id, role='subadmin')
        if subadmin.id == request.user.id:
            return JsonResponse({
                'success': False,
                'error': 'You cannot delete your own account.'
            }, status=400)

        subadmin_name = subadmin.get_full_name() or subadmin.username
        subadmin.delete()
        return JsonResponse({
            'success': True,
            'message': f'{subadmin_name} deleted successfully.'
        })
    except Exception as e:
        logger.error(f"Error deleting SubAdmin: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required(login_url='admin_login')
@admin_required
def add_agent(request):
    """
    Admin page to add new agent/employee/subadmin
    GET: Show form
    POST: Create new agent/employee
    """
    if request.method == 'POST':
        try:
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()
            phone = request.POST.get('phone', '').strip()
            gender = request.POST.get('gender', '').strip()
            address = request.POST.get('address', '').strip()
            password = request.POST.get('password', '').strip()
            role = request.POST.get('role', 'agent').strip()  # agent, employee, subadmin
            photo = request.FILES.get('photo')
            
            # Validate required fields
            if not all([first_name, email, phone, password]):
                messages.error(request, 'Please fill all required fields')
                return render(request, 'core/admin/add_agent.html')
            
            # Validate email format
            if not email or '@' not in email:
                messages.error(request, 'Invalid email address')
                return render(request, 'core/admin/add_agent.html')
            
            # Check if email already exists
            if User.objects.filter(email=email).exists():
                messages.error(request, 'Email already exists')
                return render(request, 'core/admin/add_agent.html')
            
            # Check phone format
            if not phone.isdigit() or len(phone) < 10:
                messages.error(request, 'Invalid phone number. Must be at least 10 digits')
                return render(request, 'core/admin/add_agent.html')

            # Validate password length
            if len(password) < 6:
                messages.error(request, 'Password must be at least 6 characters')
                return render(request, 'core/admin/add_agent.html')
            
            # Generate username from email
            base_username = email.split('@')[0]
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
            
            # Create User account
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role=role,
                phone=phone,
                gender=gender or None,
                address=address
            )
            
            # Handle photo upload
            if photo:
                user.profile_photo = photo
                user.save()
            
            # If role is agent, create Agent profile
            if role == 'agent':
                agent = Agent.objects.create(
                    user=user,
                    name=f"{first_name} {last_name}".strip(),
                    email=email,
                    phone=phone,
                    status='active',
                    gender=gender or None,
                    address=address,
                    city=request.POST.get('onb_perm_city', '').strip(),
                    state=request.POST.get('onb_perm_state', '').strip(),
                    pin_code=request.POST.get('onb_perm_pin', '').strip(),
                )
                if photo:
                    agent.profile_photo = photo
                    agent.save()
                success_msg = f'Agent {first_name} {last_name} created successfully with username: {username}'
            
            # If role is subadmin, mark as subadmin
            elif role == 'subadmin':
                user.is_subadmin = True
                user.save()
                success_msg = f'Partner {first_name} {last_name} created successfully with username: {username}'
            
            else:  # employee
                success_msg = f'Employee {first_name} {last_name} created successfully with username: {username}'

            onboarding_payload = collect_onboarding_payload(request)
            if onboarding_payload:
                profile, _ = UserOnboardingProfile.objects.get_or_create(
                    user=user,
                    defaults={'role': user.role, 'data': onboarding_payload},
                )
                if profile.data != onboarding_payload or profile.role != user.role:
                    profile.data = onboarding_payload
                    profile.role = user.role
                    profile.save()

            for doc_type, doc_file in collect_onboarding_documents(request):
                if not doc_file:
                    continue
                if doc_file.size > 10 * 1024 * 1024:
                    continue
                UserOnboardingDocument.objects.create(
                    user=user,
                    document_type=doc_type or 'other',
                    file=doc_file,
                )
            
            messages.success(request, success_msg)
            return redirect('admin_all_agents' if role == 'agent' else 'admin_all_employees')
        
        except Exception as e:
            logger.error(f"Error creating agent: {str(e)}")
            messages.error(request, f'Error creating user: {str(e)}')
            return render(request, 'core/admin/add_agent.html')
    
    context = {
        'page_title': 'Add New Agent/Employee',
    }
    return render(request, 'core/admin/add_agent.html', context)


@login_required(login_url='admin_login')
@admin_required
def team_management(request):
    """
    Team Management Overview - Shows employees, agents, and subadmins
    """
    try:
        employees = User.objects.filter(role='employee', is_active=True).order_by('-date_joined')
        agents = Agent.objects.filter(status='active').order_by('-created_at')
        subadmins = User.objects.filter(is_subadmin=True, is_active=True).order_by('-date_joined')
        
        context = {
            'page_title': 'Team Management',
            'employees': employees,
            'agents': agents,
            'subadmins': subadmins,
        }
        return render(request, 'core/admin/team_management.html', context)
    except Exception as e:
        logger.error(f"Error loading team management: {str(e)}")
        messages.error(request, 'Error loading team management')
        return redirect('admin_dashboard')


@require_http_methods(['GET', 'POST'])
def admin_add_loan(request):
    """
    Admin Add New Loan - Create new loan applications
    Allows admin to manually create loan entries with all applicant details
    """
    if not request.user.is_authenticated:
        # Keeps redirects consistent with normal employee/agent login flow
        return redirect('login')

    current_role = request.user.role
    self_add_loan_route = (
        'admin_add_loan' if current_role == 'admin'
        else ('employee_add_loan' if current_role == 'employee' else 'subadmin_add_loan')
    )

    if current_role not in ['admin', 'employee', 'subadmin']:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    if request.method == 'POST':
        try:
            applicant_name = (request.POST.get('name') or request.POST.get('applicant_name') or '').strip()
            applicant_email = (request.POST.get('email_id') or request.POST.get('applicant_email') or '').strip()
            applicant_mobile = (request.POST.get('mobile_no') or request.POST.get('applicant_mobile') or '').strip()
            loan_uid = (request.POST.get('loan_uid') or '').strip()
            raw_loan_type = (request.POST.get('service_required') or request.POST.get('loan_type') or '').strip()
            raw_amount = (request.POST.get('loan_amount_required') or request.POST.get('loan_amount') or '').strip()
            raw_tenure = (request.POST.get('loan_tenure') or request.POST.get('tenure_months') or '').strip()
            raw_interest = (request.POST.get('interest_rate') or '').strip()

            if not applicant_name or not applicant_mobile or not raw_loan_type or not raw_amount:
                messages.error(request, 'Please fill all required fields (Name, Mobile, Loan Type, Loan Amount).')
                return redirect(self_add_loan_route)

            if loan_uid and Loan.objects.filter(user_id=loan_uid).exists():
                messages.error(request, 'Loan ID already exists. Please enter a unique Loan ID.')
                return redirect(self_add_loan_route)

            loan_type_map = {
                'personal loan': 'personal',
                'personal': 'personal',
                'lap': 'lap',
                'loan against property': 'lap',
                'home loan': 'home',
                'home': 'home',
                'business loan': 'business',
                'business': 'business',
                'auto loan': 'car',
                'auto': 'car',
                'education loan': 'education',
                'education': 'education',
                'car loan': 'car',
                'car': 'car',
                'security loan': 'other',
                'security': 'other',
                'credit card': 'other',
                'other': 'other',
            }
            loan_type = loan_type_map.get(raw_loan_type.lower(), 'other')

            try:
                loan_amount = float(raw_amount)
            except (TypeError, ValueError):
                messages.error(request, 'Invalid loan amount.')
                return redirect(self_add_loan_route)

            tenure_months = None
            if raw_tenure:
                try:
                    tenure_months = int(raw_tenure)
                except (TypeError, ValueError):
                    tenure_months = None

            interest_rate = None
            if raw_interest:
                try:
                    interest_rate = float(raw_interest)
                except (TypeError, ValueError):
                    interest_rate = None

            permanent_city = (request.POST.get('permanent_city') or '').strip()
            present_city = (request.POST.get('present_city') or '').strip()
            city = permanent_city or present_city
            state = (request.POST.get('permanent_state') or request.POST.get('state') or '').strip()
            pin_code = (request.POST.get('permanent_pin') or request.POST.get('present_pin') or '').strip()

            remarks_field_map = {
                'alternate_mobile': 'Alternate Mobile',
                'fathers_name': 'Father Name',
                'mothers_name': 'Mother Name',
                'dob': 'Date of Birth',
                'gender': 'Gender',
                'marital_status': 'Marital Status',
                'permanent_address': 'Permanent Address',
                'permanent_landmark': 'Permanent Landmark',
                'permanent_city': 'Permanent City',
                'permanent_pin': 'Permanent PIN',
                'present_address': 'Present Address',
                'present_landmark': 'Present Landmark',
                'present_city': 'Present City',
                'present_pin': 'Present PIN',
                'occupation': 'Occupation',
                'date_of_joining': 'Date of Joining',
                'year_of_experience': 'Experience (Years)',
                'additional_income': 'Additional Income',
                'company_name': 'Company Name',
                'official_email_id': 'Official Email ID',
                'designation': 'Designation',
                'previous_company': 'Previous Company',
                'company_address': 'Company Address',
                'company_landmark': 'Company Landmark',
                'salary': 'Salary',
                'gross_salary': 'Gross Salary',
                'net_salary': 'Net Salary',
                'extra_income': 'Additional Income',
                'business_address': 'Business Address',
                'business_landmark': 'Business Landmark',
                'business_pin': 'Business PIN',
                'nature_of_business': 'Nature of Business',
                'stock_value': 'Stock Value',
                'no_of_employees': 'Number of Employees',
                'itr_details': 'ITR Details',
                'loan1_bank': 'Loan 1 Bank/Finance Name',
                'loan1_amount_taken': 'Loan 1 Amount Taken',
                'loan1_emi_left': 'Loan 1 EMI Left',
                'loan1_amount_left': 'Loan 1 Amount Left',
                'loan1_duration': 'Loan 1 Years/Months',
                'loan1_emi_over': 'Loan 1 EMI Amount',
                'loan1_bounce': 'Loan 1 Any Bounce',
                'loan1_cleared': 'Loan 1 Cleared',
                'loan2_bank': 'Loan 2 Bank/Finance Name',
                'loan2_amount_taken': 'Loan 2 Amount Taken',
                'loan2_emi_left': 'Loan 2 EMI Left',
                'loan2_amount_left': 'Loan 2 Amount Left',
                'loan2_duration': 'Loan 2 Years/Months',
                'loan2_emi_over': 'Loan 2 EMI Amount',
                'loan2_bounce': 'Loan 2 Any Bounce',
                'loan2_cleared': 'Loan 2 Cleared',
                'loan3_bank': 'Loan 3 Bank/Finance Name',
                'loan3_amount_taken': 'Loan 3 Amount Taken',
                'loan3_emi_left': 'Loan 3 EMI Left',
                'loan3_amount_left': 'Loan 3 Amount Left',
                'loan3_duration': 'Loan 3 Years/Months',
                'loan3_emi_over': 'Loan 3 EMI Amount',
                'loan3_bounce': 'Loan 3 Any Bounce',
                'loan3_cleared': 'Loan 3 Cleared',
                'charges_or_fee': 'Charges/Fee',
                'service_required_other': 'Service Required (Other)',
                'cibil_score': 'CIBIL Score',
                'aadhar_number': 'Aadhar Number',
                'pan_number': 'PAN Number',
                'bank_name': 'Bank Name',
                'account_number': 'Account Number',
                'ifsc_code': 'IFSC Code',
                'ref1_name': 'Reference 1 Name',
                'ref1_mobile': 'Reference 1 Mobile',
                'ref1_address': 'Reference 1 Address',
                'ref2_name': 'Reference 2 Name',
                'ref2_mobile': 'Reference 2 Mobile',
                'ref2_address': 'Reference 2 Address',
                'remarks_suggestions': 'Remarks/Suggestions',
                'documents_available': 'Documents Available',
                'declaration': 'Declaration',
            }
            remarks_lines = []
            for field_name, label in remarks_field_map.items():
                value = (request.POST.get(field_name) or '').strip()
                if value:
                    remarks_lines.append(f"{label}: {value}")

            handled_fields = set(remarks_field_map.keys())
            skip_fields = {
                'csrfmiddlewaretoken',
                'name',
                'applicant_name',
                'email_id',
                'applicant_email',
                'mobile_no',
                'applicant_mobile',
                'loan_uid',
                'service_required',
                'loan_type',
                'loan_amount_required',
                'loan_amount',
                'loan_tenure',
                'tenure_months',
                'interest_rate',
                'loan_purpose',
                'same_as_permanent',
            }
            for key, raw_value in request.POST.items():
                if key in handled_fields or key in skip_fields or key.endswith('[]'):
                    continue
                value = (raw_value or '').strip()
                if not value:
                    continue
                label = key.replace('_', ' ').title()
                remarks_lines.append(f"{label}: {value}")

            document_names = [(name or '').strip() for name in request.POST.getlist('document_name[]')]
            expanded_document_names = [(name or '').strip() for name in request.POST.getlist('document_name_expanded[]')]
            if document_names:
                for idx, doc_name in enumerate(document_names, start=1):
                    if doc_name:
                        remarks_lines.append(f"Document {idx}: {doc_name}")

            agent_profile = None
            if request.user.role == 'agent':
                agent_profile = Agent.objects.filter(user=request.user).first()

            loan = Loan.objects.create(
                full_name=applicant_name,
                user_id=loan_uid or None,
                email=applicant_email or None,
                mobile_number=applicant_mobile,
                city=city or None,
                state=state or None,
                pin_code=pin_code or None,
                permanent_address=(request.POST.get('permanent_address') or '').strip() or None,
                current_address=(request.POST.get('present_address') or '').strip() or None,
                loan_type=loan_type,
                loan_amount=loan_amount,
                tenure_months=tenure_months,
                interest_rate=interest_rate,
                loan_purpose=(request.POST.get('loan_purpose') or request.POST.get('remarks_suggestions') or '').strip() or None,
                bank_name=(request.POST.get('bank_name') or '').strip() or None,
                bank_account_number=(request.POST.get('account_number') or '').strip() or None,
                bank_ifsc_code=(request.POST.get('ifsc_code') or '').strip() or None,
                status='new_entry',
                applicant_type='employee',
                assigned_employee=request.user if request.user.role == 'employee' else None,
                assigned_at=timezone.now() if request.user.role == 'employee' else None,
                assigned_agent=agent_profile,
                created_by=request.user,
                remarks="\n".join(remarks_lines) if remarks_lines else None,
            )

            def get_document_type(raw_name, index):
                normalized = (raw_name or '').lower().strip()
                type_map = [
                    ('pan', 'pan_card'),
                    ('aadhaar', 'aadhaar_card'),
                    ('aadhar', 'aadhaar_card'),
                    ('co applicant pan', 'co_applicant_pan'),
                    ('co-applicant pan', 'co_applicant_pan'),
                    ('co applicant aadhar', 'co_applicant_aadhaar'),
                    ('co-applicant aadhar', 'co_applicant_aadhaar'),
                    ('co applicant aadhaar', 'co_applicant_aadhaar'),
                    ('co-applicant aadhaar', 'co_applicant_aadhaar'),
                    ('co applicant photo', 'co_applicant_photo'),
                    ('co-applicant photo', 'co_applicant_photo'),
                    ('soa', 'soa_existing_loan'),
                    ('forclos', 'forclosure_document'),
                    ('forclose', 'forclosure_document'),
                    ('forclosure', 'forclosure_document'),
                    ('photo', 'applicant_photo'),
                    ('permanent address', 'permanent_address_proof'),
                    ('recent address', 'current_address_proof'),
                    ('current address', 'current_address_proof'),
                    ('salary slip', 'salary_slip'),
                    ('bank statement', 'bank_statement'),
                    ('form 16', 'form_16'),
                    ('service book', 'service_book'),
                    ('property', 'property_documents'),
                    ('patta', 'property_documents'),
                    ('pauti', 'property_documents'),
                    ('ror', 'property_documents'),
                    ('bda approval', 'property_documents'),
                    ('rc', 'other_rc'),
                    ('insurance certificate', 'other_insurance_certificate'),
                    ('insurance', 'other_insurance'),
                    ('gst', 'other_gst'),
                    ('business vintage', 'other_business_vintage'),
                    ('itr', 'other_itr_with_computation'),
                ]
                for token, mapped in type_map:
                    if token in normalized:
                        return mapped
                return 'other' if index == 1 else f'other_{index}'

            documents_files = request.FILES.getlist('document_file[]')
            document_name_sequence = expanded_document_names if len(expanded_document_names) >= len(documents_files) else document_names
            for idx, uploaded_file in enumerate(documents_files, start=1):
                if not uploaded_file:
                    continue
                if idx - 1 < len(document_name_sequence):
                    doc_name = document_name_sequence[idx - 1]
                elif document_names:
                    doc_name = document_names[-1]
                else:
                    doc_name = ''
                document_type = get_document_type(doc_name, idx)
                if LoanDocument.objects.filter(loan=loan, document_type=document_type).exists():
                    document_type = f"{document_type}_{idx}"

                LoanDocument.objects.create(
                    loan=loan,
                    document_type=document_type[:50],
                    file=uploaded_file,
                    is_required=False,
                )

            ActivityLog.objects.create(
                action='loan_added',
                description=f"Loan application created for '{loan.full_name}' (Loan ID {loan.id})",
                user=request.user,
                related_loan=loan,
            )

            messages.success(request, f'Loan application submitted successfully! ID: {loan.id}')
            if request.user.role == 'admin':
                return redirect('admin_all_loans')
            if request.user.role == 'subadmin':
                return redirect('subadmin_all_loans')
            return redirect('employee_all_loans')
        except Exception as e:
            logger.error(f"Error creating loan: {str(e)}")
            messages.error(request, f'Error creating loan application: {str(e)}')
            return redirect(self_add_loan_route)

    recent_qs = Loan.objects.filter(created_by=request.user).order_by('-created_at')[:8]
    recent_loans = [{
        'applicant_name': loan.full_name or '-',
        'phone': loan.mobile_number or '-',
        'loan_amount_required': loan.loan_amount,
        'service_required': loan.get_loan_type_display(),
        'created_date': loan.created_at,
        'status': loan.status,
    } for loan in recent_qs]

    context = {
        'page_title': 'Add New Loan Application',
        'recent_loans': recent_loans,
    }
    template_name = 'core/admin/add_loan.html' if request.user.role == 'admin' else 'core/employee/add_loan.html'
    return render(request, template_name, context)


@login_required(login_url='admin_login')
@admin_required
def admin_join_requests(request):
    """
    Admin Join Requests - Shows pending requests from users wanting to join as SubAdmins/Agents
    """
    try:
        pending_count = LoanApplication.objects.filter(
            applicant__role__in=['employee', 'agent'],
            status='New Entry'
        ).count()
        context = {
            'page_title': 'Join Requests',
            'join_requests': [],
            'request_count': pending_count,
        }
        return render(request, 'core/admin/join_requests.html', context)
    except Exception as e:
        logger.error(f"Error loading join requests: {str(e)}")
        messages.error(request, 'Error loading join requests')
        return redirect('admin_dashboard')


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_join_requests(request):
    """
    Real-time API for join requests originating from login-page registration.
    Uses LoanApplication + Applicant as source.
    """
    try:
        applications = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
            'assigned_by',
        ).prefetch_related('documents').filter(
            applicant__role__in=['employee', 'agent'],
            status='New Entry',
        ).order_by('-created_at')

        requests_data = []
        for app in applications:
            applicant = app.applicant
            related_loan = find_related_loan(app)
            documents = _merge_join_documents(
                app.documents.all(),
                related_loan.documents.all() if related_loan else [],
            )

            requests_data.append({
                'id': app.id,
                'application_id': app.id,
                'applicant_id': applicant.id,
                'applicant_name': applicant.full_name or '-',
                'username': applicant.username or '-',
                'role': applicant.role or '-',
                'mobile': applicant.mobile or '-',
                'email': applicant.email or '-',
                'city': applicant.city or '-',
                'state': applicant.state or '-',
                'pin_code': applicant.pin_code or '-',
                'gender': applicant.gender or '-',
                'loan_type': applicant.loan_type or '-',
                'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                'tenure_months': applicant.tenure_months or '-',
                'interest_rate': float(applicant.interest_rate) if applicant.interest_rate else 0,
                'emi': float(applicant.emi) if applicant.emi else 0,
                'loan_purpose': applicant.loan_purpose or '-',
                'bank_name': applicant.bank_name or '-',
                'bank_type': applicant.bank_type or '-',
                'account_number': applicant.account_number or '-',
                'ifsc_code': applicant.ifsc_code or '-',
                'status': app.status,
                'assigned_employee': app.assigned_employee.get_full_name() if app.assigned_employee else '-',
                'assigned_agent': app.assigned_agent.name if app.assigned_agent else '-',
                'assigned_by': app.assigned_by.get_full_name() if app.assigned_by else '-',
                'assigned_at': app.assigned_at.strftime('%Y-%m-%d %H:%M') if app.assigned_at else '-',
                'request_date': app.created_at.strftime('%Y-%m-%d %H:%M') if app.created_at else '-',
                'updated_at': app.updated_at.strftime('%Y-%m-%d %H:%M') if app.updated_at else '-',
                'documents': documents,
                'documents_count': len(documents),
                'can_approve': app.status == 'New Entry',
                'can_reject': app.status == 'New Entry',
                'can_delete': True,
            })

        return JsonResponse({
            'success': True,
            'count': len(requests_data),
            'requests': requests_data,
        })
    except Exception as e:
        logger.error(f"Error loading join request data: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_join_request_detail(request, application_id):
    """Fetch full join-request details for modal view (all sections)."""
    try:
        application = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
            'assigned_by',
        ).prefetch_related('documents').get(id=application_id, applicant__role__in=['employee', 'agent'])
    except LoanApplication.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Join request not found'}, status=404)

    try:
        payload = _build_join_request_detail_payload(application)
        return JsonResponse({'success': True, 'data': payload})
    except Exception as exc:
        logger.error(f"Error loading join request detail {application_id}: {str(exc)}")
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_http_methods(['POST'])
def api_admin_join_request_action(request, application_id):
    """Handle approve/reject/delete actions for join requests."""
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid request payload'}, status=400)

    action = str(data.get('action', '')).strip().lower()
    if action not in ['approve', 'reject', 'delete']:
        return JsonResponse({'success': False, 'error': 'Invalid action'}, status=400)

    try:
        application = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
            'assigned_by',
        ).get(id=application_id, applicant__role__in=['employee', 'agent'])
    except LoanApplication.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Join request not found'}, status=404)

    applicant = application.applicant

    try:
        if action == 'delete':
            applicant_name = applicant.full_name or f'Application {application.id}'
            related_loan = find_related_loan(application)
            if related_loan and related_loan.status != 'disbursed':
                related_loan.delete()
            application.delete()
            ActivityLog.objects.create(
                action='status_updated',
                description=f'Join request deleted for {applicant_name}',
                user=request.user,
            )
            return JsonResponse({'success': True, 'message': f'Join request deleted for {applicant_name}'})

        if action == 'reject':
            reason = str(data.get('reason', '')).strip() or 'Rejected by admin from Join Requests'
            application.status = 'Rejected'
            application.rejected_by = request.user
            application.rejected_at = timezone.now()
            application.rejection_reason = reason
            application.save(update_fields=['status', 'rejected_by', 'rejected_at', 'rejection_reason', 'updated_at'])

            applicant.status = 'Rejected'
            applicant.save(update_fields=['status', 'updated_at'])

            ActivityLog.objects.create(
                action='status_updated',
                description=f'Join request rejected for {applicant.full_name}: {reason}',
                user=request.user,
            )
            return JsonResponse({'success': True, 'message': f'Join request rejected for {applicant.full_name}'})

        # Approve flow
        with transaction.atomic():
            first_name, last_name = _split_name(applicant.full_name)
            candidate_username = applicant.username or (applicant.email.split('@')[0] if applicant.email else f'user{application.id}')
            existing_user = None
            if applicant.email:
                existing_user = User.objects.filter(email__iexact=applicant.email).first()

            created_new_user = False
            temp_password = ''

            if existing_user:
                if existing_user.role in ['admin', 'subadmin', 'dsa']:
                    return JsonResponse({
                        'success': False,
                        'error': f'Email already belongs to {existing_user.get_role_display()}. Cannot auto-approve this request.'
                    }, status=400)
                user = existing_user
                user.role = applicant.role
                user.first_name = first_name or user.first_name
                user.last_name = last_name or user.last_name
                user.phone = applicant.mobile or user.phone
                user.gender = _normalize_user_gender(applicant.gender)
                user.is_active = True
                user.save()
            else:
                username = _build_unique_username(candidate_username)
                temp_password = f"Gbms@{application.id}{(applicant.mobile or '0000')[-4:]}"
                user = User.objects.create_user(
                    username=username,
                    email=applicant.email or '',
                    password=temp_password,
                    first_name=first_name,
                    last_name=last_name,
                    role=applicant.role,
                    phone=applicant.mobile,
                    gender=_normalize_user_gender(applicant.gender),
                    address=', '.join([v for v in [applicant.city, applicant.state, applicant.pin_code] if v]) or None,
                    is_active=True,
                )
                created_new_user = True

            created_agent = None
            if applicant.role == 'agent':
                created_agent = Agent.objects.filter(user=user).first()
                if not created_agent:
                    created_agent = Agent.objects.filter(email__iexact=applicant.email).first() if applicant.email else None

                if created_agent:
                    created_agent.user = user
                    created_agent.name = applicant.full_name or created_agent.name
                    created_agent.phone = applicant.mobile or created_agent.phone
                    created_agent.email = applicant.email or created_agent.email
                    created_agent.gender = _normalize_user_gender(applicant.gender)
                    created_agent.city = applicant.city or created_agent.city
                    created_agent.state = applicant.state or created_agent.state
                    created_agent.pin_code = applicant.pin_code or created_agent.pin_code
                    created_agent.address = created_agent.address or ', '.join([v for v in [applicant.city, applicant.state, applicant.pin_code] if v])
                    created_agent.status = 'active'
                    if not created_agent.created_by:
                        created_agent.created_by = request.user
                    created_agent.save()
                else:
                    created_agent = Agent.objects.create(
                        user=user,
                        name=applicant.full_name or user.get_full_name() or user.username,
                        phone=applicant.mobile or '0000000000',
                        email=applicant.email or '',
                        address=', '.join([v for v in [applicant.city, applicant.state, applicant.pin_code] if v]) or None,
                        gender=_normalize_user_gender(applicant.gender),
                        city=applicant.city or None,
                        state=applicant.state or None,
                        pin_code=applicant.pin_code or None,
                        status='active',
                        created_by=request.user,
                    )
                application.assigned_agent = created_agent
                application.assigned_employee = None
            else:
                application.assigned_employee = user
                application.assigned_agent = None

            application.status = 'Approved'
            application.approved_by = request.user
            application.approved_at = timezone.now()
            application.assigned_by = request.user
            application.assigned_at = timezone.now()
            application.approval_notes = f'Approved from Join Requests by {request.user.get_full_name() or request.user.username}'
            application.save(
                update_fields=[
                    'status',
                    'approved_by',
                    'approved_at',
                    'assigned_by',
                    'assigned_at',
                    'approval_notes',
                    'assigned_agent',
                    'assigned_employee',
                    'updated_at',
                ]
            )

            applicant.status = 'Approved'
            applicant.save(update_fields=['status', 'updated_at'])

            ActivityLog.objects.create(
                action='status_updated',
                description=f'Join request approved for {applicant.full_name} ({applicant.role})',
                user=request.user,
            )

        response = {
            'success': True,
            'message': f'Join request approved. {applicant.role.title()} is now active under admin.',
            'username': user.username,
            'role': applicant.role,
            'application_status': application.status,
        }
        if created_new_user:
            response['temporary_password'] = temp_password
            response['password_note'] = 'Temporary password generated. Please change after first login.'
        return JsonResponse(response)
    except Exception as exc:
        logger.error(f"Error performing join request action {action} on {application_id}: {str(exc)}")
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@login_required(login_url='admin_login')
@admin_required
def admin_new_entries(request):
    """View New Entry applications"""
    applications = LoanApplication.objects.filter(status='New Entry').select_related('applicant', 'assigned_employee', 'assigned_agent', 'assigned_by').order_by('-created_at')
    
    context = {
        'page_title': 'New Applications',
        'applications': applications,
        'status_name': 'New Entry',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_in_processing(request):
    """View In Processing applications"""
    applications = LoanApplication.objects.filter(status='Waiting for Processing').select_related('applicant', 'assigned_employee', 'assigned_agent', 'assigned_by').order_by('-created_at')
    
    context = {
        'page_title': 'Document Pending Applications',
        'applications': applications,
        'status_name': 'Waiting for Processing',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_follow_ups(request):
    """View Banking Processing applications"""
    applications = LoanApplication.objects.filter(status='Required Follow-up').select_related('applicant', 'assigned_employee', 'assigned_agent', 'assigned_by').order_by('-created_at')
    
    context = {
        'page_title': 'Banking Processing Applications',
        'applications': applications,
        'status_name': 'Banking Processing',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_approved(request):
    """View Approved applications"""
    applications = LoanApplication.objects.filter(status='Approved').select_related('applicant', 'assigned_employee', 'assigned_agent', 'assigned_by').order_by('-created_at')
    
    context = {
        'page_title': 'Approved Applications',
        'applications': applications,
        'status_name': 'Approved',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_rejected(request):
    """View Rejected applications"""
    applications = LoanApplication.objects.filter(status='Rejected').select_related('applicant', 'assigned_employee', 'assigned_agent', 'assigned_by').order_by('-created_at')
    
    context = {
        'page_title': 'Rejected Applications',
        'applications': applications,
        'status_name': 'Rejected',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_disbursed(request):
    """View Disbursed applications"""
    applications = LoanApplication.objects.filter(status='Disbursed').select_related('applicant', 'assigned_employee', 'assigned_agent', 'assigned_by').order_by('-created_at')
    
    context = {
        'page_title': 'Disbursed Applications',
        'applications': applications,
        'status_name': 'Disbursed',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def assign_application(request, app_id):
    """Assign an application to an employee"""
    try:
        application = LoanApplication.objects.get(id=app_id)
    except LoanApplication.DoesNotExist:
        return redirect('admin_new_entries')
    
    # Get all active agents/employees (excluding superusers and staff)
    agents = User.objects.filter(is_active=True, is_staff=False).exclude(is_superuser=True)
    
    if request.method == 'POST':
        agent_id = request.POST.get('agent_id')
        try:
            agent = User.objects.get(id=agent_id)
            application.assigned_employee = agent
            application.status = 'Waiting for Processing'
            application.save()
            return redirect('admin_in_processing')
        except User.DoesNotExist:
            pass
    
    applicant_name = request.GET.get('applicant', application.applicant.full_name)
    
    context = {
        'application': application,
        'applicant_name': applicant_name,
        'agents': agents,
        'page_title': 'Assign Application',
    }
    return render(request, 'core/admin/assign_application.html', context)


@login_required(login_url='admin_login')
@admin_required
def api_get_application_details(request, app_id):
    """API endpoint to fetch full application details"""
    try:
        application = LoanApplication.objects.select_related('applicant', 'assigned_employee').get(id=app_id)
        applicant = application.applicant
        
        # Get existing loans if available
        existing_loans = []
        try:
            # Try to get from applicant model if it has existing loan fields
            if hasattr(applicant, 'existing_loans'):
                existing_loans = applicant.existing_loans if applicant.existing_loans else []
        except:
            pass
        
        data = {
            'success': True,
            'application': {
                'id': application.id,
                'status': application.status,
                'created_at': application.created_at.strftime('%Y-%m-%d %H:%M'),
                'assigned_employee': application.assigned_employee.get_full_name() if application.assigned_employee else 'Not Assigned',
            },
            'applicant': {
                # Section 1: Name & Contact Details
                'full_name': applicant.full_name or '',
                'mobile': applicant.mobile or '',
                'alternate_mobile': getattr(applicant, 'alternate_mobile', '') or '',
                'email': applicant.email or '',
                'father_name': getattr(applicant, 'father_name', '') or '',
                'mother_name': getattr(applicant, 'mother_name', '') or '',
                'date_of_birth': applicant.date_of_birth.strftime('%Y-%m-%d') if hasattr(applicant, 'date_of_birth') and applicant.date_of_birth else '',
                'gender': getattr(applicant, 'gender', '') or '',
                'marital_status': getattr(applicant, 'marital_status', '') or '',
                
                # Permanent Address
                'permanent_address': getattr(applicant, 'permanent_address', '') or '',
                'permanent_landmark': getattr(applicant, 'permanent_landmark', '') or '',
                'permanent_city': getattr(applicant, 'permanent_city', '') or '',
                'permanent_pin': getattr(applicant, 'permanent_pin', '') or '',
                
                # Present Address
                'present_address': getattr(applicant, 'present_address', '') or '',
                'present_landmark': getattr(applicant, 'present_landmark', '') or '',
                'present_city': getattr(applicant, 'present_city', '') or '',
                'present_pin': getattr(applicant, 'present_pin', '') or '',
                
                # Section 2: Occupation & Income Details
                'occupation': getattr(applicant, 'occupation', '') or '',
                'date_of_joining': getattr(applicant, 'date_of_joining', None),
                'year_of_experience': getattr(applicant, 'year_of_experience', '') or '',
                'additional_income': getattr(applicant, 'additional_income', '') or '',
                'extra_income_details': getattr(applicant, 'extra_income_details', '') or '',
                
                # Section 4: Loan Request
                'loan_type': applicant.loan_type or '',
                'loan_amount': str(applicant.loan_amount) if applicant.loan_amount else '',
                'loan_tenure': getattr(applicant, 'loan_tenure', '') or '',
                'charges_fee': getattr(applicant, 'charges_fee', 'No') or 'No',
                
                # Section 6: Financial & Bank Details
                'cibil_score': getattr(applicant, 'cibil_score', '') or '',
                'aadhar_number': getattr(applicant, 'aadhar_number', '') or '',
                'pan_number': getattr(applicant, 'pan_number', '') or '',
                'bank_name': getattr(applicant, 'bank_name', '') or '',
                'account_number': getattr(applicant, 'account_number', '') or '',
                'remarks': getattr(applicant, 'remarks', '') or '',
                'declaration': getattr(applicant, 'declaration', 'No') or 'No',
            },
            'documents': []
        }
        
        # Get documents
        try:
            documents = ApplicantDocument.objects.filter(applicant=applicant)
            for doc in documents:
                data['documents'].append({
                    'name': doc.document_type or 'Document',
                    'url': doc.file.url if doc.file else '',
                    'uploaded': doc.uploaded_at.strftime('%Y-%m-%d') if doc.uploaded_at else ''
                })
        except:
            pass
        
        return JsonResponse(data)
    except LoanApplication.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Application not found'}, status=404)
