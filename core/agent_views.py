"""
Agent-specific views for role-based loan management dashboard
Includes: New Entries, Add Loans, Sub-Agents, Reports, Complaints
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Sum, Q
from django.utils import timezone
from django.urls import reverse
from datetime import datetime, timedelta
import csv
from openpyxl import Workbook

from .models import (
    Loan,
    LoanApplication,
    Agent,
    Complaint,
    User,
    LoanDocument,
    LoanStatusHistory,
    AgentAssignment,
    UserOnboardingDocument,
)
from .loan_sync import find_related_loan_application, sync_loan_to_application
from .followup_utils import auto_move_overdue_to_follow_up
from .role_decorators import agent_required
from .upload_limits import validate_loan_document_batch
from .updated_document_utils import (
    UPDATED_DOCUMENT_LABEL,
    UPDATED_DOCUMENT_STATUS_KEY,
    application_has_updated_documents,
    loan_has_updated_documents,
)
from .account_notifications import send_account_credentials_email
from .id_utils import generate_agent_sequence_id, normalize_manual_loan_id
from .workflow_rows import (
    application_effective_status_key,
    build_application_display_row,
)

APP_STATUS_TO_LOAN_KEY = {
    'New Entry': 'new_entry',
    'Waiting for Processing': 'waiting',
    'Required Follow-up': 'follow_up',
    'Approved': 'approved',
    'Rejected': 'rejected',
    'Disbursed': 'disbursed',
}


def get_agent_loan_queryset(user, agent):
    """
    Unified queryset for agent-owned data:
    - Loans created by this agent user
    - Loans currently assigned to this agent profile
    """
    return Loan.objects.filter(
        Q(created_by=user) | Q(assigned_agent=agent)
    ).distinct()


def _resolve_employee_for_agent(agent):
    """
    Resolve the employee responsible for this agent.
    Preference:
    1) Latest explicit AgentAssignment
    2) Agent created_by if it is an employee
    """
    assignment = (
        AgentAssignment.objects.filter(agent=agent)
        .select_related('employee')
        .order_by('-assigned_at')
        .first()
    )
    if assignment and assignment.employee and assignment.employee.role == 'employee':
        return assignment.employee
    created_by = agent.created_by
    if created_by and getattr(created_by, 'role', None) == 'employee':
        return created_by
    return None


def _append_note_line(existing_text, new_line):
    line = str(new_line or '').strip()
    if not line:
        return existing_text or ''
    existing = str(existing_text or '').strip()
    return f"{existing}\n{line}".strip() if existing else line


def _normalize_history_status(status_key):
    normalized = str(status_key or '').strip().lower()
    allowed = {'new_entry', 'waiting', 'follow_up', 'approved', 'rejected', 'disbursed'}
    return normalized if normalized in allowed else 'new_entry'


def _has_revert_marker(raw_text):
    return 'revert remark ' in str(raw_text or '').lower()


def _follow_up_pending_q():
    return Q(status__in=['new_entry', 'waiting']) & Q(remarks__icontains='Revert Remark ')


def _is_follow_up_pending(loan_obj):
    if not loan_obj:
        return False
    return loan_obj.status in ['new_entry', 'waiting'] and _has_revert_marker(loan_obj.remarks)


def _effective_status_key_for_loan(loan_obj):
    if not loan_obj:
        return ''
    if _is_follow_up_pending(loan_obj):
        return 'follow_up_pending'
    raw_status = str(getattr(loan_obj, 'status', '') or '').strip().lower()
    if raw_status == 'waiting' and loan_has_updated_documents(loan_obj):
        return UPDATED_DOCUMENT_STATUS_KEY
    return raw_status


def _status_breakdown(loans_iterable):
    counts = {
        'new_entry': 0,
        'waiting': 0,
        UPDATED_DOCUMENT_STATUS_KEY: 0,
        'follow_up': 0,
        'follow_up_pending': 0,
        'approved': 0,
        'rejected': 0,
        'disbursed': 0,
        'total': 0,
    }
    for loan_obj in loans_iterable:
        status_key = _effective_status_key_for_loan(loan_obj)
        if status_key in counts:
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


def _application_status_breakdown(apps_iterable):
    counts = {
        'new_entry': 0,
        'waiting': 0,
        UPDATED_DOCUMENT_STATUS_KEY: 0,
        'follow_up': 0,
        'follow_up_pending': 0,
        'approved': 0,
        'rejected': 0,
        'disbursed': 0,
        'total': 0,
    }
    for app_obj in apps_iterable:
        status_key = _effective_status_key_for_application(app_obj)
        if status_key in counts:
            counts[status_key] += 1
        counts['total'] += 1
    return counts


def _merge_status_counts(primary_counts, extra_counts):
    for key, value in extra_counts.items():
        primary_counts[key] = primary_counts.get(key, 0) + value
    return primary_counts


def _agent_workflow_only_applications(agent, legacy_loans):
    related_app_ids = {
        related_app.id
        for related_app in (find_related_loan_application(loan) for loan in legacy_loans)
        if related_app
    }
    filters = Q(assigned_agent=agent)
    if getattr(agent, 'user_id', None):
        filters |= Q(assigned_by_id=agent.user_id)
    return LoanApplication.objects.select_related(
        'applicant',
        'assigned_by',
        'assigned_employee',
        'assigned_agent',
        'assigned_agent__user',
        'assigned_agent__created_by',
    ).filter(filters).exclude(id__in=related_app_ids)


@agent_required
def agent_dashboard(request):
    """
    Main agent dashboard with real-time counts and status overview.
    Shows assigned loans, pending applications, and quick stats.
    """
    agent = Agent.objects.get(user=request.user)

    # Include both created and assigned loans for a reliable live dashboard view
    agent_loans_qs = get_agent_loan_queryset(request.user, agent)
    agent_loans = list(agent_loans_qs)
    counts = _status_breakdown(agent_loans)
    counts = _merge_status_counts(
        counts,
        _application_status_breakdown(_agent_workflow_only_applications(agent, agent_loans)),
    )

    # Real-time dashboard statistics
    dashboard_data = {
        'total_assigned': counts['total'],
        'processing': counts['new_entry'] + counts['waiting'] + counts[UPDATED_DOCUMENT_STATUS_KEY] + counts['follow_up'],
        'new_entry': counts['new_entry'],
        'waiting': counts['waiting'],
        'updated_document': counts[UPDATED_DOCUMENT_STATUS_KEY],
        'bank_stage': counts['follow_up'],
        'follow_up_pending': counts['follow_up_pending'],
        'approved': counts['approved'],
        'rejected': counts['rejected'],
        'disbursed': counts['disbursed'],
        'total_amount': agent_loans_qs.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
    }

    context = {
        'agent': agent,
        'dashboard': dashboard_data,
        'recent_loans': agent_loans_qs.order_by('-created_at')[:10],
    }
    return render(request, 'core/agent/dashboard.html', context)


@agent_required
def agent_new_entries(request):
    """
    Display new entries assigned by admin to this agent.
    Shows clean table format without forms (admin-assigned loans only).
    Real-time status updates.
    """
    agent = Agent.objects.get(user=request.user)
    
    # Get new entries assigned to this agent by admin
    new_entries = Loan.objects.filter(
        assigned_agent=agent,
        status='new_entry'
    ).order_by('-created_at')
    
    context = {
        'new_entries': new_entries,
        'total_new': new_entries.count(),
        'agent': agent,
    }
    return render(request, 'core/agent/new_entries.html', context)


@agent_required
@require_http_methods(["GET", "POST"])
def agent_add_loan(request):
    """
    Unified Add New Loan form for Channel Partner.
    Reuses the same real-time form/workflow used by admin/employee/subadmin.
    """
    from .admin_views import admin_add_loan
    return admin_add_loan(request)


@agent_required
@agent_required
def agent_sub_agents(request):
    """
    Allow agents to create and manage their sub-agents.
    Only agents created by this agent are shown.
    """
    agent = Agent.objects.get(user=request.user)
    
    # Get sub-agents created by this agent
    sub_agents = Agent.objects.filter(created_by=request.user).select_related('user').order_by('-created_at')
    
    context = {
        'sub_agents': sub_agents,
        'agent': agent,
        'total_sub_agents': sub_agents.count(),
    }
    return render(request, 'core/agent/sub_agents.html', context)


@agent_required
def agent_add_employee(request):
    """
    Form page to add a new sub-agent/team member
    """
    agent = Agent.objects.get(user=request.user)
    context = {
        'agent': agent,
        'page_title': 'Add New Team Member',
    }
    return render(request, 'core/agent/agent_add_employee.html', context)


@agent_required
@require_http_methods(["POST"])
def create_sub_agent(request):
    """
    Create a new sub-agent/team member under the current agent.
    Accepts FormData including photo upload
    """
    try:
        parent_agent = Agent.objects.get(user=request.user)
        
        # Get form data
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '').strip()
        gender = request.POST.get('gender', 'Other').strip()
        address = request.POST.get('address', '').strip()
        pin_code = request.POST.get('pin_code', '').strip()
        state = request.POST.get('state', '').strip()
        city = request.POST.get('city', '').strip()
        profile_photo = request.FILES.get('profile_photo', None)
        
        # Validation
        if not all([full_name, email, phone, password]):
            return JsonResponse({
                'success': False,
                'error': 'Full Name, Email, Phone, and Password are required'
            }, status=400)
        
        # Reuse contact details from deleted/blocked accounts, but block active duplicates.
        if (
            User.objects.filter(email__iexact=email, is_active=True).exists()
            or Agent.objects.filter(email__iexact=email, status='active').exists()
        ):
            return JsonResponse({
                'success': False,
                'error': 'Email already registered for an active channel partner'
            }, status=400)
        
        if (
            User.objects.filter(phone=phone, is_active=True).exists()
            or Agent.objects.filter(phone=phone, status='active').exists()
        ):
            return JsonResponse({
                'success': False,
                'error': 'Phone number already registered for an active channel partner'
            }, status=400)
        
        # Parse full name
        name_parts = full_name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        base_username = email.split('@')[0]
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            counter += 1
            username = f"{base_username}{counter}"

        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role='agent',
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            gender=gender,
            address=address,
        )
        
        # Handle photo upload
        if profile_photo:
            # Validate file size (5MB max)
            if profile_photo.size > 5 * 1024 * 1024:
                user.delete()
                return JsonResponse({
                    'success': False,
                    'error': 'Profile photo must be less than 5MB'
                }, status=400)
            
            user.profile_photo = profile_photo
            user.save()
        
        generated_agent_id = generate_agent_sequence_id(is_sub_channel_partner=True)

        # Create agent
        sub_agent = Agent.objects.create(
            user=user,
            agent_id=generated_agent_id,
            name=f"{first_name} {last_name}",
            phone=phone,
            email=email,
            address=address if address else None,
            city=city if city else None,
            state=state if state else None,
            pin_code=pin_code if pin_code else None,
            gender=gender if gender else None,
            created_by=request.user,
            under_employee=_resolve_employee_for_agent(parent_agent),
        )

        email_sent, email_detail = send_account_credentials_email(
            request=request,
            email=user.email,
            full_name=sub_agent.name,
            username=user.username,
            password=password,
            role=user.role,
            account_id=sub_agent.agent_id,
        )
        
        return JsonResponse({
            'success': True,
            'message': (
                f'Sub channel partner {sub_agent.name} ({generated_agent_id}) created successfully!'
                + (' Credentials email sent successfully.' if email_sent else (f' Credentials email could not be sent: {email_detail}' if email_detail else ''))
            ),
            'agent_id': sub_agent.id,
            'agent_code': generated_agent_id,
            'email_sent': email_sent,
            'email_message': email_detail,
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error: {str(e)}'
        }, status=500)


@agent_required
def agent_my_applications(request):
    """
    Show loans/applications created or managed by this agent.
    Shows all loans: approved, rejected, active, etc.
    """
    agent = Agent.objects.get(user=request.user)
    
    # Show both created and assigned applications
    all_loans_qs = get_agent_loan_queryset(request.user, agent).order_by('-created_at')
    all_loans = list(all_loans_qs)
    workflow_apps = list(_agent_workflow_only_applications(agent, all_loans))
    workflow_rows = [
        build_application_display_row(app_obj, status_key=application_effective_status_key(app_obj))
        for app_obj in workflow_apps
    ]

    def _prepare_legacy_row(loan_obj):
        status_key = _effective_status_key_for_loan(loan_obj)
        loan_obj.entity_type = 'legacy'
        loan_obj.status_raw = loan_obj.status
        loan_obj.status = status_key
        loan_obj.has_revert_pending = status_key == 'follow_up_pending'
        return loan_obj

    all_display_rows = [_prepare_legacy_row(loan) for loan in all_loans] + workflow_rows
    all_display_rows.sort(key=lambda row: getattr(getattr(row, 'created_at', None), 'timestamp', lambda: 0)(), reverse=True)
    
    # Filter by status if provided
    status_filter = request.GET.get('status')
    status_alias_map = {
        'waiting_for_processing': 'waiting',
        'processing': 'waiting',
        'bank': 'follow_up',
        'followup_pending': 'follow_up_pending',
        'updated': UPDATED_DOCUMENT_STATUS_KEY,
    }
    normalized_status = status_alias_map.get(status_filter, status_filter) if status_filter else None
    if normalized_status:
        loans = [loan for loan in all_display_rows if getattr(loan, 'status', '') == normalized_status]
    else:
        loans = list(all_display_rows)

    recent_submitted = list(all_display_rows[:10])

    # Get counts by status
    counts = _status_breakdown(all_loans)
    counts = _merge_status_counts(counts, _application_status_breakdown(workflow_apps))
    total_count = counts['total']
    follow_up_pending_count = counts['follow_up_pending']
    processing_count = counts['new_entry'] + counts['waiting'] + counts[UPDATED_DOCUMENT_STATUS_KEY] + counts['follow_up']
    approved_count = counts['approved']
    rejected_count = counts['rejected']
    disbursed_count = counts['disbursed']
    active_count = total_count - rejected_count - disbursed_count
    focus_loan_id = request.GET.get('loan_id', '').strip()
    
    context = {
        'loans': loans,
        'total_count': total_count,
        'processing_count': processing_count,
        'follow_up_pending_count': follow_up_pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'disbursed_count': disbursed_count,
        'active_count': active_count,
        'status_filter': normalized_status,
        'recent_submitted': recent_submitted,
        'focus_loan_id': focus_loan_id,
        'statuses': [
            ('draft', 'Draft'),
            ('new_entry', 'New Entry'),
            ('waiting', 'Processing'),
            (UPDATED_DOCUMENT_STATUS_KEY, UPDATED_DOCUMENT_LABEL),
            ('follow_up', 'Bank Stage'),
            ('follow_up_pending', 'Follow Up'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('disbursed', 'Disbursed'),
        ]
    }
    return render(request, 'core/agent/my_applications.html', context)


@agent_required
def agent_loan_detail(request, loan_id):
    """
    Render the interactive loan detail page (documents upload + pending/updated state).

    This uses the legacy Loan id in most agent flows, so the page relies on the
    `/api/employee/loan/<loan_id>/detail/` endpoint which can fall back to legacy
    records and return documents with access control for agents.
    """
    agent = Agent.objects.get(user=request.user)
    source = str(request.GET.get('entity_type') or request.GET.get('source') or '').strip().lower()

    from .employee_views_new import _loan_detail_layout_context
    from .loan_helpers import is_channel_partner

    layout_context = {
        'hide_banker_details': is_channel_partner(request.user),
        **_loan_detail_layout_context(request),
    }

    if source == 'application':
        app = get_object_or_404(
            LoanApplication.objects.filter(Q(assigned_agent=agent) | Q(assigned_by=request.user)),
            id=loan_id,
        )
        return render(request, 'core/employee/loan_detail.html', {
            'loan_id': app.id,
            'entity_type': 'application',
            **layout_context,
        })

    legacy_qs = get_agent_loan_queryset(request.user, agent)
    loan = legacy_qs.filter(id=loan_id).first()
    if loan:
        return render(request, 'core/employee/loan_detail.html', {
            'loan_id': loan.id,
            'entity_type': 'legacy',
            **layout_context,
        })

    app = get_object_or_404(
        LoanApplication.objects.filter(Q(assigned_agent=agent) | Q(assigned_by=request.user)),
        id=loan_id,
    )
    return render(request, 'core/employee/loan_detail.html', {
        'loan_id': app.id,
        'entity_type': 'application',
        **layout_context,
    })


@agent_required
@require_http_methods(["POST"])
def agent_forward_application(request):
    """
    Forward agent new application to next process with manual loan ID.
    """
    try:
        agent = Agent.objects.get(user=request.user)
        loan_id = str(request.POST.get('loan_id', '')).strip()
        manual_loan_id = normalize_manual_loan_id(request.POST.get('manual_loan_id'))
        next_stage = str(request.POST.get('next_stage', 'waiting')).strip().lower()

        if not loan_id or not manual_loan_id:
            return JsonResponse({'success': False, 'error': 'Loan ID and Manual Loan ID are required.'}, status=400)

        loan = get_object_or_404(get_agent_loan_queryset(request.user, agent), id=loan_id)

        if loan.status not in ['new_entry', 'draft', 'waiting']:
            return JsonResponse({'success': False, 'error': 'Forward is allowed only for New Application/Draft/Document Pending.'}, status=400)

        if Loan.objects.exclude(id=loan.id).filter(user_id__iexact=manual_loan_id).exists():
            return JsonResponse({'success': False, 'error': 'Manual Loan ID already exists.'}, status=400)

        target_status = 'follow_up' if next_stage == 'follow_up' else 'waiting'
        previous_status = loan.status
        loan.user_id = manual_loan_id
        loan.status = target_status
        loan.remarks = _append_note_line(loan.remarks, f"Forwarded by agent with Manual Loan ID: {manual_loan_id}")
        loan.save(update_fields=['user_id', 'status', 'remarks', 'updated_at'])

        try:
            LoanStatusHistory.objects.create(
                loan=loan,
                from_status=_normalize_history_status(previous_status),
                to_status=_normalize_history_status(target_status),
                changed_by=request.user,
                reason=f"Forwarded to {target_status} with Manual Loan ID {manual_loan_id}",
                is_auto_triggered=False,
            )
        except Exception:
            pass

        return JsonResponse({
            'success': True,
            'message': 'Application forwarded successfully.',
            'new_status': target_status,
            'manual_loan_id': manual_loan_id,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@agent_required
@require_http_methods(["GET", "POST"])
def agent_resubmit_reverted_loan(request, loan_id):
    """
    Agent correction form for reverted applications.
    Allows updating key fields, replacing one document, and resubmitting
    directly into Bank Login Process.
    """
    agent = Agent.objects.get(user=request.user)
    loan = get_object_or_404(get_agent_loan_queryset(request.user, agent), id=loan_id)

    remarks_text = str(loan.remarks or '')
    has_revert_history = 'revert remark ' in remarks_text.lower()
    if not has_revert_history:
        messages.warning(request, 'This loan does not have a revert remark yet.')
        return redirect('agent_my_applications')

    if request.method == 'POST':
        # Enhanced template sends `agent_remarks` (plural).
        agent_remark = str(request.POST.get('agent_remarks', '')).strip()
        if not agent_remark and not str(request.POST.get('auto_save', '')).lower() == 'true':
            messages.error(request, 'Please write agent remark before resubmitting.')
            return redirect('agent_resubmit_reverted_loan', loan_id=loan.id)

        is_auto_save = str(request.POST.get('auto_save', '')).lower() == 'true'

        # Update all editable fields (enhanced template).
        def _clean_str(v):
            return str(v or '').strip()

        def _to_int_or_none(raw):
            raw = _clean_str(raw)
            if not raw:
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None

        def _to_decimal_or_none(raw):
            raw = _clean_str(raw)
            if not raw:
                return None
            try:
                return raw  # Let model/DB handle Decimal conversion via DecimalField
            except Exception:
                return None

        loan.full_name = _clean_str(request.POST.get('full_name', loan.full_name))
        loan.mobile_number = _clean_str(request.POST.get('mobile_number', loan.mobile_number))
        loan.email = _clean_str(request.POST.get('email', loan.email))

        loan.permanent_address = _clean_str(request.POST.get('permanent_address', loan.permanent_address))
        loan.current_address = _clean_str(request.POST.get('current_address', loan.current_address))
        loan.city = _clean_str(request.POST.get('city', loan.city))
        loan.state = _clean_str(request.POST.get('state', loan.state))
        loan.pin_code = _clean_str(request.POST.get('pin_code', loan.pin_code))

        loan.loan_type = _clean_str(request.POST.get('loan_type', loan.loan_type))
        loan.loan_amount = _to_decimal_or_none(request.POST.get('loan_amount', loan.loan_amount)) or loan.loan_amount
        loan.tenure_months = _to_int_or_none(request.POST.get('tenure_months', loan.tenure_months))
        loan.interest_rate = _to_decimal_or_none(request.POST.get('interest_rate', loan.interest_rate)) or loan.interest_rate
        loan.loan_purpose = _clean_str(request.POST.get('loan_purpose', loan.loan_purpose))

        # Co-applicant & Guarantor (optional)
        has_co_applicant_raw = request.POST.get('has_co_applicant', 'false')
        loan.has_co_applicant = str(has_co_applicant_raw).lower() == 'true'
        if loan.has_co_applicant:
            loan.co_applicant_name = _clean_str(request.POST.get('co_applicant_name', loan.co_applicant_name))
            loan.co_applicant_phone = _clean_str(request.POST.get('co_applicant_phone', loan.co_applicant_phone))
            loan.co_applicant_email = _clean_str(request.POST.get('co_applicant_email', loan.co_applicant_email))
        else:
            loan.co_applicant_name = None
            loan.co_applicant_phone = None
            loan.co_applicant_email = None

        has_guarantor_raw = request.POST.get('has_guarantor', 'false')
        loan.has_guarantor = str(has_guarantor_raw).lower() == 'true'
        if loan.has_guarantor:
            loan.guarantor_name = _clean_str(request.POST.get('guarantor_name', loan.guarantor_name))
            loan.guarantor_phone = _clean_str(request.POST.get('guarantor_phone', loan.guarantor_phone))
            loan.guarantor_email = _clean_str(request.POST.get('guarantor_email', loan.guarantor_email))
        else:
            loan.guarantor_name = None
            loan.guarantor_phone = None
            loan.guarantor_email = None

        loan.bank_name = _clean_str(request.POST.get('bank_name', loan.bank_name))
        loan.bank_type = _clean_str(request.POST.get('bank_type', loan.bank_type)) or None
        loan.bank_account_number = _clean_str(request.POST.get('bank_account_number', loan.bank_account_number))
        loan.bank_ifsc_code = _clean_str(request.POST.get('bank_ifsc_code', loan.bank_ifsc_code))

        # Only update remarks/status on real submit; auto-save should not create new history entries.
        previous_status = loan.status
        if not is_auto_save:
            reply_count = 0
            remarks_text = str(loan.remarks or '')
            for line in remarks_text.splitlines():
                if str(line).strip().lower().startswith('agent reply '):
                    reply_count += 1
            reply_reason = f"Agent Reply {reply_count + 1}: {agent_remark}"

            loan.remarks = _append_note_line(loan.remarks, reply_reason)
            loan.status = 'follow_up'
            loan.assigned_at = timezone.now()
            loan.action_taken_at = None
            loan.is_sm_signed = False
            loan.sm_signed_at = None
        else:
            # Keep current workflow status for draft save.
            loan.action_taken_at = loan.action_taken_at or None

        # Save the updated loan core fields first.
        loan.save()

        # Multi-document uploads: enhanced template sends files as `new_document_<index>`.
        if not is_auto_save:
            def _infer_document_type_from_filename(filename: str) -> str:
                name = _clean_str(filename).lower()
                # Applicant basics
                if 'pan' in name and 'co' not in name and 'guar' not in name:
                    return 'pan_card'
                if 'aadhaar' in name or 'aadhar' in name:
                    if 'co' in name:
                        if 'photo' in name:
                            return 'co_applicant_photo'
                        return 'co_applicant_aadhaar'
                    if 'guar' in name or 'guarantor' in name:
                        return 'guarantor_aadhaar'
                    return 'aadhaar_card'
                if 'photo' in name:
                    if 'co' in name:
                        return 'co_applicant_photo'
                    if 'guar' in name or 'guarantor' in name:
                        return 'guarantor_address_proof'  # best-effort; UI may not provide distinct photo naming
                    return 'applicant_photo'
                if 'permanent' in name or ('perm' in name and 'address' in name):
                    return 'permanent_address_proof'
                if 'current' in name or 'present' in name or ('curr' in name and 'address' in name):
                    return 'current_address_proof'
                if 'salary' in name or 'slip' in name:
                    return 'salary_slip'
                if 'bank_statement' in name or 'bank statement' in name:
                    return 'bank_statement'
                if 'form16' in name or 'form_16' in name or 'form 16' in name:
                    return 'form_16'
                if 'service_book' in name or 'service book' in name:
                    return 'service_book'
                if 'property' in name:
                    return 'property_documents'
                if 'soa' in name:
                    return 'soa_existing_loan'
                if 'co' in name and 'pan' in name:
                    return 'co_applicant_pan'
                if 'guar' in name or 'guarantor' in name:
                    if 'pan' in name:
                        return 'guarantor_pan'
                    if 'address' in name:
                        return 'guarantor_address_proof'
                return 'other'

            # Perform uploads.
            uploaded_any = False
            for file_key, doc_file in request.FILES.items():
                if not str(file_key).startswith('new_document_'):
                    continue
                uploaded_any = True
                inferred_type = _infer_document_type_from_filename(getattr(doc_file, 'name', '') or file_key)
                LoanDocument.objects.update_or_create(
                    loan=loan,
                    document_type=inferred_type,
                    defaults={
                        'file': doc_file,
                        'is_required': False,
                    }
                )

        if is_auto_save:
            # Draft save: return a simple success response for the AJAX request.
            return JsonResponse({'success': True, 'message': 'Draft auto-saved'})

        synced_application = sync_loan_to_application(
            loan,
            assigned_by_user=request.user,
            create_if_missing=True,
        )
        if synced_application:
            LoanStatusHistory.objects.create(
                loan_application=synced_application,
                from_status=_normalize_history_status(previous_status),
                to_status='follow_up',
                changed_by=request.user,
                reason=reply_reason,
                is_auto_triggered=False,
            )

        messages.success(request, 'Application re-submitted to Bank Login Process successfully.')
        return redirect(f"{reverse('agent_my_applications')}?status=follow_up&loan_id={loan.id}")

    documents = LoanDocument.objects.filter(loan=loan).order_by('-uploaded_at')
    revert_remarks = []
    for line in remarks_text.splitlines():
        clean = str(line).strip()
        if clean.lower().startswith('revert remark '):
            revert_remarks.append(clean)

    context = {
        'page_title': 'Reverted Loan Edit',
        'loan': loan,
        'documents': documents,
        'revert_remarks': revert_remarks,
        'document_type_choices': LoanDocument.DOCUMENT_TYPE_CHOICES,
    }
    return render(request, 'core/agent/reverted_loan_edit_enhanced.html', context)


@agent_required
def agent_reports(request):
    """
    Generate downloadable reports for agent's loans.
    Supports: 1 month, 6 months, 1 year.
    """
    agent = Agent.objects.get(user=request.user)
    
    period = request.GET.get('period', '1month')
    status_filter = (request.GET.get('status') or '').strip()
    employee_filter = (request.GET.get('employee') or '').strip()
    partner_filter = (request.GET.get('partner') or '').strip()
    search_query = (request.GET.get('q') or '').strip()
    loan_id_filter = (request.GET.get('loan_id') or '').strip()

    # Calculate date range
    today = timezone.now()
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    if from_date and to_date:
        try:
            start_date = timezone.make_aware(datetime.strptime(from_date, '%Y-%m-%d'))
            end_of_day = datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1)
            end_date = timezone.make_aware(end_of_day)
            period = 'custom'
        except ValueError:
            messages.error(request, 'Invalid custom date range. Showing last 1 month.')
            start_date = today - timedelta(days=30)
            end_date = today
            period = '1month'
    elif period == '1month':
        start_date = today - timedelta(days=30)
        end_date = today
    elif period == '6months':
        start_date = today - timedelta(days=180)
        end_date = today
    elif period == '1year':
        start_date = today - timedelta(days=365)
        end_date = today
    else:
        start_date = today - timedelta(days=30)
        end_date = today

    # Get loans in period
    loans = get_agent_loan_queryset(request.user, agent).filter(
        created_at__gte=start_date,
        created_at__lt=end_date
    ).select_related(
        'created_by',
        'assigned_employee',
        'assigned_agent',
    ).prefetch_related('documents').order_by('-created_at')

    if loan_id_filter:
        try:
            loans = loans.filter(id=int(loan_id_filter))
        except (TypeError, ValueError):
            loans = loans.none()

    if status_filter:
        status_alias_map = {
            'processing': 'waiting',
            'waiting_for_processing': 'waiting',
            'updated': UPDATED_DOCUMENT_STATUS_KEY,
            'banking': 'follow_up',
            'followup_pending': 'follow_up_pending',
        }
        normalized_status = status_alias_map.get(status_filter, status_filter)
        matching_ids = [
            loan.id for loan in loans
            if _effective_status_key_for_loan(loan) == normalized_status
        ]
        loans = loans.filter(id__in=matching_ids)
        status_filter = normalized_status

    if employee_filter:
        loans = loans.filter(assigned_employee_id=employee_filter)

    if partner_filter:
        loans = loans.filter(assigned_agent_id=partner_filter)

    if search_query:
        loans = loans.filter(
            Q(full_name__icontains=search_query) |
            Q(mobile_number__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(user_id__icontains=search_query)
        )
    
    # Handle download
    if request.GET.get('download'):
        format_type = request.GET.get('format', 'csv')
        if format_type == 'csv':
            return export_loans_csv(loans, period)
        elif format_type in ['excel', 'xlsx']:
            return export_loans_excel(loans, period)

    employee_options = User.objects.filter(
        id__in=get_agent_loan_queryset(request.user, agent)
        .exclude(assigned_employee__isnull=True)
        .values_list('assigned_employee_id', flat=True)
    ).order_by('first_name', 'last_name', 'username')

    partner_options = Agent.objects.filter(
        id__in=get_agent_loan_queryset(request.user, agent)
        .exclude(assigned_agent__isnull=True)
        .values_list('assigned_agent_id', flat=True)
    ).order_by('name')
    
    context = {
        'loans': loans,
        'period': period,
        'from_date': from_date,
        'to_date': to_date,
        'status_filter': status_filter,
        'employee_filter': employee_filter,
        'partner_filter': partner_filter,
        'search_query': search_query,
        'employee_options': employee_options,
        'partner_options': partner_options,
        'total_loans': loans.count(),
        'total_amount': loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
        'approved_count': loans.filter(status='approved').count(),
        'approved_loans': loans.filter(status='approved').count(),
        'disbursed_loans': loans.filter(status='disbursed').count(),
        'rejected_loans': loans.filter(status='rejected').count(),
        'generated_reports': [],
    }
    return render(request, 'core/agent/reports.html', context)


@agent_required
def agent_complaints(request):
    """
    Display complaints filed by this agent.
    Shows real-time updates and allows viewing complaint details.
    """
    agent = Agent.objects.get(user=request.user)

    base_complaints = Complaint.objects.filter(
        filed_by_agent=agent
    ).select_related('loan', 'assigned_admin').order_by('-created_at')
    
    user_loans = get_agent_loan_queryset(request.user, agent).order_by('-created_at')
    
    # Filter by status
    status_filter = request.GET.get('status')
    complaints = base_complaints
    if status_filter:
        complaints = complaints.filter(status=status_filter)

    complaints = list(complaints)

    # Subject is stored in description first line for compatibility with model fields
    for complaint in complaints:
        raw_description = (complaint.description or '').strip()
        if '\n\n' in raw_description:
            subject_line, body_text = raw_description.split('\n\n', 1)
        else:
            subject_line = raw_description.split('\n', 1)[0]
            body_text = raw_description

        fallback_subject = f"{complaint.get_complaint_type_display()} Issue"
        complaint.subject_text = (subject_line or fallback_subject)[:100]
        complaint.body_text = body_text
    
    context = {
        'complaints': complaints,
        'user_loans': user_loans,
        'total': base_complaints.count(),
        'open': base_complaints.filter(status__in=['open', 'in_progress']).count(),
        'resolved': base_complaints.filter(status='resolved').count(),
        'status_filter': status_filter,
    }
    return render(request, 'core/agent/complaints.html', context)


@agent_required
@require_http_methods(["POST"])
def file_complaint(request):
    """
    File a new complaint from agent.
    Automatically appears in admin panel in real-time.
    """
    try:
        agent = Agent.objects.get(user=request.user)
        loan_id = (request.POST.get('loan_id') or '').strip()
        subject = (request.POST.get('subject') or '').strip()
        description = (request.POST.get('description') or '').strip()
        priority = (request.POST.get('priority') or 'medium').strip().lower()
        raw_type = (request.POST.get('complaint_type') or 'other').strip().lower()

        if not loan_id:
            messages.error(request, 'Please select a loan first.')
            return redirect('agent_complaints')
        if not description:
            messages.error(request, 'Please enter complaint description.')
            return redirect('agent_complaints')

        loan = get_agent_loan_queryset(request.user, agent).filter(id=loan_id).first()
        if not loan:
            messages.error(request, 'Selected loan was not found in your scope.')
            return redirect('agent_complaints')

        complaint_type_map = {
            'processing_delay': 'service',
            'communication': 'service',
            'service_quality': 'service',
            'approval_issue': 'service',
            'disbursement': 'payment',
            'documentation': 'documentation',
            'other': 'other',
            'service': 'service',
            'payment': 'payment',
        }
        complaint_type = complaint_type_map.get(raw_type, 'other')
        if priority == 'normal':
            priority = 'medium'
        if priority not in {'low', 'medium', 'high', 'urgent'}:
            priority = 'medium'

        if subject:
            full_description = f"{subject}\n\n{description}"
        else:
            full_description = description

        Complaint.objects.create(
            customer_name=loan.full_name or 'Unknown',
            loan=loan,
            filed_by_agent=agent,
            complaint_type=complaint_type,
            priority=priority,
            description=full_description,
            status='open',
            created_by=request.user,
        )
        
        messages.success(request, 'Complaint filed successfully!')
        return redirect('agent_complaints')
        
    except Exception as e:
        messages.error(request, f'Error filing complaint: {str(e)}')
        return redirect('agent_complaints')


def _report_user_name(user_obj):
    if not user_obj:
        return ''
    return user_obj.get_full_name() or user_obj.username or user_obj.email or ''


def _report_partner_name(agent_obj):
    if not agent_obj:
        return ''
    return agent_obj.name or _report_user_name(agent_obj.user) or ''


def _report_datetime(value):
    if not value:
        return ''
    try:
        return timezone.localtime(value).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return str(value)


def _loan_report_row(loan):
    status_key = _effective_status_key_for_loan(loan)
    return [
        loan.user_id or loan.id,
        loan.full_name or '',
        loan.mobile_number or '',
        loan.email or '',
        loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else (loan.loan_type or ''),
        loan.loan_amount or 0,
        get_status_label(status_key),
        _report_user_name(loan.assigned_employee),
        _report_partner_name(loan.assigned_agent),
        _report_user_name(loan.created_by),
        _report_datetime(loan.created_at),
        _report_datetime(loan.updated_at),
        _report_datetime(loan.assigned_at),
        _report_datetime(loan.action_taken_at),
        loan.bank_name or '',
        loan.bank_account_number or '',
        loan.bank_ifsc_code or '',
        loan.sm_name or '',
        loan.remarks or '',
    ]


def _loan_report_headers():
    return [
        'Loan ID',
        'Applicant Name',
        'Phone',
        'Email',
        'Loan Type',
        'Loan Amount',
        'Status',
        'Assigned Employee',
        'Channel Partner',
        'Created By',
        'Created Time',
        'Updated Time',
        'Assigned Time',
        'Action Time',
        'Bank Name',
        'Bank Account Number',
        'Bank IFSC',
        'SM / DSA Name',
        'Remarks',
    ]


def export_loans_csv(loans, period):
    """Export loans data as CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="channel_partner_loans_{period}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(_loan_report_headers())
    
    for loan in loans:
        writer.writerow(_loan_report_row(loan))
    
    return response


