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
from datetime import datetime, timezone as datetime_timezone
import json
import logging
import re

from .models import LoanApplication, Applicant, ApplicantDocument, LoanAssignment, LoanStatusHistory, User, Agent, Loan, LoanDocument, ActivityLog, SubAdminEntry, UserOnboardingProfile, UserOnboardingDocument, EmployeeProfile, AgentAssignment
from .decorators import admin_required
from .loan_sync import extract_assignment_context, role_label, find_related_loan, find_related_loan_application
from .onboarding_utils import (
    collect_onboarding_payload,
    collect_onboarding_documents,
    collect_onboarding_payload_from_source,
    collect_user_document_payload,
)
from .followup_utils import auto_move_overdue_to_follow_up
from .upload_limits import validate_loan_document_batch
from .id_utils import generate_agent_sequence_id, generate_user_sequence_id, normalize_manual_loan_id, display_manual_loan_id
from .loan_helpers import display_loan_id, get_lead_receive_options, resolve_lead_receive_name, is_password_protected_document_name
from .updated_document_utils import (
    UPDATED_DOCUMENT_LABEL,
    UPDATED_DOCUMENT_STATUS_KEY,
    application_has_updated_documents,
    loan_has_updated_documents,
)
from .account_notifications import send_account_credentials_email
from .workflow_rows import (
    application_effective_status_key,
    build_application_display_row,
)

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
SUBADMIN_TAG_PATTERN = re.compile(r'\[subadmin:\d+\]', flags=re.IGNORECASE)


def _has_revert_marker(value):
    return 'revert remark' in str(value or '').lower()


def _follow_up_pending_q():
    return Q(status__in=['new_entry', 'waiting']) & Q(remarks__icontains='Revert Remark')


def _parse_int_list(raw_values):
    ids = []
    for value in raw_values or []:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            ids.append(parsed)
    return sorted(set(ids))


def _normalize_filter_id(raw_value):
    value = str(raw_value or '').strip()
    if not value:
        return ''
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return ''
    return str(parsed) if parsed > 0 else ''


def _join_registration_filter():
    """Login-page registrations do not carry loan request fields."""
    return (
        Q(applicant__role__in=['employee', 'agent'])
        & (Q(applicant__loan_type__isnull=True) | Q(applicant__loan_type=''))
        & Q(applicant__loan_amount__isnull=True)
    )


def _normalize_detail_key(value):
    text = str(value or '').strip().lower()
    text = text.replace('_', ' ').replace('-', ' ').replace('/', ' ')
    return ' '.join(text.split())


def _parse_detail_lines(raw_text):
    parsed = {}
    for line in str(raw_text or '').replace('\r', '\n').splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        clean_key = _normalize_detail_key(key)
        clean_value = str(value or '').strip()
        if clean_key and clean_value:
            parsed[clean_key] = clean_value
    return parsed


def _detail_value(parsed_details, *keys, default=''):
    for key in keys:
        value = parsed_details.get(_normalize_detail_key(key))
        if value not in [None, '']:
            return value
    return default


def _lead_receive_names_from_remarks(raw_text):
    parsed = _parse_detail_lines(raw_text)
    return {
        'channel_partner': _detail_value(
            parsed,
            'lead receive channel partner name',
            'channel partner name',
            default='',
        ),
        'employee': _detail_value(
            parsed,
            'lead receive employee name',
            'employee name',
            'employee',
            default='',
        ),
        'leader': _detail_value(
            parsed,
            'lead receive leader name',
            'leader name',
            'partner name',
            default='',
        ),
    }


def _non_empty_or_na(value):
    text = str(value or '').strip()
    return text if text else 'N/A'


def _display_user_name(user_obj, fallback=''):
    if not user_obj:
        return fallback
    return user_obj.get_full_name() or user_obj.username or user_obj.email or fallback


def _lead_receive_defaults_for_user(user_obj):
    defaults = {
        'lead_receive_channel_partner_name': '',
        'lead_receive_employee_name': '',
        'lead_receive_leader_name': '',
    }
    role = getattr(user_obj, 'role', '')
    if role == 'agent':
        agent_profile = Agent.objects.filter(user=user_obj).select_related('created_by').first()
        defaults['lead_receive_channel_partner_name'] = (
            getattr(agent_profile, 'name', '') if agent_profile else ''
        ) or _display_user_name(user_obj)
        if agent_profile and getattr(getattr(agent_profile, 'created_by', None), 'role', '') == 'subadmin':
            defaults['lead_receive_leader_name'] = _display_user_name(agent_profile.created_by)
    elif role == 'employee':
        defaults['lead_receive_employee_name'] = _display_user_name(user_obj)
    elif role == 'subadmin':
        defaults['lead_receive_leader_name'] = _display_user_name(user_obj)
    return defaults


def _partner_user_for_loan(loan_obj, related_app=None, assignment_context=None):
    assignment_context = assignment_context or {}
    assigned_by_user = assignment_context.get('assigned_by_user')
    if getattr(assigned_by_user, 'role', '') == 'subadmin':
        return assigned_by_user

    assigned_agent = getattr(loan_obj, 'assigned_agent', None)
    if assigned_agent and getattr(getattr(assigned_agent, 'created_by', None), 'role', '') == 'subadmin':
        return assigned_agent.created_by

    if related_app:
        app_assigned_by = getattr(related_app, 'assigned_by', None)
        if getattr(app_assigned_by, 'role', '') == 'subadmin':
            return app_assigned_by
        app_agent = getattr(related_app, 'assigned_agent', None)
        if app_agent and getattr(getattr(app_agent, 'created_by', None), 'role', '') == 'subadmin':
            return app_agent.created_by

    creator = getattr(loan_obj, 'created_by', None)
    if getattr(creator, 'role', '') == 'subadmin':
        return creator
    return None


def _partner_user_for_application(app_obj):
    assigned_by = getattr(app_obj, 'assigned_by', None)
    if getattr(assigned_by, 'role', '') == 'subadmin':
        return assigned_by

    assigned_agent = getattr(app_obj, 'assigned_agent', None)
    if assigned_agent and getattr(getattr(assigned_agent, 'created_by', None), 'role', '') == 'subadmin':
        return assigned_agent.created_by
    return None


def _set_employee_under_subadmin(employee, subadmin_user=None):
    profile, _ = EmployeeProfile.objects.get_or_create(user=employee)
    notes = SUBADMIN_TAG_PATTERN.sub('', str(profile.notes or '')).strip()
    notes = re.sub(r'\n{3,}', '\n\n', notes)
    if subadmin_user:
        tag = f"[subadmin:{subadmin_user.id}]"
        notes = f"{notes}\n{tag}".strip() if notes else tag
    profile.notes = notes
    profile.save(update_fields=['notes', 'updated_at'])
    return profile


def _sync_partner_employees(subadmin, employee_ids):
    tag = f"[subadmin:{subadmin.id}]"
    desired_ids = set(
        User.objects.filter(id__in=employee_ids, role='employee').values_list('id', flat=True)
    )

    current_employees = User.objects.filter(
        role='employee',
        employee_profile__notes__icontains=tag,
    ).distinct()
    for employee in current_employees.exclude(id__in=desired_ids):
        _set_employee_under_subadmin(employee, None)
    for employee in User.objects.filter(id__in=desired_ids, role='employee'):
        _set_employee_under_subadmin(employee, subadmin)
    return len(desired_ids)


def _sync_partner_channel_partners(subadmin, channel_partner_ids, fallback_owner=None):
    desired_ids = set(
        Agent.objects.filter(id__in=channel_partner_ids, status='active').values_list('id', flat=True)
    )
    fallback = fallback_owner or User.objects.filter(role='admin', is_active=True).order_by('id').first()

    Agent.objects.filter(created_by=subadmin).exclude(id__in=desired_ids).update(created_by=fallback)

    selected_agents = Agent.objects.filter(id__in=desired_ids).select_related('under_employee')
    for agent in selected_agents:
        update_fields = []
        if agent.created_by_id != subadmin.id:
            agent.created_by = subadmin
            update_fields.append('created_by')
        if update_fields:
            update_fields.append('updated_at')
            agent.save(update_fields=update_fields)
        if agent.under_employee_id:
            _set_employee_under_subadmin(agent.under_employee, subadmin)
        linked_employee_ids = AgentAssignment.objects.filter(agent=agent).values_list('employee_id', flat=True)
        for employee in User.objects.filter(id__in=linked_employee_ids, role='employee'):
            _set_employee_under_subadmin(employee, subadmin)
    return len(desired_ids)


