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
    Agent,
    Complaint,
    User,
    LoanDocument,
    LoanStatusHistory,
    AgentAssignment,
    UserOnboardingDocument,
)
from .loan_sync import sync_loan_to_application
from .followup_utils import auto_move_overdue_to_follow_up
from .role_decorators import agent_required
from .upload_limits import validate_loan_document_batch
from .updated_document_utils import (
    UPDATED_DOCUMENT_LABEL,
    UPDATED_DOCUMENT_STATUS_KEY,
    loan_has_updated_documents,
)
from .account_notifications import send_account_credentials_email
from .id_utils import normalize_manual_loan_id


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
    sub_agents = Agent.objects.filter(created_by=request.user)
    
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
        
        # Check email uniqueness
        if User.objects.filter(email=email).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already registered'
            }, status=400)
        
        # Check phone uniqueness  
        if User.objects.filter(phone=phone).exists():
            return JsonResponse({
                'success': False,
                'error': 'Phone number already registered'
            }, status=400)
        
        # Parse full name
        name_parts = full_name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        # Create user
        user = User.objects.create_user(
            username=email.split('@')[0],  # Username from email prefix
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
        
        # Create agent
        sub_agent = Agent.objects.create(
            user=user,
            name=f"{first_name} {last_name}",
            phone=phone,
            email=email,
            address=address if address else None,
            city=city if city else None,
            state=state if state else None,
            pin_code=pin_code if pin_code else None,
            gender=gender if gender else None,
            created_by=request.user,
        )

        email_sent, email_detail = send_account_credentials_email(
            request=request,
            email=user.email,
            full_name=sub_agent.name,
            username=user.username,
            password=password,
            role=user.role,
        )
        
        return JsonResponse({
            'success': True,
            'message': (
                f'Team member {sub_agent.name} created successfully!'
                + (' Credentials email sent successfully.' if email_sent else (f' Credentials email could not be sent: {email_detail}' if email_detail else ''))
            ),
            'agent_id': sub_agent.id,
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
        loans = [loan for loan in all_loans if _effective_status_key_for_loan(loan) == normalized_status]
    else:
        loans = list(all_loans)

    for loan in loans:
        loan.has_revert_pending = _effective_status_key_for_loan(loan) == 'follow_up_pending'

    recent_submitted = list(all_loans[:10])
    for loan in recent_submitted:
        loan.has_revert_pending = _effective_status_key_for_loan(loan) == 'follow_up_pending'

    # Get counts by status
    counts = _status_breakdown(all_loans)
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
    loan = get_object_or_404(get_agent_loan_queryset(request.user, agent), id=loan_id)
    # Share the same UI with employee, but hide employee-only actions in JS by role.
    return render(request, 'core/employee/loan_detail.html', {'loan_id': loan.id})


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
    directly into Banking Processing.
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

        messages.success(request, 'Application re-submitted to Banking Processing successfully.')
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
    
    # Handle download
    if request.GET.get('download'):
        format_type = request.GET.get('format', 'csv')
        if format_type == 'csv':
            return export_loans_csv(loans, period)
        elif format_type == 'excel':
            return export_loans_excel(loans, period)
    
    context = {
        'loans': loans,
        'period': period,
        'from_date': from_date,
        'to_date': to_date,
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


def export_loans_csv(loans, period):
    """Export loans data as CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="loans_{period}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Applicant Name', 'Phone', 'Email', 'Loan Amount', 'Status', 'Created Date'])
    
    for loan in loans:
        writer.writerow([
            loan.full_name,
            loan.mobile_number,
            loan.email,
            loan.loan_amount,
            loan.get_status_display(),
            loan.created_at.strftime('%Y-%m-%d'),
        ])
    
    return response


def export_loans_excel(loans, period):
    """Export loans data as Excel"""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Loans'
    
    # Headers
    headers = ['Applicant Name', 'Phone', 'Email', 'Loan Amount', 'Status', 'Created Date']
    worksheet.append(headers)
    
    # Data
    for loan in loans:
        worksheet.append([
            loan.full_name,
            loan.mobile_number,
            loan.email,
            loan.loan_amount,
            loan.get_status_display(),
            loan.created_at.strftime('%Y-%m-%d'),
        ])
    
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
    response['Content-Disposition'] = f'attachment; filename="loans_{period}.xlsx"'
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
    """Legacy settings route now merged into profile page."""
    return redirect('agent_profile')


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
        recent_loans = recent_loans_qs[:limit]
        
        # Format response data
        loans_data = []
        for loan in recent_loans:
            status_key = _effective_status_key_for_loan(loan)
            loan_data = {
                'id': loan.id,
                'applicant_name': loan.full_name or 'N/A',
                'mobile_number': loan.mobile_number or 'N/A',
                'loan_type': loan.loan_type or 'N/A',
                'loan_amount': float(loan.loan_amount or 0),
                'status': status_key,
                'status_label': get_status_label(status_key),
                'stage': get_stage_label(status_key),
                'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'assigned_date': loan.updated_at.strftime('%Y-%m-%d') if loan.updated_at else 'N/A',
                'assigned_employee': loan.assigned_employee.get_full_name() if loan.assigned_employee else 'Pending',
                'assigned_agent': (
                    loan.assigned_agent.user.get_full_name()
                    if loan.assigned_agent and loan.assigned_agent.user
                    else (loan.assigned_agent.name if loan.assigned_agent else 'N/A')
                ),
                'status_badge': get_status_badge(status_key),
                # Open directly in My Applications to avoid applicant-id route mismatch
                'detail_url': f"{reverse('agent_my_applications')}?loan_id={loan.id}",
            }
            loans_data.append(loan_data)
        
        return JsonResponse({
            'success': True,
            'total': recent_loans_qs.count(),
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