def export_loans_excel(loans, period):
    """Export loans data as Excel"""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Loans'
    
    # Headers
    worksheet.append(_loan_report_headers())
    
    # Data
    for loan in loans:
        worksheet.append(_loan_report_row(loan))
    
    # Auto-adjust columns
    for column in worksheet.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)
    
    # Write to response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="channel_partner_loans_{period}.xlsx"'
    workbook.save(response)
    
    return response


# API endpoints for real-time updates
@agent_required
def api_agent_dashboard_stats(request):
    """
    API endpoint for real-time dashboard statistics.
    Returns JSON data for live count updates.
    """
    auto_move_overdue_to_follow_up()

    agent = Agent.objects.get(user=request.user)
    agent_loans_qs = get_agent_loan_queryset(request.user, agent)
    agent_loans = list(agent_loans_qs)
    counts = _status_breakdown(agent_loans)
    counts = _merge_status_counts(
        counts,
        _application_status_breakdown(_agent_workflow_only_applications(agent, agent_loans)),
    )
    
    data = {
        'total_assigned': counts['total'],
        'processing': counts['new_entry'] + counts['waiting'] + counts[UPDATED_DOCUMENT_STATUS_KEY] + counts['follow_up'],
        'approved': counts['approved'],
        'rejected': counts['rejected'],
        'disbursed': counts['disbursed'],
        'total_amount': float(agent_loans_qs.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0),
        'new_entry': counts['new_entry'],
        'waiting': counts['waiting'],
        'updated_document': counts[UPDATED_DOCUMENT_STATUS_KEY],
        'bank_stage': counts['follow_up'],
        'follow_up_pending': counts['follow_up_pending'],
        'timestamp': timezone.now().isoformat(),
    }
    
    return JsonResponse(data)