def _is_follow_up_pending_loan(loan_obj, related_app=None):
    return _effective_status_key_for_loan(loan_obj, related_app=related_app) == 'follow_up_pending'


def _status_key_to_display_text(status_key, fallback_text=''):
    key = str(status_key or '').strip().lower()
    if key == 'follow_up_pending':
        return FOLLOW_UP_PENDING_LABEL
    if key == UPDATED_DOCUMENT_STATUS_KEY:
        return UPDATED_DOCUMENT_LABEL
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
        if legacy_key == 'waiting' and loan_has_updated_documents(loan_obj):
            return UPDATED_DOCUMENT_STATUS_KEY
        return legacy_key

    app_key = APP_STATUS_TO_LOAN_KEY.get(getattr(related_app, 'status', ''), '')
    app_follow_up_pending = app_key in ['new_entry', 'waiting'] and _has_revert_marker(getattr(related_app, 'approval_notes', ''))
    if app_follow_up_pending:
        return 'follow_up_pending'

    # If application has progressed, prefer it over stale legacy states.
    if app_key in ['follow_up', 'approved', 'rejected', 'disbursed']:
        return app_key

    effective_key = app_key if app_key in ['new_entry', 'waiting'] else legacy_key
    if effective_key == 'waiting' and loan_has_updated_documents(loan_obj, related_app=related_app):
        return UPDATED_DOCUMENT_STATUS_KEY
    return effective_key


def _compute_status_breakdown(loans_qs):
    counts = {
        'new_entry': 0,
        'waiting': 0,
        'updated_document': 0,
        'follow_up': 0,
        'follow_up_pending': 0,
        'approved': 0,
        'rejected': 0,
        'disbursed': 0,
        'total': 0,
    }

    for loan in loans_qs:
        status_key = _effective_status_key_for_loan(loan)
        if status_key in [
            'new_entry',
            'waiting',
            'updated_document',
            'follow_up',
            'approved',
            'rejected',
            'disbursed',
            'follow_up_pending',
        ]:
            counts[status_key] += 1
        counts['total'] += 1

    return counts


def _effective_status_key_for_application(app_obj):
    app_key = APP_STATUS_TO_LOAN_KEY.get(getattr(app_obj, 'status', ''), '')
    if app_key in ['new_entry', 'waiting'] and _has_revert_marker(getattr(app_obj, 'approval_notes', '')):
        return 'follow_up_pending'
    if app_key == 'waiting' and application_has_updated_documents(app_obj):
        return UPDATED_DOCUMENT_STATUS_KEY
    return app_key


def _compute_application_status_breakdown(apps_qs):
    counts = {
        'new_entry': 0,
        'waiting': 0,
        'updated_document': 0,
        'follow_up': 0,
        'follow_up_pending': 0,
        'approved': 0,
        'rejected': 0,
        'disbursed': 0,
        'total': 0,
    }

    for app in apps_qs:
        status_key = _effective_status_key_for_application(app)
        if status_key in counts:
            counts[status_key] += 1
        counts['total'] += 1
    return counts


def _merge_status_counts(primary_counts, extra_counts):
    for key, value in extra_counts.items():
        primary_counts[key] = primary_counts.get(key, 0) + value
    return primary_counts


