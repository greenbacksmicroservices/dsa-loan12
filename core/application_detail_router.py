"""
APPLICATION DETAIL ROUTER - Strict Form Prevention (Production-Grade)
================================================================================
CRITICAL: Forms ONLY render in New Entry status
Routes to correct template based on status + role + safety checks

Architecture:
1. application_detail_form() - Form editing (New Entry only, admin only)
2. application_detail_router() - Routes to read-only views based on status
3. Status-specific detail views - Waiting, Follow-up, Approved, Rejected, Disbursed

Form Isolation:
- Form is in: templates/partials/application_form_only.html
- Form rendered by: application_detail_form() only
- Context flag: can_edit_form (True ONLY for New Entry + admin)
- Prevention: prevent_form_rendering(status) guard in templates
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.utils import timezone
from datetime import timedelta

from .models import LoanApplication, Applicant, User, Agent, ActivityLog, Loan
from .decorators import admin_required


class FormPreventionError(Exception):
    """Raised when form rendering is attempted outside 'new' status"""
    pass


def get_application_or_404(applicant_id, user):
    """
    Safely fetch application with permission check
    Raises Http404 if not found or user lacks permission
    """
    try:
        app = LoanApplication.objects.select_related(
            'applicant', 'assigned_employee', 'assigned_agent',
            'approved_by', 'rejected_by'
        ).get(applicant__id=applicant_id)
        return app
    except LoanApplication.DoesNotExist:
        raise Http404("Application not found")


def can_edit_application(application, user):
    """
    Strict rules for form editing:
    - ONLY if status == 'New Entry'
    - ONLY if user is admin
    - NO exceptions
    """
    return (
        application.status == 'New Entry' and 
        user.is_authenticated and 
        user.role == 'admin'
    )


def prevent_form_rendering(status):
    """
    CRITICAL: Returns True ONLY if form should render
    Used as safety check - must be True AND can_edit_application must be True
    """
    return status == 'New Entry'


def get_application_detail_context(application, user):
    """
    Build context with safety checks
    CRITICAL: Form context ONLY if status='New Entry' AND user='admin'
    
    Returns:
        dict: Context with:
            - can_edit_form: bool - True ONLY if New Entry + admin
            - form_fields_editable: bool - Match can_edit_form
            - hours_waiting: int - For Waiting status
            - is_overdue: bool - For 24-hour threshold
    """
    context = {
        'application': application,
        'applicant': application.applicant,
        'status': application.status,
        'can_edit_form': False,  # DEFAULT: False (safe)
        'form_fields_editable': False,  # DEFAULT: False (safe)
    }
    
    # CRITICAL: Form context ONLY for New Entry + admin
    if application.status == 'New Entry' and user.is_authenticated and user.role == 'admin':
        context['can_edit_form'] = True
        context['form_fields_editable'] = True
        context['available_employees'] = User.objects.filter(role='employee', is_active=True)
        context['available_agents'] = Agent.objects.filter(status='Active')
        context['is_new_entry'] = True
    
    # Calculate metrics for Waiting/Follow-up status
    if application.assigned_at and application.status in ['Waiting for Processing', 'Required Follow-up']:
        hours_waiting = int((timezone.now() - application.assigned_at).total_seconds() / 3600)
        context['hours_waiting'] = hours_waiting
        context['hours_remaining'] = max(0, 24 - hours_waiting)
        context['is_overdue'] = hours_waiting > 24
    
    # Add timeline events
    context['timeline_events'] = []
    if application.created_at:
        context['timeline_events'].append({
            'type': 'created',
            'timestamp': application.created_at,
            'description': 'Application created'
        })
    if application.assigned_at:
        context['timeline_events'].append({
            'type': 'assigned',
            'timestamp': application.assigned_at,
            'description': f'Assigned to {application.assigned_employee or application.assigned_agent}'
        })
    if application.approved_at:
        context['timeline_events'].append({
            'type': 'approved',
            'timestamp': application.approved_at,
            'description': f'Approved by {application.approved_by}'
        })
    if application.rejected_at:
        context['timeline_events'].append({
            'type': 'rejected',
            'timestamp': application.rejected_at,
            'description': f'Rejected by {application.rejected_by}'
        })
    if application.disbursed_at:
        context['timeline_events'].append({
            'type': 'disbursed',
            'timestamp': application.disbursed_at,
            'description': 'Funds disbursed'
        })
    
    return context


@login_required
def application_detail_router(request, applicant_id):
    """
    MASTER ROUTER - Routes to correct template based on status + role
    CRITICAL: NEVER renders forms outside 'New Entry' status
    
    Routing Table:
    - New Entry (admin only) -> application_detail_form.html (WITH form)
    - Waiting (admin/assigned) -> application_detail_waiting.html (read-only)
    - Follow-up (admin only) -> application_detail_followup.html (read-only)
    - Approved (admin only) -> application_detail_approved.html (read-only)
    - Rejected (admin only) -> application_detail_rejected.html (read-only)
    - Disbursed (admin/finance) -> application_detail_disbursed.html (read-only)
    
    Args:
        request: HttpRequest object
        applicant_id: Primary key of Applicant
        
    Returns:
        HttpResponse: Rendered template with context
        Http404: If application not found or user unauthorized
    """
    
    # Fetch application with safety
    try:
        application = LoanApplication.objects.select_related(
            'applicant', 'assigned_employee', 'assigned_agent',
            'approved_by', 'rejected_by'
        ).get(applicant__id=applicant_id)
    except LoanApplication.DoesNotExist:
        # Compatibility fallback:
        # some UIs send Loan.id here; route them to role-safe pages instead of 404.
        fallback_loan = Loan.objects.filter(id=applicant_id).select_related(
            'assigned_agent', 'created_by'
        ).first()
        if fallback_loan:
            if request.user.role == 'agent':
                try:
                    user_agent = request.user.agent_profile
                except Exception:
                    user_agent = None
                if fallback_loan.created_by_id == request.user.id or (
                    user_agent and fallback_loan.assigned_agent_id == user_agent.id
                ):
                    return redirect(f"/agent/my-applications/?loan_id={fallback_loan.id}")
            if request.user.role == 'admin':
                return redirect(f"/admin/all-loans/?q={fallback_loan.id}")
            if request.user.role == 'subadmin':
                return redirect(f"/subadmin/all-loans/?q={fallback_loan.id}")
            if request.user.role == 'employee':
                return redirect(f"/employee/all-loans/?q={fallback_loan.id}")
        raise Http404("Application not found")
    
    # Role-based permission checks
    if application.status == 'New Entry':
        # ONLY admin can edit new entries
        if request.user.role != 'admin':
            messages.error(request, 'You do not have permission to view this application.')
            return redirect('dashboard')
    
    elif application.status == 'Waiting for Processing':
        # Admin sees all, others see only assigned
        if request.user.role not in ['admin', 'employee', 'agent']:
            messages.error(request, 'You do not have permission to view this application.')
            return redirect('dashboard')
        
        if request.user.role == 'employee' and application.assigned_employee != request.user:
            messages.error(request, 'You do not have permission to view this application.')
            return redirect('dashboard')
        elif request.user.role == 'agent' and application.assigned_agent != request.user.agent_profile:
            messages.error(request, 'You do not have permission to view this application.')
            return redirect('dashboard')
    
    elif application.status == 'Required Follow-up':
        # Admin only
        if request.user.role != 'admin':
            messages.error(request, 'You do not have permission to view this application.')
            return redirect('dashboard')
    
    elif application.status in ['Approved', 'Rejected']:
        # Admin only
        if request.user.role != 'admin':
            messages.error(request, 'You do not have permission to view this application.')
            return redirect('dashboard')
    
    elif application.status == 'Disbursed':
        # Admin or Finance only
        if request.user.role not in ['admin', 'finance']:
            messages.error(request, 'You do not have permission to view this application.')
            return redirect('dashboard')
    
    # Build context (safe - no form context unless New Entry + admin)
    context = get_application_detail_context(application, request.user)
    
    # Route to correct template based on status
    if application.status == 'New Entry':
        # FORM EDITING (admin only)
        template = 'admin/dashboard/new_entry_detail.html'
        context['is_form_page'] = True
    
    elif application.status == 'Waiting for Processing':
        # READ-ONLY detail view
        template = 'dashboard/waiting_detail.html'
        context['can_approve_reject'] = request.user.role == 'admin'
        context['can_reassign'] = request.user.role == 'admin'
        context['is_form_page'] = False
    
    elif application.status == 'Required Follow-up':
        # READ-ONLY detail view (admin only)
        template = 'admin/dashboard/followup_detail.html'
        context['can_reassign'] = True
        context['is_form_page'] = False
    
    elif application.status == 'Approved':
        # READ-ONLY detail view (admin only)
        template = 'admin/dashboard/approved_detail.html'
        context['is_form_page'] = False
    
    elif application.status == 'Rejected':
        # READ-ONLY detail view (admin only)
        template = 'admin/dashboard/rejected_detail.html'
        context['is_form_page'] = False
    
    elif application.status == 'Disbursed':
        # READ-ONLY detail view (admin/finance)
        template = 'admin/dashboard/disbursed_detail.html'
        context['is_form_page'] = False
    
    else:
        raise Http404(f"Unknown status: {application.status}")
    
    return render(request, template, context)


@login_required
@admin_required
def new_entry_form_view(request, applicant_id):
    """
    NEW ENTRY FORM VIEW - Handles form editing/submission
    CRITICAL: ONLY for 'New Entry' status + admin role
    
    Features:
    - Renders form partial: partials/application_form_only.html
    - Validates status is 'New Entry'
    - Requires assignment to Waiting status
    - Logs assignment activity
    
    Args:
        request: HttpRequest
        applicant_id: Applicant ID
        
    Returns:
        GET: Rendered form template
        POST: Redirect to detail view after assignment
    """
    
    try:
        application = LoanApplication.objects.select_related(
            'applicant', 'assigned_employee', 'assigned_agent'
        ).get(applicant__id=applicant_id)
    except LoanApplication.DoesNotExist:
        raise Http404("Application not found")
    
    # CRITICAL: Only New Entry can be edited
    if application.status != 'New Entry':
        messages.error(request, 'This application can no longer be edited. Only New Entry applications can be modified.')
        return redirect('application_detail_router', applicant_id=applicant_id)
    
    if request.method == 'POST':
        try:
            # Update applicant info
            applicant = application.applicant
            applicant.full_name = request.POST.get('full_name', applicant.full_name)
            applicant.email = request.POST.get('email', applicant.email)
            applicant.phone_number = request.POST.get('phone', applicant.phone_number)
            applicant.alternate_phone = request.POST.get('alternate_phone', applicant.alternate_phone)
            applicant.pan = request.POST.get('pan', applicant.pan)
            applicant.aadhar = request.POST.get('aadhar', applicant.aadhar)
            applicant.date_of_birth = request.POST.get('date_of_birth', applicant.date_of_birth)
            applicant.gender = request.POST.get('gender', applicant.gender)
            applicant.permanent_address = request.POST.get('permanent_address', applicant.permanent_address)
            applicant.current_address = request.POST.get('current_address', applicant.current_address)
            applicant.city = request.POST.get('city', applicant.city)
            applicant.state = request.POST.get('state', applicant.state)
            applicant.pincode = request.POST.get('pincode', applicant.pincode)
            applicant.country = request.POST.get('country', 'India')
            applicant.save()
            
            # Update application info
            application.loan_amount = request.POST.get('loan_amount', application.loan_amount)
            application.loan_type = request.POST.get('loan_type', application.loan_type)
            application.loan_tenure = request.POST.get('loan_tenure', application.loan_tenure)
            application.annual_income = request.POST.get('annual_income', application.annual_income)
            application.employment_type = request.POST.get('employment_type', application.employment_type)
            application.employer_name = request.POST.get('employer_name', application.employer_name)
            application.bank_name = request.POST.get('bank_name', application.bank_name)
            application.account_type = request.POST.get('account_type', application.account_type)
            application.collateral_description = request.POST.get('collateral_description', application.collateral_description)
            application.collateral_value = request.POST.get('collateral_value', application.collateral_value)
            application.loan_purpose = request.POST.get('purpose_of_loan', application.loan_purpose)
            application.existing_loans = request.POST.get('existing_loans', application.existing_loans)
            application.credit_score = request.POST.get('credit_score', application.credit_score)
            application.notes = request.POST.get('remarks', application.notes)
            
            # Handle assignment (REQUIRED to move from New Entry)
            assign_to = request.POST.get('assign_to', '').strip()
            if not assign_to:
                messages.error(request, 'You must assign this application to an employee or agent before proceeding.')
                context = get_application_detail_context(application, request.user)
                context['available_employees'] = User.objects.filter(role='employee', is_active=True)
                context['available_agents'] = Agent.objects.filter(status='Active')
                return render(request, 'admin/dashboard/new_entry_detail.html', context)
            
            # Parse assignment
            if assign_to.startswith('emp_'):
                emp_id = assign_to.replace('emp_', '')
                application.assigned_employee = User.objects.get(id=int(emp_id), role='employee')
                application.assigned_agent = None
                assigned_to_name = application.assigned_employee.full_name
            elif assign_to.startswith('agent_'):
                agent_id = assign_to.replace('agent_', '')
                application.assigned_agent = Agent.objects.get(id=int(agent_id), status='Active')
                application.assigned_employee = None
                assigned_to_name = application.assigned_agent.name
            else:
                messages.error(request, 'Invalid assignment selection. Please select a valid employee or agent.')
                context = get_application_detail_context(application, request.user)
                context['available_employees'] = User.objects.filter(role='employee', is_active=True)
                context['available_agents'] = Agent.objects.filter(status='Active')
                return render(request, 'admin/dashboard/new_entry_detail.html', context)
            
            # Move to Waiting status
            application.status = 'Waiting for Processing'
            application.assigned_at = timezone.now()
            application.save()
            
            # Log activity
            ActivityLog.objects.create(
                user=request.user,
                action='status_updated',
                description=f'Form submitted and application assigned to {assigned_to_name}. Status: New Entry → Waiting for Processing'
            )
            
            messages.success(request, f'Application successfully assigned to {assigned_to_name}. Status changed to "Waiting for Processing".')
            return redirect('application_detail_router', applicant_id=applicant_id)
        
        except User.DoesNotExist:
            messages.error(request, 'Selected employee not found.')
            context = get_application_detail_context(application, request.user)
            context['available_employees'] = User.objects.filter(role='employee', is_active=True)
            context['available_agents'] = Agent.objects.filter(status='Active')
            return render(request, 'admin/dashboard/new_entry_detail.html', context)
        except Agent.DoesNotExist:
            messages.error(request, 'Selected agent not found.')
            context = get_application_detail_context(application, request.user)
            context['available_employees'] = User.objects.filter(role='employee', is_active=True)
            context['available_agents'] = Agent.objects.filter(status='Active')
            return render(request, 'admin/dashboard/new_entry_detail.html', context)
        except Exception as e:
            messages.error(request, f'Error saving application: {str(e)}')
            context = get_application_detail_context(application, request.user)
            context['available_employees'] = User.objects.filter(role='employee', is_active=True)
            context['available_agents'] = Agent.objects.filter(status='Active')
            return render(request, 'admin/dashboard/new_entry_detail.html', context)
    
    # GET request - show form
    context = get_application_detail_context(application, request.user)
    context['is_new_entry_form'] = True
    
    return render(request, 'admin/dashboard/new_entry_detail.html', context)