@agent_required
def agent_notifications(request):
    """
    Real-time notifications API for agent dashboard.
    Shows updates about loans and complaints from admin panel.
    """
    agent = Agent.objects.get(user=request.user)
    assigned_loans = Loan.objects.filter(assigned_agent=agent)

    notifications = []

    approved_loans = assigned_loans.filter(status='approved').order_by('-updated_at')[:3]
    for loan in approved_loans:
        notifications.append({
            'id': f'approved_{loan.id}',
            'title': 'Loan Approved',
            'message': f'{loan.full_name} - Rs {loan.loan_amount}',
            'created_at': loan.updated_at.isoformat(),
            'type': 'approved'
        })

    complaints = Complaint.objects.filter(filed_by_agent=agent).order_by('-created_at')[:2]
    for complaint in complaints:
        notifications.append({
            'id': f'complaint_{complaint.id}',
            'title': 'Complaint Update',
            'message': complaint.subject,
            'created_at': complaint.created_at.isoformat(),
            'type': 'complaint'
        })

    new_entries = assigned_loans.filter(status='new_entry').order_by('-created_at')[:2]
    for entry in new_entries:
        notifications.append({
            'id': f'new_entry_{entry.id}',
            'title': 'New Entry Assigned',
            'message': f'{entry.full_name} - Rs {entry.loan_amount}',
            'created_at': entry.created_at.isoformat(),
            'type': 'new_entry'
        })

    notifications.sort(key=lambda x: x['created_at'], reverse=True)

    return JsonResponse({
        'notifications': notifications[:5]
    })