def _ui_status_label(status_text):
    normalized = str(status_text or '').strip().lower()
    if normalized in ['new entry', 'new_entry', 'draft']:
        return 'New Application'
    if normalized in ['waiting for processing', 'in processing', 'waiting', 'processing']:
        return 'Document Pending'
    if normalized in ['required follow-up', 'required follow up']:
        return 'Bank Login Process'
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
        all_loans = list(Loan.objects.all())
        status_counts = _compute_status_breakdown(all_loans)
        related_app_ids = {
            related_app.id
            for related_app in (find_related_loan_application(loan) for loan in all_loans)
            if related_app
        }
        status_counts = _merge_status_counts(
            status_counts,
            _compute_application_status_breakdown(LoanApplication.objects.exclude(id__in=related_app_ids)),
        )
        follow_up_pending_count = status_counts['follow_up_pending']
        new_entry_count = status_counts['new_entry']
        in_processing_count = status_counts['waiting']
        updated_document_count = status_counts['updated_document']
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
            'updated_document_count': updated_document_count,
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
    if status_filter == 'all':
        status_filter = ''
    agent_filter = request.GET.get('agent', '').strip()
    employee_filter = request.GET.get('employee', '').strip()
    partner_filter = request.GET.get('partner', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10
    if per_page not in [10, 25, 50, 100]:
        per_page = 10
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

    agent_filter = _normalize_filter_id(agent_filter)
    employee_filter = _normalize_filter_id(employee_filter)
    partner_filter = _normalize_filter_id(partner_filter)

    if date_from:
        loans = loans.filter(created_at__date__gte=date_from)
    if date_to:
        loans = loans.filter(created_at__date__lte=date_to)

    # Apply coarse DB filter (final status filtering happens after effective-status resolution)
    if status_filter == 'follow_up_pending':
        loans = loans.filter(status__in=['new_entry', 'waiting', 'follow_up'])
    elif status_filter in ['new_entry', 'waiting', UPDATED_DOCUMENT_STATUS_KEY, 'follow_up']:
        loans = loans.filter(status__in=['new_entry', 'waiting', 'follow_up'])
    elif status_filter in ['approved', 'rejected', 'disbursed']:
        loans = loans.filter(status__in=[status_filter, 'follow_up'])

    loan_ids_for_photos = list(loans.values_list('id', flat=True))
    legacy_photo_by_loan_id = {}
    for doc in LoanDocument.objects.filter(
        loan_id__in=loan_ids_for_photos,
        document_type__in=['applicant_photo', 'photo'],
    ).exclude(file='').order_by('loan_id', 'id'):
        if doc.loan_id not in legacy_photo_by_loan_id and doc.file:
            legacy_photo_by_loan_id[doc.loan_id] = doc.file.url

    # Pre-fetch LoanApplications to avoid N+1 query problem and include
    # workflow-only rows that do not have a matching legacy Loan record.
    apps = list(
        LoanApplication.objects.select_related(
            'applicant',
            'assigned_by',
            'assigned_employee',
            'assigned_agent',
            'assigned_agent__user',
            'assigned_agent__created_by',
        ).all()
    )
    app_by_email = {a.applicant.email.lower(): a for a in apps if a.applicant and a.applicant.email}
    app_by_mobile = {a.applicant.mobile: a for a in apps if a.applicant and a.applicant.mobile}
    app_by_name = {a.applicant.full_name.lower(): a for a in apps if a.applicant and a.applicant.full_name}
    app_photo_by_app_id = {}
    for doc in ApplicantDocument.objects.filter(
        loan_application_id__in=[app.id for app in apps],
        document_type__in=['photo', 'applicant_photo'],
    ).exclude(file='').order_by('loan_application_id', 'id'):
        if doc.loan_application_id not in app_photo_by_app_id and doc.file:
            app_photo_by_app_id[doc.loan_application_id] = doc.file.url

    def _user_name_or_na(user_obj):
        if not user_obj:
            return 'N/A'
        return user_obj.get_full_name() or user_obj.username or user_obj.email or 'N/A'

    def _agent_name_or_na(agent_obj):
        if not agent_obj:
            return 'N/A'
        return (
            agent_obj.name
            or (agent_obj.user.get_full_name() if getattr(agent_obj, 'user', None) else '')
            or (agent_obj.user.username if getattr(agent_obj, 'user', None) else '')
            or 'N/A'
        )

    enriched_loans = []
    related_app_ids = set()
    for loan in loans:
        # Fast memory lookup instead of DB query
        related_app = None
        if loan.email and loan.email.lower() in app_by_email:
            related_app = app_by_email[loan.email.lower()]
        elif loan.mobile_number and loan.mobile_number in app_by_mobile:
            related_app = app_by_mobile[loan.mobile_number]
        elif loan.full_name and loan.full_name.lower() in app_by_name:
            related_app = app_by_name[loan.full_name.lower()]

        if not related_app:
            related_app = find_related_loan_application(loan)
        if related_app:
            related_app_ids.add(related_app.id)

        effective_status_key = _effective_status_key_for_loan(loan, related_app=related_app)
        follow_up_pending = effective_status_key == 'follow_up_pending'

        if status_filter == 'follow_up_pending' and effective_status_key != 'follow_up_pending':
            continue
        if status_filter and status_filter != 'follow_up_pending' and effective_status_key != status_filter:
            continue

        if related_app:
            if not loan.assigned_employee and related_app.assigned_employee:
                loan.assigned_employee = related_app.assigned_employee
            if not loan.assigned_agent and related_app.assigned_agent:
                loan.assigned_agent = related_app.assigned_agent

        creator = loan.created_by
        if related_app and not creator and related_app.assigned_by:
            creator = related_app.assigned_by

        creator_name = _user_name_or_na(creator)
        loan.created_under_display = f"{role_label(creator)} - {creator_name}" if creator else 'System'
        if loan.assigned_employee:
            loan.assigned_to_display = f"Employee - {_user_name_or_na(loan.assigned_employee)}"
        elif loan.assigned_agent:
            loan.assigned_to_display = f"Channel Partner - {_agent_name_or_na(loan.assigned_agent)}"
        else:
            loan.assigned_to_display = 'N/A'
        assignment_context = extract_assignment_context(loan, related_app)
        partner_user = _partner_user_for_loan(loan, related_app=related_app, assignment_context=assignment_context)
        lead_names = _lead_receive_names_from_remarks(getattr(loan, 'remarks', ''))

        if agent_filter and str(loan.assigned_agent_id or '') != agent_filter:
            continue
        if employee_filter and str(loan.assigned_employee_id or '') != employee_filter:
            continue
        if partner_filter and str(getattr(partner_user, 'id', '') or '') != partner_filter:
            continue

        submitted_by_display = 'N/A'
        if loan.assigned_agent:
            submitted_by_display = _agent_name_or_na(loan.assigned_agent)
        elif related_app and related_app.assigned_agent:
            submitted_by_display = _agent_name_or_na(related_app.assigned_agent)
        elif creator and creator.role == 'agent':
            submitted_by_display = _user_name_or_na(creator)
        elif related_app and related_app.assigned_by and related_app.assigned_by.role == 'agent':
            submitted_by_display = _user_name_or_na(related_app.assigned_by)
        if submitted_by_display == 'N/A' and lead_names.get('channel_partner'):
            submitted_by_display = lead_names['channel_partner']

        processed_by_display = 'N/A'
        if loan.assigned_employee:
            processed_by_display = _user_name_or_na(loan.assigned_employee)
        elif related_app and related_app.assigned_employee:
            processed_by_display = _user_name_or_na(related_app.assigned_employee)
        elif creator and creator.role == 'employee':
            processed_by_display = _user_name_or_na(creator)
        if processed_by_display == 'N/A' and lead_names.get('employee'):
            processed_by_display = lead_names['employee']

        partner_under_display = 'N/A'
        if partner_user:
            partner_under_display = _user_name_or_na(partner_user)
        elif assignment_context.get('role') == 'subadmin':
            partner_under_display = assignment_context.get('assigned_by_name') or 'N/A'
        elif loan.assigned_agent and loan.assigned_agent.created_by and loan.assigned_agent.created_by.role == 'subadmin':
            partner_under_display = _user_name_or_na(loan.assigned_agent.created_by)
        elif related_app and related_app.assigned_by and related_app.assigned_by.role == 'subadmin':
            partner_under_display = _user_name_or_na(related_app.assigned_by)
        elif creator and creator.role == 'subadmin':
            partner_under_display = _user_name_or_na(creator)
        if partner_under_display == 'N/A' and lead_names.get('leader'):
            partner_under_display = lead_names['leader']
        loan.submitted_by_display = submitted_by_display
        loan.processed_by_display = processed_by_display
        loan.partner_under_display = partner_under_display
        loan.partner_under_id = getattr(partner_user, 'id', '') or ''
        loan.follow_up_pending = follow_up_pending
        loan.status_key_display = effective_status_key or loan.status
        loan.status_display_text = _status_key_to_display_text(effective_status_key, fallback_text=loan.get_status_display())
        loan.assigned_by_display = assignment_context.get('assigned_by_display') or 'N/A'
        loan.entity_type = 'legacy'
        loan.applicant_photo_url = legacy_photo_by_loan_id.get(loan.id) or (
            app_photo_by_app_id.get(related_app.id) if related_app else ''
        )
        enriched_loans.append(loan)

    def _app_matches_filters(app_obj, status_key):
        applicant = getattr(app_obj, 'applicant', None)
        if search_query:
            haystack = ' '.join([
                str(getattr(applicant, 'full_name', '') or ''),
                str(getattr(applicant, 'mobile', '') or ''),
                str(getattr(applicant, 'email', '') or ''),
                str(display_loan_id(legacy_loan=find_related_loan(app_obj), loan_application=app_obj)),
            ]).lower()
            if search_query.lower() not in haystack:
                return False
        if status_filter and status_key != status_filter:
            return False
        if agent_filter and str(getattr(app_obj, 'assigned_agent_id', '') or '') != agent_filter:
            return False
        if employee_filter and str(getattr(app_obj, 'assigned_employee_id', '') or '') != employee_filter:
            return False
        if partner_filter:
            partner_user = _partner_user_for_application(app_obj)
            if str(getattr(partner_user, 'id', '') or '') != partner_filter:
                return False
        if date_from and (not app_obj.created_at or app_obj.created_at.date().isoformat() < date_from):
            return False
        if date_to and (not app_obj.created_at or app_obj.created_at.date().isoformat() > date_to):
            return False
        return True

    workflow_rows = []
    for app_obj in apps:
        if app_obj.id in related_app_ids:
            continue
        status_key = application_effective_status_key(app_obj)
        if not _app_matches_filters(app_obj, status_key):
            continue
        workflow_row = build_application_display_row(app_obj, status_key=status_key)
        partner_user = _partner_user_for_application(app_obj)
        workflow_row.partner_under_id = getattr(partner_user, 'id', '') or ''
        workflow_row.applicant_photo_url = app_photo_by_app_id.get(app_obj.id, '')
        workflow_rows.append(workflow_row)

    enriched_loans.extend(workflow_rows)
    fallback_created_at = datetime.min.replace(tzinfo=datetime_timezone.utc)
    enriched_loans.sort(key=lambda item: getattr(item, 'created_at', None) or fallback_created_at, reverse=True)
    
    context = {
        'page_title': 'All Loans - Master Database',
        'loans': enriched_loans,
        'search_query': search_query,
        'status_filter': status_filter,
        'agent_filter': agent_filter,
        'employee_filter': employee_filter,
        'partner_filter': partner_filter,
        'date_from': date_from,
        'date_to': date_to,
        'per_page': per_page,
        'agents': Agent.objects.filter(status='active').order_by('name', 'agent_id'),
        'employees': User.objects.filter(role='employee', is_active=True).order_by('first_name', 'last_name', 'username'),
        'partners': User.objects.filter(role='subadmin', is_active=True).order_by('first_name', 'last_name', 'username'),
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
            'updated_document': status_counts['updated_document'],
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
                'loan_id': display_loan_id(legacy_loan=find_related_loan(loan), loan_application=loan),
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
@require_POST
def delete_loan(request, loan_id):
    """Delete a loan from admin/partner tables using POST + redirect."""
    if request.user.role not in ('admin', 'subadmin'):
        messages.error(request, 'Unauthorized access.')
        return redirect(request.META.get('HTTP_REFERER', 'admin_all_loans'))

    from .loan_helpers import delete_loan_by_primary_key

    entity_type = request.POST.get('entity_type') or request.POST.get('source') or ''
    result = delete_loan_by_primary_key(loan_id, entity_type=entity_type)
    referer = request.META.get('HTTP_REFERER')

    if result.get('success'):
        messages.success(request, result.get('message') or 'Loan deleted successfully.')
    else:
        messages.error(request, result.get('error') or 'Failed to delete loan.')

    if referer:
        return redirect(referer)
    if request.user.role == 'subadmin':
        return redirect('subadmin_all_loans')
    return redirect('admin_all_loans')


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_delete_loan(request, loan_id):
    """Delete a loan application and linked legacy loan when present."""
    try:
        from .loan_helpers import delete_loan_by_primary_key

        entity_type = request.POST.get('entity_type') or request.POST.get('source') or ''
        if not entity_type and request.body:
            try:
                payload = json.loads(request.body.decode('utf-8') or '{}')
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {}
            if isinstance(payload, dict):
                entity_type = payload.get('entity_type') or payload.get('source') or ''

        result = delete_loan_by_primary_key(loan_id, entity_type=entity_type)
        status_code = result.get('status_code', 200 if result.get('success') else 400)
        if result.get('success'):
            logger.info(f"Loan {loan_id} deleted by {request.user.username}")
            return JsonResponse({
                'success': True,
                'message': result.get('message') or 'Loan deleted successfully.',
            }, status=status_code)
        return JsonResponse({
            'success': False,
            'error': result.get('error') or 'Failed to delete loan.',
        }, status=status_code)
    except Exception as e:
        logger.error(f"Error deleting loan: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
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
        agent_filter = _normalize_filter_id(request.GET.get('agent', '').strip())
        employee_filter = _normalize_filter_id(request.GET.get('employee', '').strip())
        partner_filter = _normalize_filter_id(request.GET.get('partner', '').strip())
        date_from = request.GET.get('date_from', '').strip()
        date_to = request.GET.get('date_to', '').strip()
        
        query = Loan.objects.all().select_related(
            'created_by',
            'assigned_employee',
            'assigned_agent',
            'assigned_agent__user',
            'assigned_agent__created_by',
        )
        
        # Coarse filter by status (final status decision is computed using related workflow record)
        if status_filter == 'follow_up_pending':
            query = query.filter(status__in=['new_entry', 'waiting', 'follow_up'])
        elif status_filter in ['new_entry', 'waiting', UPDATED_DOCUMENT_STATUS_KEY, 'follow_up']:
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

        if agent_filter:
            query = query.filter(assigned_agent_id=agent_filter)
        if employee_filter:
            query = query.filter(assigned_employee_id=employee_filter)
        if date_from:
            query = query.filter(created_at__date__gte=date_from)
        if date_to:
            query = query.filter(created_at__date__lte=date_to)
        
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
            assignment_context = extract_assignment_context(loan, related_app)
            partner_user = _partner_user_for_loan(loan, related_app=related_app, assignment_context=assignment_context)
            lead_names = _lead_receive_names_from_remarks(getattr(loan, 'remarks', ''))
            if partner_filter and str(getattr(partner_user, 'id', '') or '') != partner_filter:
                continue
            submitted_by = '-'
            if loan.assigned_agent:
                submitted_by = (
                    loan.assigned_agent.name
                    or (loan.assigned_agent.user.get_full_name() if loan.assigned_agent.user else '')
                    or '-'
                )
            elif loan.created_by and loan.created_by.role == 'agent':
                submitted_by = loan.created_by.get_full_name() or loan.created_by.username or '-'
            if submitted_by == '-' and lead_names.get('channel_partner'):
                submitted_by = lead_names['channel_partner']
            processed_by = (
                loan.assigned_employee.get_full_name() or loan.assigned_employee.username
                if loan.assigned_employee else '-'
            )
            if processed_by == '-' and lead_names.get('employee'):
                processed_by = lead_names['employee']
            partner_under = '-'
            if partner_user:
                partner_under = partner_user.get_full_name() or partner_user.username or '-'
            elif assignment_context.get('role') == 'subadmin':
                partner_under = assignment_context.get('assigned_by_name') or '-'
            elif loan.assigned_agent and loan.assigned_agent.created_by and loan.assigned_agent.created_by.role == 'subadmin':
                partner_under = (
                    loan.assigned_agent.created_by.get_full_name()
                    or loan.assigned_agent.created_by.username
                    or '-'
                )
            if partner_under == '-' and lead_names.get('leader'):
                partner_under = lead_names['leader']
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
                'submitted_by': submitted_by,
                'processed_by': processed_by,
                'partner_under': partner_under,
                'partner_id': getattr(partner_user, 'id', '') or '',
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


def _build_subadmin_management_context(request, page_mode='list'):
    """Shared context for partner add/list pages."""
    from .subadmin_views import _subadmin_managed_agents_qs, _subadmin_managed_employees_qs, _subadmin_scoped_loans_qs

    subadmins = User.objects.filter(role='subadmin').order_by('-date_joined')
    subadmin_list = []
    for subadmin in subadmins:
        managed_agents_count = _subadmin_managed_agents_qs(subadmin).count()
        managed_employees_count = _subadmin_managed_employees_qs(subadmin).count()
        loans_qs = _subadmin_scoped_loans_qs(subadmin)
        total_applications = loans_qs.count()
        running_applications = loans_qs.exclude(status__in=['approved', 'rejected', 'disbursed']).count()
        entries_count = SubAdminEntry.objects.filter(subadmin=subadmin).count()
        subadmin.total_agents = managed_agents_count
        subadmin.total_employees = managed_employees_count
        subadmin.total_applications = total_applications
        subadmin.running_applications = running_applications
        subadmin.total_entries = entries_count
        subadmin.partner_id = subadmin.employee_id or f'EDC-P-{subadmin.id:04d}'
        subadmin_list.append({
            'id': subadmin.id,
            'name': subadmin.get_full_name(),
            'partner_id': subadmin.partner_id,
            'email': subadmin.email,
            'username': subadmin.username,
            'phone': subadmin.phone or '-',
            'address': subadmin.address or '-',
            'joined_on': subadmin.date_joined.strftime('%Y-%m-%d') if subadmin.date_joined else '-',
            'total_agents': managed_agents_count,
            'total_employees': managed_employees_count,
            'total_applications': total_applications,
            'running_applications': running_applications,
            'total_entries': entries_count,
            'is_active': subadmin.is_active,
            'date_joined': subadmin.date_joined,
            'photo_url': subadmin.profile_photo.url if subadmin.profile_photo else '',
        })

    titles = {
        'add': 'Add Partner',
        'list': 'All Partners',
    }
    employee_options = User.objects.filter(role='employee', is_active=True).order_by('first_name', 'last_name', 'username')
    channel_partner_options = Agent.objects.filter(status='active').order_by('agent_id', 'name', 'id')
    return {
        'page_title': titles.get(page_mode, 'Partner Management'),
        'page_mode': page_mode,
        'subadmins': subadmins,
        'subadmin_count': subadmins.count(),
        'subadmin_rows': subadmin_list,
        'employee_options': employee_options,
        'channel_partner_options': channel_partner_options,
    }


@login_required(login_url='admin_login')
@admin_required
def admin_subadmin_management(request):
    """Legacy URL — all partners list."""
    return admin_partners_list(request)


@login_required(login_url='admin_login')
@admin_required
def admin_partners_add(request):
    """Render add partner page directly."""
    context = _build_subadmin_management_context(request, page_mode='add')
    return render(request, 'core/admin/subadmin_management_new.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_partners_list(request):
    """All partners table."""
    try:
        context = _build_subadmin_management_context(request, page_mode='list')
        return render(request, 'core/admin/subadmin_management_new.html', context)
    except Exception as e:
        logger.error(f"Error loading partners list: {str(e)}")
        return render(request, 'core/admin/subadmin_management_new.html', {'error': str(e), 'page_mode': 'list'})


@login_required(login_url='admin_login')
@admin_required
def admin_partner_detail(request, subadmin_id):
    """Dedicated detail page for a Partner."""
    partner = get_object_or_404(User, id=subadmin_id, role='subadmin')
    return render(request, 'core/admin/partner_detail.html', {'partner': partner})


@login_required(login_url='admin_login')
@admin_required
def admin_employee_full_details(request, employee_id):
    """Dedicated detail page for an Employee."""
    employee = get_object_or_404(User, id=employee_id, role='employee')
    return render(request, 'core/admin/employee_full_details.html', {'employee': employee})


@login_required(login_url='admin_login')
@admin_required
def admin_channel_partner_full_details(request, agent_id):
    """Dedicated detail page for a Channel Partner."""
    agent = get_object_or_404(Agent, id=agent_id)
    return render(request, 'core/admin/channel_partner_detail.html', {'agent': agent})


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_subadmin_full_details(request, subadmin_id):
    """Return full performance + customer detail for a SubAdmin."""
    try:
        subadmin = get_object_or_404(User, id=subadmin_id, role='subadmin')
        from collections import defaultdict
        from .subadmin_views import (
            _extract_assignment_marker,
            _latest_bank_remark,
            _role_label,
            _serialize_subadmin_loan_details,
            _subadmin_managed_agents_qs,
            _subadmin_managed_employees_qs,
            _subadmin_scoped_loans_qs,
        )

        managed_agents_qs = _subadmin_managed_agents_qs(subadmin).select_related('user', 'under_employee', 'created_by')
        managed_employees_qs = _subadmin_managed_employees_qs(subadmin).order_by('first_name', 'last_name', 'username')
        loans_qs = _subadmin_scoped_loans_qs(subadmin).select_related(
            'assigned_employee', 'assigned_agent', 'created_by'
        ).order_by('-created_at')
        entries_qs = SubAdminEntry.objects.filter(subadmin=subadmin)

        customers = []
        employee_loan_counts = defaultdict(int)
        agent_loan_counts = defaultdict(int)

        for loan in loans_qs[:250]:
            serialized = _serialize_subadmin_loan_details(loan) or {}
            status_key = str(serialized.get('status') or loan.status or '').strip().lower()

            assigned_to = '-'
            if loan.assigned_employee:
                assigned_to = f"Employee - {loan.assigned_employee.get_full_name() or loan.assigned_employee.username}"
            elif loan.assigned_agent:
                assigned_to = f"Channel Partner - {loan.assigned_agent.name}"

            if loan.assigned_employee_id:
                employee_loan_counts[loan.assigned_employee_id] += 1
            if loan.assigned_agent_id:
                agent_loan_counts[loan.assigned_agent_id] += 1

            if loan.created_by:
                owner_name = f"{_role_label(loan.created_by)} - {loan.created_by.get_full_name() or loan.created_by.username}"
            else:
                owner_name = f"Partner - {subadmin.get_full_name() or subadmin.username}"

            customers.append({
                'loan_id': loan.id,
                'loan_uid': display_loan_id(legacy_loan=loan),
                'customer_name': loan.full_name or '-',
                'mobile': loan.mobile_number or '-',
                'email': loan.email or '-',
                'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else loan.loan_type,
                'loan_amount': float(loan.loan_amount or 0),
                'status': status_key or loan.status,
                'status_display': serialized.get('status_display') or _ui_status_label(loan.get_status_display()),
                'assigned_to': assigned_to,
                'assigned_by': serialized.get('assigned_by') or _extract_assignment_marker(loan),
                'owner_name': owner_name,
                'bank_remark': serialized.get('bank_remark') or _latest_bank_remark(loan),
                'created_at': serialized.get('created_at') or (loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else ''),
                'updated_at': serialized.get('updated_at') or (loan.updated_at.strftime('%Y-%m-%d %H:%M') if loan.updated_at else ''),
                'assigned_at': loan.assigned_at.strftime('%Y-%m-%d %H:%M') if loan.assigned_at else '-',
                'action_taken_at': loan.action_taken_at.strftime('%Y-%m-%d %H:%M') if loan.action_taken_at else '-',
                'follow_up_triggered_at': loan.follow_up_triggered_at.strftime('%Y-%m-%d %H:%M') if loan.follow_up_triggered_at else '-',
                'remarks': serialized.get('remarks') or (loan.remarks or '-'),
                'remarks_lines': serialized.get('remarks_lines') or [],
                'documents': serialized.get('documents') or [],
                'status_timeline': serialized.get('status_timeline') or [],
                'full_application_details': serialized.get('full_application_details') or [],
                'loan_purpose': serialized.get('loan_purpose') or (loan.loan_purpose or '-'),
                'tenure_months': serialized.get('tenure_months') or (loan.tenure_months or '-'),
                'interest_rate': serialized.get('interest_rate') if serialized.get('interest_rate') is not None else (float(loan.interest_rate) if loan.interest_rate is not None else '-'),
                'emi': serialized.get('emi') if serialized.get('emi') is not None else (float(loan.emi) if loan.emi is not None else '-'),
                'bank_name': serialized.get('bank_name') or (loan.bank_name or '-'),
                'bank_account_number': serialized.get('bank_account_number') or (loan.bank_account_number or '-'),
                'bank_ifsc_code': serialized.get('bank_ifsc_code') or (loan.bank_ifsc_code or '-'),
                'bank_type': serialized.get('bank_type') or (loan.bank_type or '-'),
                'sm_name': serialized.get('sm_name') or (loan.sm_name or '-'),
                'sm_phone_number': serialized.get('sm_phone_number') or (loan.sm_phone_number or '-'),
                'sm_email': serialized.get('sm_email') or (loan.sm_email or '-'),
                'assigned_employee_id': loan.assigned_employee_id,
                'assigned_agent_id': loan.assigned_agent_id,
            })

        managed_employees = []
        for employee in managed_employees_qs:
            linked_agents_qs = Agent.objects.filter(
                Q(created_by=subadmin),
                Q(under_employee=employee) | Q(employee_assignments__employee=employee)
            ).distinct()
            managed_employees.append({
                'id': employee.id,
                'employee_id': employee.employee_id or f'EDC-EMP-{employee.id:04d}',
                'name': employee.get_full_name() or employee.username or '-',
                'email': employee.email or 'N/A',
                'phone': employee.phone or 'N/A',
                'photo_url': employee.profile_photo.url if employee.profile_photo else '',
                'status': 'Active' if employee.is_active else 'Inactive',
                'channel_partner_count': linked_agents_qs.count(),
                'application_count': employee_loan_counts.get(employee.id, 0),
            })

        managed_agents = []
        for agent in managed_agents_qs.order_by('name', 'id'):
            managed_agents.append({
                'id': agent.id,
                'agent_id': agent.agent_id or f'EDC-CP-{agent.id:04d}',
                'name': agent.name or (agent.user.get_full_name() if agent.user else '-') or '-',
                'email': agent.email or 'N/A',
                'phone': agent.phone or 'N/A',
                'photo_url': agent.profile_photo.url if agent.profile_photo else (
                    agent.user.profile_photo.url if agent.user and agent.user.profile_photo else ''
                ),
                'status': str(agent.status or 'active').title(),
                'under_employee': (
                    agent.under_employee.get_full_name() or agent.under_employee.username
                    if agent.under_employee else 'N/A'
                ),
                'application_count': agent_loan_counts.get(agent.id, 0),
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
        if hasattr(subadmin, 'onboarding_profile') and subadmin.onboarding_profile:
            onboarding = subadmin.onboarding_profile.data or {}
        documents = collect_user_document_payload(subadmin)

        section1 = onboarding.get('section1') if isinstance(onboarding, dict) else {}
        perm = (section1 or {}).get('permanent_address') or {}
        section6 = onboarding.get('section6') if isinstance(onboarding, dict) else {}

        return JsonResponse({
            'success': True,
            'subadmin': {
                'id': subadmin.id,
                'partner_id': subadmin.employee_id or f'EDC-P-{subadmin.id:04d}',
                'name': subadmin.get_full_name() or subadmin.username,
                'username': subadmin.username,
                'email': subadmin.email or '-',
                'phone': subadmin.phone or '-',
                'address': subadmin.address or '-',
                'photo_url': subadmin.profile_photo.url if subadmin.profile_photo else '',
                'joined_on': subadmin.date_joined.strftime('%Y-%m-%d') if subadmin.date_joined else '-',
                'status': 'Active' if subadmin.is_active else 'Inactive',
                'city': str(perm.get('city') or '').strip(),
                'district': str(perm.get('district') or '').strip(),
                'state': str(perm.get('state') or '').strip(),
                'pin_code': str(perm.get('pin_code') or '').strip(),
                'aadhar_number': str((section6 or {}).get('aadhar_number') or '').strip(),
            },
            'summary': summary,
            'customers': customers,
            'managed_employees': managed_employees,
            'managed_agents': managed_agents,
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
        city = (data.get('city') or '').strip() or (data.get('onb_perm_city') or '').strip()
        district = (data.get('district') or '').strip() or (data.get('onb_perm_district') or '').strip()
        pin = (data.get('pin') or '').strip() or (data.get('pin_code') or '').strip() or (data.get('onb_perm_pin') or '').strip()
        state = (data.get('state') or '').strip() or (data.get('onb_perm_state') or '').strip()
        gender = (data.get('gender') or '').strip()
        dob = (data.get('onb_dob') or data.get('date_of_birth') or '').strip()
        photo_base64 = data.get('photo', '') if isinstance(data, dict) else ''
        photo_file = request.FILES.get('photo') if not is_json else None
        if not is_json:
            employee_ids_raw = request.POST.getlist('employee_ids')
            channel_partner_ids_raw = request.POST.getlist('channel_partner_ids')
        else:
            raw_employee_ids = data.get('employee_ids') if isinstance(data, dict) else []
            raw_channel_partner_ids = data.get('channel_partner_ids') if isinstance(data, dict) else []
            employee_ids_raw = raw_employee_ids if isinstance(raw_employee_ids, list) else []
            channel_partner_ids_raw = raw_channel_partner_ids if isinstance(raw_channel_partner_ids, list) else []
        employee_ids = _parse_int_list(employee_ids_raw)
        channel_partner_ids = _parse_int_list(channel_partner_ids_raw)

        if not name:
            name = f"{first_name} {last_name}".strip()
        if not username and email:
            username = email.split('@')[0]
        
        # Validation
        if not all([username, email, password, name, phone, city, district, pin]):
            return JsonResponse({
                'success': False,
                'error': 'Name, Email, Username, Phone, City, District, PIN Code, and Password are required'
            }, status=400)

        phone_digits = phone.replace('+', '')
        if not phone_digits.isdigit() or len(phone_digits) < 10 or len(phone_digits) > 15:
            return JsonResponse({
                'success': False,
                'error': 'Phone number must be 10-15 digits'
            }, status=400)

        if not pin.isdigit() or len(pin) != 6:
            return JsonResponse({
                'success': False,
                'error': 'PIN code must be 6 digits'
            }, status=400)
        
        # Check if username exists
        if User.objects.filter(username=username).exists():
            return JsonResponse({
                'success': False,
                'error': 'Username already exists'
            }, status=400)
        
        # Deleted/inactive partners do not reserve contact details.
        if User.objects.filter(email__iexact=email, is_active=True).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already exists for an active partner'
            }, status=400)

        if User.objects.filter(phone=phone, is_active=True).exists():
            return JsonResponse({
                'success': False,
                'error': 'Phone already exists for an active partner'
            }, status=400)
        
        # Create SubAdmin user
        partner_unique_id = generate_user_sequence_id('subadmin')
        subadmin = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=name.split()[0] if name else '',
            last_name=' '.join(name.split()[1:]) if len(name.split()) > 1 else '',
            role='subadmin',
            phone=phone,
            address=address,
            employee_id=partner_unique_id,
            gender=gender or None,
        )
        if dob:
            subadmin.date_of_birth = dob
        
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

        email_sent, email_detail = send_account_credentials_email(
            request=request,
            email=subadmin.email,
            full_name=subadmin.get_full_name() or subadmin.username,
            username=subadmin.username,
            password=password,
            role=subadmin.role,
            account_id=subadmin.employee_id or partner_unique_id,
        )

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

        assigned_employee_count = 0
        if employee_ids:
            assigned_employee_count = _sync_partner_employees(subadmin, employee_ids)
        assigned_channel_partner_count = 0
        if channel_partner_ids:
            assigned_channel_partner_count = _sync_partner_channel_partners(
                subadmin,
                channel_partner_ids,
                fallback_owner=request.user,
            )
        
        return JsonResponse({
            'success': True,
            'message': 'Partner created successfully',
            'email_sent': email_sent,
            'email_message': email_detail,
            'subadmin': {
                'id': subadmin.id,
                'partner_id': subadmin.employee_id or f'EDC-P-{subadmin.id:04d}',
                'username': subadmin.username,
                'email': subadmin.email,
                'name': subadmin.get_full_name() or subadmin.username,
                'phone': getattr(subadmin, 'phone', ''),
                'address': getattr(subadmin, 'address', ''),
                'is_active': subadmin.is_active,
                'date_joined': subadmin.date_joined.strftime('%Y-%m-%d') if subadmin.date_joined else '',
                'photo_url': subadmin.profile_photo.url if subadmin.profile_photo else '',
                'total_agents': assigned_channel_partner_count,
                'total_employees': assigned_employee_count,
                'total_applications': 0,
                'running_applications': 0,
                'total_entries': 0,
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
        subadmins = User.objects.filter(role='subadmin', is_active=True).values(
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone', 'address', 'created_at', 'employee_id'
        )
        
        subadmin_list = []
        for sub in subadmins:
            subadmin_list.append({
                'id': sub['id'],
                'username': sub['username'],
                'email': sub['email'],
                'name': f"{sub['first_name']} {sub['last_name']}".strip() or sub['username'],
                'partner_id': sub['employee_id'] or f"EDC-P-{sub['id']:04d}",
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
    is_json = bool(request.content_type and 'application/json' in request.content_type)
    if is_json:
        try:
            data = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON payload'}, status=400)
    else:
        data = request.POST

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
    if User.objects.filter(email__iexact=email, is_active=True).exclude(id=subadmin.id).exists():
        return JsonResponse({'success': False, 'error': 'Email already exists for an active partner'}, status=400)
    if User.objects.filter(phone=phone, is_active=True).exclude(id=subadmin.id).exists():
        return JsonResponse({'success': False, 'error': 'Phone already exists for an active partner'}, status=400)

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

    profile_photo = request.FILES.get('profile_photo') or request.FILES.get('photo')
    if profile_photo:
        if profile_photo.size > 5 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'Profile photo must be less than 5MB'}, status=400)
        subadmin.profile_photo = profile_photo

    subadmin.save()

    employee_ids = None
    channel_partner_ids = None
    if is_json:
        if isinstance(data, dict) and 'employee_ids' in data:
            raw_employee_ids = data.get('employee_ids')
            employee_ids = _parse_int_list(raw_employee_ids if isinstance(raw_employee_ids, list) else [])
        if isinstance(data, dict) and 'channel_partner_ids' in data:
            raw_channel_partner_ids = data.get('channel_partner_ids')
            channel_partner_ids = _parse_int_list(raw_channel_partner_ids if isinstance(raw_channel_partner_ids, list) else [])
    else:
        if 'employee_ids' in request.POST:
            employee_ids = _parse_int_list(request.POST.getlist('employee_ids'))
        if 'channel_partner_ids' in request.POST:
            channel_partner_ids = _parse_int_list(request.POST.getlist('channel_partner_ids'))

    assigned_employee_count = None
    assigned_channel_partner_count = None
    if employee_ids is not None:
        assigned_employee_count = _sync_partner_employees(subadmin, employee_ids)
    if channel_partner_ids is not None:
        assigned_channel_partner_count = _sync_partner_channel_partners(
            subadmin,
            channel_partner_ids,
            fallback_owner=request.user,
        )

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
            'photo_url': subadmin.profile_photo.url if subadmin.profile_photo else '',
            'status': 'Active' if subadmin.is_active else 'Inactive',
            'total_employees': assigned_employee_count,
            'total_agents': assigned_channel_partner_count,
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
    context = {
        'page_title': 'Add New Agent/Employee',
    }

    if request.method == 'POST':
        try:
            full_name = request.POST.get('full_name', '').strip()
            first_name_raw = request.POST.get('first_name', '').strip()
            last_name_raw = request.POST.get('last_name', '').strip()
            if not full_name:
                full_name = " ".join([part for part in [first_name_raw, last_name_raw] if part]).strip()

            email = request.POST.get('email', '').strip()
            phone = request.POST.get('phone', '').strip()
            gender = request.POST.get('gender', '').strip()
            city = request.POST.get('city', '').strip() or request.POST.get('onb_perm_city', '').strip()
            district = request.POST.get('district', '').strip() or request.POST.get('onb_perm_district', '').strip()
            pin_code = request.POST.get('pin_code', '').strip() or request.POST.get('onb_perm_pin', '').strip()
            state = request.POST.get('state', '').strip() or request.POST.get('onb_perm_state', '').strip()
            address_input = request.POST.get('address', '').strip()
            password = request.POST.get('password', '').strip()
            role = request.POST.get('role', 'agent').strip().lower()  # agent, employee, subadmin
            photo = request.FILES.get('photo') or request.FILES.get('profile_photo')

            if role not in {'agent', 'employee', 'subadmin'}:
                role = 'agent'
            
            # Validate required fields
            if not all([full_name, email, phone, city, district, pin_code, password]):
                messages.error(request, 'Please fill all required fields')
                return render(request, 'core/admin/add_agent.html', context)
            
            # Validate email format
            if not email or '@' not in email:
                messages.error(request, 'Invalid email address')
                return render(request, 'core/admin/add_agent.html', context)
            
            # Deleted/inactive accounts do not reserve contact details.
            active_email_exists = User.objects.filter(email__iexact=email, is_active=True).exists()
            if role == 'agent':
                active_email_exists = active_email_exists or Agent.objects.filter(email__iexact=email, status='active').exists()
            if active_email_exists:
                messages.error(request, f'Email already exists for an active {role}')
                return render(request, 'core/admin/add_agent.html', context)

            active_phone_exists = User.objects.filter(phone=phone, is_active=True).exists()
            if role == 'agent':
                active_phone_exists = active_phone_exists or Agent.objects.filter(phone=phone, status='active').exists()
            if active_phone_exists:
                messages.error(request, f'Phone number already exists for an active {role}')
                return render(request, 'core/admin/add_agent.html', context)
            
            # Check phone format
            if not phone.isdigit() or len(phone) < 10 or len(phone) > 15:
                messages.error(request, 'Invalid phone number. Must be 10-15 digits')
                return render(request, 'core/admin/add_agent.html', context)

            if not pin_code.isdigit() or len(pin_code) != 6:
                messages.error(request, 'PIN code must be exactly 6 digits')
                return render(request, 'core/admin/add_agent.html', context)

            # Validate password length
            if len(password) < 6:
                messages.error(request, 'Password must be at least 6 characters')
                return render(request, 'core/admin/add_agent.html', context)

            name_parts = full_name.split(' ', 1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ''

            address = address_input or " | ".join([
                part for part in [
                    f"City: {city}" if city else '',
                    f"District: {district}" if district else '',
                    f"State: {state}" if state else '',
                    f"PIN: {pin_code}" if pin_code else '',
                ] if part
            ])
            
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
                address=address,
                employee_id=generate_user_sequence_id('employee') if role == 'employee' else (generate_user_sequence_id('subadmin') if role == 'subadmin' else None),
            )
            
            # Handle photo upload
            if photo:
                user.profile_photo = photo
                user.save()

            display_name = user.get_full_name() or user.username
            account_code = user.employee_id or ''
            
            # If role is agent, create Agent profile
            if role == 'agent':
                agent = Agent.objects.create(
                    user=user,
                    agent_id=generate_agent_sequence_id(is_sub_channel_partner=False),
                    name=display_name,
                    email=email,
                    phone=phone,
                    status='active',
                    gender=gender or None,
                    address=address,
                    city=city or None,
                    state=state or None,
                    pin_code=pin_code or None,
                    created_by=request.user,
                )
                account_code = agent.agent_id or ''
                if photo:
                    agent.profile_photo = photo
                    agent.save()
                success_msg = f'Agent {display_name} created successfully with username: {username}'
            
            # If role is subadmin, mark as subadmin
            elif role == 'subadmin':
                user.is_subadmin = True
                user.save(update_fields=['is_subadmin'])
                success_msg = f'Partner {display_name} created successfully with username: {username}'
            
            else:  # employee
                EmployeeProfile.objects.get_or_create(
                    user=user,
                    defaults={'employee_role': 'loan_processor'},
                )
                success_msg = f'Employee {display_name} created successfully with username: {username}'

            onboarding_payload = collect_onboarding_payload(request)
            creator_info = {
                'created_by_id': request.user.id,
                'created_by_name': request.user.get_full_name() or request.user.username or 'System',
                'created_by_role': role_label(request.user),
            }
            if isinstance(onboarding_payload, dict):
                onboarding_payload['_meta'] = creator_info
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

            email_sent, email_detail = send_account_credentials_email(
                request=request,
                email=user.email,
                full_name=display_name,
                username=user.username,
                password=password,
                role=user.role,
                account_id=account_code,
            )
            
            if email_sent:
                messages.success(request, f'{success_msg} Credentials email sent successfully.')
            else:
                messages.success(request, f'{success_msg} Credentials email could not be sent: {email_detail}')
            if role == 'agent':
                return redirect('admin_agents_list')
            if role == 'subadmin':
                return redirect('admin_partners_list')
            return redirect('admin_employees_list')
        
        except Exception as e:
            logger.error(f"Error creating agent: {str(e)}")
            messages.error(request, f'Error creating user: {str(e)}')
            return render(request, 'core/admin/add_agent.html', context)

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
        else ('employee_add_loan' if current_role == 'employee'
              else ('subadmin_add_loan' if current_role == 'subadmin' else 'agent_add_loan'))
    )

    if current_role not in ['admin', 'employee', 'subadmin', 'agent']:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    if request.method == 'POST':
        try:
            applicant_name = (request.POST.get('name') or request.POST.get('applicant_name') or '').strip()
            applicant_email = (request.POST.get('email_id') or request.POST.get('applicant_email') or '').strip()
            applicant_mobile = (request.POST.get('mobile_no') or request.POST.get('applicant_mobile') or '').strip()
            loan_uid = normalize_manual_loan_id(request.POST.get('loan_uid'))
            raw_loan_type = (request.POST.get('service_required') or request.POST.get('loan_type') or '').strip()
            raw_amount = (request.POST.get('loan_amount_required') or request.POST.get('loan_amount') or '').strip()
            raw_tenure = (request.POST.get('loan_tenure') or request.POST.get('tenure_months') or '').strip()

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

            permanent_city = (request.POST.get('permanent_city') or '').strip()
            present_city = (request.POST.get('present_city') or '').strip()
            city = permanent_city or present_city
            state = (request.POST.get('permanent_state') or request.POST.get('state') or '').strip()
            pin_code = (request.POST.get('permanent_pin') or request.POST.get('present_pin') or '').strip()
            lead_receive_defaults = _lead_receive_defaults_for_user(request.user)
            lead_receive_options = get_lead_receive_options(request.user)
            lead_received_by_id = (request.POST.get('lead_received_by') or '').strip()
            if request.user.role == 'agent' and not lead_received_by_id and lead_receive_options:
                lead_received_by_id = str(lead_receive_options[0]['id'])
            resolved_leader_name = resolve_lead_receive_name(
                lead_received_by_id,
                request.POST.get('lead_receive_leader_name')
                or lead_receive_defaults.get('lead_receive_leader_name', ''),
            )

            removed_add_loan_fields = {
                'pan_number',
                'aadhar_number',
                'occupation',
                'company_name',
                'designation',
                'other_applicant_information',
                'bank_name',
                'product_selection',
                'interest_rate',
                'lead_receive_employee_name',
                'cibil_score',
                'charges_or_fee',
                'other_loan_fields',
            }

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
                'business_name': 'Business Name',
                'lead_receive_channel_partner_name': 'Channel Partner Name',
                'lead_receive_leader_name': 'Leader Name',
                'lead_receive_source': 'Lead Source',
                'lead_receive_description': 'Lead Description',
                'remarks_suggestions': 'Remarks/Suggestions',
                'documents_available': 'Documents Available',
                'declaration': 'Declaration',
            }
            remarks_lines = []
            for field_name, label in remarks_field_map.items():
                if field_name in removed_add_loan_fields:
                    continue
                if field_name == 'lead_receive_leader_name':
                    value = resolved_leader_name
                else:
                    value = (
                        request.POST.get(field_name)
                        or lead_receive_defaults.get(field_name)
                        or ''
                    ).strip()
                if value:
                    remarks_lines.append(f"{label}: {value}")

            handled_fields = set(remarks_field_map.keys())
            skip_fields = removed_add_loan_fields | {
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
                interest_rate=None,
                loan_purpose=(request.POST.get('loan_purpose') or request.POST.get('remarks_suggestions') or '').strip() or None,
                business_name=(request.POST.get('business_name') or '').strip() or None,
                bank_name=None,
                bank_account_number=(request.POST.get('account_number') or '').strip() or None,
                bank_ifsc_code=(request.POST.get('ifsc_code') or '').strip() or None,
                status='new_entry',
                applicant_type='agent' if request.user.role == 'agent' else 'employee',
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
            is_valid_upload, upload_error = validate_loan_document_batch(documents_files)
            if not is_valid_upload:
                messages.error(request, upload_error)
                return redirect(self_add_loan_route)
            document_name_sequence = expanded_document_names if len(expanded_document_names) >= len(documents_files) else document_names
            password_expanded = request.POST.getlist('document_password_expanded[]')
            password_values = request.POST.getlist('document_password[]')
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

                doc_password = None
                flag_index = idx - 1
                if flag_index < len(password_expanded):
                    raw_password = (password_expanded[flag_index] or '').strip()
                    if raw_password:
                        doc_password = raw_password
                if doc_password is None and flag_index < len(password_values):
                    raw_password = (password_values[flag_index] or '').strip()
                    if raw_password:
                        doc_password = raw_password

                LoanDocument.objects.create(
                    loan=loan,
                    document_type=document_type[:50],
                    file=uploaded_file,
                    is_required=False,
                    document_password=doc_password,
                )

            from .loan_helpers import mirror_legacy_documents_to_application
            from .loan_sync import find_related_loan_application

            mirror_legacy_documents_to_application(loan)
            related_app = find_related_loan_application(loan)
            if related_app and lead_received_by_id:
                try:
                    receiver = User.objects.filter(id=int(lead_received_by_id), is_active=True).first()
                except (TypeError, ValueError):
                    receiver = None
                if receiver:
                    related_app.lead_received_by = receiver
                    related_app.save(update_fields=['lead_received_by'])

            manual_label = display_manual_loan_id(loan)

            ActivityLog.objects.create(
                action='loan_added',
                description=f"Loan application created for '{loan.full_name}' (Manual Loan ID {manual_label})",
                user=request.user,
                related_loan=loan,
            )

            if loan.user_id:
                messages.success(request, f'Loan application submitted successfully. Manual Loan ID: {loan.user_id}')
            else:
                messages.success(request, 'Loan application submitted successfully. Assign the Manual Loan ID during processing.')
            if request.user.role == 'admin':
                return redirect('admin_all_loans')
            if request.user.role == 'subadmin':
                return redirect('subadmin_all_loans')
            if request.user.role == 'agent':
                return redirect('agent_my_applications')
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
    lead_receive_defaults = _lead_receive_defaults_for_user(request.user)
    lead_receive_options = get_lead_receive_options(request.user)
    auto_lead_received_by_id = str(lead_receive_options[0]['id']) if lead_receive_options else ''

    context = {
        'page_title': 'Add New Loan Application',
        'recent_loans': recent_loans,
        'base_template': 'subadmin/base_subadmin.html' if request.user.role == 'subadmin' else 'core/base.html',
        'lead_receive_channel_partner_default': lead_receive_defaults.get('lead_receive_channel_partner_name', ''),
        'lead_receive_employee_default': lead_receive_defaults.get('lead_receive_employee_name', ''),
        'lead_receive_leader_default': lead_receive_defaults.get('lead_receive_leader_name', ''),
        'lead_receive_options': lead_receive_options,
        'auto_lead_received_by_id': auto_lead_received_by_id,
    }
    template_map = {
        'admin': 'core/admin/add_loan.html',
        'employee': 'core/employee/add_loan.html',
        'subadmin': 'core/employee/add_loan.html',
        'agent': 'core/employee/add_loan.html',
    }
    template_name = template_map.get(request.user.role, 'core/admin/add_loan.html')
    return render(request, template_name, context)


@login_required(login_url='admin_login')
@admin_required
def admin_join_requests(request):
    """
    Admin Join Requests - Shows pending requests from users wanting to join as SubAdmins/Agents
    """
    try:
        pending_count = LoanApplication.objects.filter(
            _join_registration_filter(),
            status='New Entry',
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
            _join_registration_filter(),
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
        ).prefetch_related('documents').get(
            _join_registration_filter(),
            id=application_id,
        )
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
        ).get(
            _join_registration_filter(),
            id=application_id,
        )
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
            email_sent, email_detail = send_account_credentials_email(
                request=request,
                email=user.email,
                full_name=user.get_full_name() or user.username,
                username=user.username,
                password=temp_password,
                role=user.role,
                account_id=getattr(user, 'employee_id', '') or (user.agent_profile.agent_id if hasattr(user, 'agent_profile') else ''),
            )
            response['email_sent'] = email_sent
            response['email_message'] = email_detail
        return JsonResponse(response)
    except Exception as exc:
        logger.error(f"Error performing join request action {action} on {application_id}: {str(exc)}")
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@login_required(login_url='admin_login')
@admin_required
def admin_new_entries(request):
    """View New Entry applications"""
    applications = LoanApplication.objects.filter(status='New Entry').exclude(
        _join_registration_filter()
    ).select_related('applicant', 'assigned_employee', 'assigned_agent', 'assigned_by').order_by('-created_at')
    
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
    applications = [
        app for app in LoanApplication.objects.filter(status='Waiting for Processing').select_related('applicant', 'assigned_employee', 'assigned_agent', 'assigned_by').order_by('-created_at')
        if not loan_has_updated_documents(find_related_loan(app), related_app=app)
    ]
    
    context = {
        'page_title': 'Document Pending Applications',
        'applications': applications,
        'status_name': 'Waiting for Processing',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_updated_document(request):
    """View Updated Document applications"""
    applications = [
        app for app in LoanApplication.objects.filter(status='Waiting for Processing').select_related('applicant', 'assigned_employee', 'assigned_agent', 'assigned_by').order_by('-created_at')
        if loan_has_updated_documents(find_related_loan(app), related_app=app)
    ]

    context = {
        'page_title': 'Updated Document Applications',
        'applications': applications,
        'status_name': UPDATED_DOCUMENT_LABEL,
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_follow_ups(request):
    """View Bank Login Process applications"""
    applications = LoanApplication.objects.filter(status='Required Follow-up').select_related('applicant', 'assigned_employee', 'assigned_agent', 'assigned_by').order_by('-created_at')
    
    context = {
        'page_title': 'Bank Login Process Applications',
        'applications': applications,
        'status_name': 'Bank Login Process',
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
            documents = ApplicantDocument.objects.filter(loan_application=application)
            related_legacy = find_related_loan(application)
            if related_legacy:
                from .models import LoanDocument
                for loan_doc in LoanDocument.objects.filter(loan=related_legacy):
                    doc_password = (getattr(loan_doc, 'document_password', None) or '').strip()
                    data['documents'].append({
                        'name': loan_doc.get_document_type_display() if hasattr(loan_doc, 'get_document_type_display') else (loan_doc.document_type or 'Document'),
                        'url': loan_doc.file.url if loan_doc.file else '',
                        'uploaded': loan_doc.uploaded_at.strftime('%Y-%m-%d') if loan_doc.uploaded_at else '',
                        'document_password': doc_password,
                        'has_password': bool(doc_password),
                    })
            for doc in documents:
                doc_password = (getattr(doc, 'document_password', None) or '').strip()
                data['documents'].append({
                    'name': doc.document_type or 'Document',
                    'url': doc.file.url if doc.file else '',
                    'uploaded': doc.uploaded_at.strftime('%Y-%m-%d') if doc.uploaded_at else '',
                    'document_password': doc_password,
                    'has_password': bool(doc_password),
                })
        except:
            pass
        
        return JsonResponse(data)
    except LoanApplication.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Application not found'}, status=404)