@agent_required
def agent_profile(request):
    """Agent profile page - display all agent details"""
    try:
        agent = Agent.objects.get(user=request.user)
    except Agent.DoesNotExist:
        messages.error(request, "Agent profile not found!")
        return redirect('agent_dashboard')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'change_password':
            old_password = request.POST.get('old_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            if not request.user.check_password(old_password):
                messages.error(request, "Old password is incorrect.")
            elif new_password != confirm_password:
                messages.error(request, "New passwords do not match.")
            elif len(new_password) < 6:
                messages.error(request, "Password must be at least 6 characters.")
            else:
                request.user.set_password(new_password)
                request.user.save()
                messages.success(request, "Password changed successfully. Please log in again.")
                return redirect('login')

        elif action == 'notification_settings':
            messages.success(request, "Notification settings updated successfully.")
        
        elif action == 'upload_onboarding_doc':
            """
            Upload agent onboarding/KYC documents (Pan, Aadhar, Passbook/Cancel check/statement).
            Stored in User model so other panels can display the uploaded files easily.
            """
            document_type = (request.POST.get('document_type') or '').strip()
            document_file = request.FILES.get('document_file')
            if not document_type:
                messages.error(request, 'Document type required.')
                return redirect('agent_profile')
            if not document_file:
                messages.error(request, 'Document file required.')
                return redirect('agent_profile')
            if document_file.size > 10 * 1024 * 1024:
                messages.error(request, 'File size must be <= 10MB.')
                return redirect('agent_profile')

            user = request.user
            if document_type == 'pan_card':
                user.pan_card_doc = document_file
            elif document_type == 'aadhaar_card':
                user.aadhar_card_doc = document_file
            elif document_type == 'bank_statement':
                user.bank_details_doc = document_file
            user.save()
            messages.success(request, 'Document uploaded successfully.')
            return redirect('agent_profile')    
    context = {
        'agent': agent,
        'page_title': 'My Profile',
        'onboarding_documents': request.user.onboarding_documents.all().order_by('-uploaded_at'),
    }
    return render(request, 'core/agent/profile.html', context)


@agent_required
def agent_edit_profile(request):
    """Edit agent profile - phone, email, address, profile_photo"""
    try:
        agent = Agent.objects.get(user=request.user)
    except Agent.DoesNotExist:
        messages.error(request, "Agent profile not found!")
        return redirect('agent_dashboard')
    
    if request.method == 'POST':
        # Update only allowed fields
        phone = request.POST.get('phone', agent.phone)
        email = request.POST.get('email', agent.email)
        address = request.POST.get('address', agent.address)
        
        # Handle profile photo upload
        if 'profile_photo' in request.FILES:
            agent.profile_photo = request.FILES['profile_photo']
        
        # Update fields
        agent.phone = phone
        agent.email = email
        agent.address = address
        agent.save()
        
        # Update user email as well
        user = request.user
        user.email = email
        user.save()
        
        messages.success(request, "Profile updated successfully!")
        return redirect('agent_profile')
    
    context = {
        'agent': agent,
        'page_title': 'Edit Profile',
    }
    return render(request, 'core/agent/edit_profile.html', context)


@agent_required
def agent_settings(request):
    """Channel partner settings and profile management."""
    try:
        agent = Agent.objects.get(user=request.user)
    except Agent.DoesNotExist:
        messages.error(request, "Agent profile not found!")
        return redirect('agent_dashboard')
    return render(request, 'core/shared/panel_settings.html', {
        'agent': agent,
        'page_title': 'Settings',
    })


@agent_required
def api_agent_recent_entries(request):
    """
    API endpoint for agent's recent loan entries (created by this agent).
    Returns recent applications in JSON format for real-time dashboard display.
    Includes all loans created by agent regardless of status.
    """
    try:
        agent = Agent.objects.get(user=request.user)
        
        # Get limit from query params
        limit = int(request.GET.get('limit', 10))
        
        # Use same scope as dashboard cards so table and cards always match
        recent_loans_qs = get_agent_loan_queryset(request.user, agent).select_related(
            'assigned_employee', 'assigned_agent'
        ).order_by('-created_at')
        legacy_loans = list(recent_loans_qs)
        workflow_apps = list(_agent_workflow_only_applications(agent, legacy_loans))
        workflow_rows = [
            build_application_display_row(app_obj, status_key=application_effective_status_key(app_obj))
            for app_obj in workflow_apps
        ]
        recent_rows = []
        for loan in legacy_loans:
            status_key = _effective_status_key_for_loan(loan)
            loan.entity_type = 'legacy'
            loan.status = status_key
            recent_rows.append(loan)
        recent_rows.extend(workflow_rows)
        recent_rows.sort(key=lambda row: getattr(getattr(row, 'created_at', None), 'timestamp', lambda: 0)(), reverse=True)
        recent_rows = recent_rows[:limit]
        
        # Format response data
        loans_data = []
        for loan in recent_rows:
            status_key = getattr(loan, 'status', '') or _effective_status_key_for_loan(loan)
            entity_type = getattr(loan, 'entity_type', 'legacy') or 'legacy'
            assigned_employee = getattr(loan, 'assigned_employee', None)
            assigned_agent = getattr(loan, 'assigned_agent', None)
            loan_data = {
                'id': loan.id,
                'applicant_name': getattr(loan, 'full_name', '') or getattr(loan, 'applicant_name', '') or 'N/A',
                'mobile_number': getattr(loan, 'mobile_number', '') or getattr(loan, 'phone', '') or 'N/A',
                'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else (getattr(loan, 'loan_type', '') or 'N/A'),
                'loan_amount': float(getattr(loan, 'loan_amount', 0) or 0),
                'status': status_key,
                'status_label': get_status_label(status_key),
                'stage': get_stage_label(status_key),
                'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'assigned_date': getattr(loan, 'updated_at', None).strftime('%Y-%m-%d') if getattr(loan, 'updated_at', None) else 'N/A',
                'assigned_employee': assigned_employee.get_full_name() if assigned_employee else getattr(loan, 'processed_by', 'Pending'),
                'assigned_agent': (
                    assigned_agent.user.get_full_name()
                    if assigned_agent and assigned_agent.user
                    else (assigned_agent.name if assigned_agent else getattr(loan, 'submitted_by', 'N/A'))
                ),
                'status_badge': get_status_badge(status_key),
                # Open directly in My Applications to avoid applicant-id route mismatch
                'detail_url': f"{reverse('agent_loan_detail', args=[loan.id])}?entity_type={entity_type}",
                'entity_type': entity_type,
            }
            loans_data.append(loan_data)
        
        return JsonResponse({
            'success': True,
            'total': len(legacy_loans) + len(workflow_apps),
            'recent_entries': loans_data,
        })
    
    except Agent.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Agent not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def get_status_badge(status):
    """Helper function to get Bootstrap badge class for status"""
    badges = {
        'draft': 'secondary',
        'new_entry': 'primary',
        'waiting_for_processing': 'warning',
        'waiting': 'warning',
        UPDATED_DOCUMENT_STATUS_KEY: 'success',
        'processing': 'info',
        'follow_up_pending': 'warning',
        'approved': 'success',
        'rejected': 'danger',
        'disbursed': 'success',
        'follow_up': 'warning',
    }
    return badges.get(status, 'secondary')


def get_status_label(status):
    labels = {
        'draft': 'Draft',
        'new_entry': 'New Entry',
        'waiting': 'Processing',
        UPDATED_DOCUMENT_STATUS_KEY: UPDATED_DOCUMENT_LABEL,
        'waiting_for_processing': 'Processing',
        'follow_up': 'Bank Stage',
        'follow_up_pending': 'Follow Up',
        'approved': 'Approved',
        'rejected': 'Rejected',
        'disbursed': 'Disbursed',
    }
    return labels.get(status, status.replace('_', ' ').title())


def get_stage_label(status):
    stage_map = {
        'draft': 'Draft',
        'new_entry': 'New Entry',
        'waiting': 'Processing',
        UPDATED_DOCUMENT_STATUS_KEY: UPDATED_DOCUMENT_LABEL,
        'waiting_for_processing': 'Processing',
        'follow_up': 'Bank Stage',
        'follow_up_pending': 'Follow Up',
        'approved': 'Completed',
        'rejected': 'Closed',
        'disbursed': 'Disbursed',
    }
    return stage_map.get(status, 'Processing')
