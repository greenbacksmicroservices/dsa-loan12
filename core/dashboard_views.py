"""
DSA LOS - Dashboard Views & Status Management
Production-ready status-based UI control with 24-hour auto-follow-up logic
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q, F
from django.utils import timezone
from django.http import JsonResponse
from datetime import timedelta
import json

from .models import User, Agent, LoanApplication, Applicant, ActivityLog
from .decorators import admin_required


# ============================================================================
# UTILITY FUNCTIONS - Status & Permission Checks
# ============================================================================

def can_access_new_entry(user):
    """Only admin can access new entry (form editing)"""
    return user.is_authenticated and user.role == 'admin'


def can_access_waiting(user, loan_app=None):
    """
    Waiting view access:
    - Admin: Can see all
    - Employee/Agent: Can see only assigned
    """
    if not user.is_authenticated:
        return False
    
    if user.role == 'admin':
        return True
    
    if loan_app is None:
        return False
    
    if user.role == 'employee':
        return loan_app.assigned_employee == user
    elif user.role == 'agent':
        return loan_app.assigned_agent == user.agent_profile
    
    return False


def can_access_followup(user):
    """Follow-up access: Admin only"""
    return user.is_authenticated and user.role == 'admin'


def can_access_approved_rejected(user):
    """Approved/Rejected access: Admin only"""
    return user.is_authenticated and user.role == 'admin'


def can_access_disbursed(user):
    """Disbursed access: Admin and Finance team"""
    return user.is_authenticated and user.role in ['admin', 'finance']


def prevent_form_rendering(status):
    """
    CRITICAL: Prevent form rendering unless status is 'New Entry'
    Returns True if form should be shown, False otherwise
    """
    return status == 'New Entry'


def check_and_move_to_followup():
    """
    Celery-like background task (can be called via cron or Celery)
    Auto-move applications from Waiting to Follow-up after 24 hours
    """
    cutoff_time = timezone.now() - timedelta(hours=24)
    
    # Find all waiting applications assigned >24 hours ago with no action
    applications_to_move = LoanApplication.objects.filter(
        status='Waiting for Processing',
        assigned_at__lt=cutoff_time,
        approved_at__isnull=True,
        rejected_at__isnull=True
    )
    
    moved_count = 0
    for app in applications_to_move:
        app.status = 'Required Follow-up'
        app.follow_up_scheduled_at = timezone.now()
        app.follow_up_count = (app.follow_up_count or 0) + 1
        app.save()
        
        ActivityLog.objects.create(
            action='status_updated',
            description=f"Auto-moved {app.applicant.full_name} from Waiting to Follow-up (24hr timeout)",
            user=None  # System action
        )
        moved_count += 1
    
    return moved_count


# ============================================================================
# ADMIN SECTION - New Entry (FORM + ASSIGN)
# ============================================================================

@login_required
@admin_required
def admin_new_entry(request):
    """
    Admin New Entries LIST (READ-ONLY TABLE)
    ✅ Shows table of new applications
    ✅ View only - no form editing
    ✅ Click to view details + assign only
    ✅ Only status = 'New Entry'
    """
    # Get all new entry applications
    applications = LoanApplication.objects.filter(
        status='New Entry'
    ).select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'applications': applications,
        'app_count': applications.count(),
        'section': 'new_entry',
        'can_edit_form': False,
        'can_assign': False,
        'show_form': False,
    }
    
    return render(request, 'core/admin/new_entries_list.html', context)


@login_required
@admin_required
def admin_new_entry_detail(request, applicant_id):
    """
    New Entry APPLICATION DETAIL (READ-ONLY + ASSIGN ONLY)
    ✅ View all application data
    ✅ View documents with download
    ✅ Assign to employee dropdown
    ❌ NO form editing
    ❌ NO data modification
    """
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        
        # CRITICAL CHECK: Must be New Entry status
        if loan_app.status != 'New Entry':
            messages.error(request, f'This application is {loan_app.status}, not New Entry.')
            return redirect('admin_new_entry')
        
        # Check permission
        if not can_access_new_entry(request.user):
            messages.error(request, 'Only admins can view new entries.')
            return redirect('admin_dashboard')
        
        documents = loan_app.documents.all()
        employees = User.objects.filter(role='employee', is_active=True)
        
        context = {
            'applicant': applicant,
            'loan_app': loan_app,
            'documents': documents,
            'employees': employees,
            'section': 'new_entry',
            'can_edit_form': False,
            'can_assign': True,  # ONLY assignment allowed
            'show_form': False,  # EXPLICIT: NO form
            'readonly': True,
        }
        
        return render(request, 'core/admin/loan_detail.html', context)
    
    except Applicant.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('admin_new_entry')


# ============================================================================
# EMPLOYEE/AGENT SECTION - Waiting for Processing (READ-ONLY + APPROVE/REJECT)
# ============================================================================

@login_required
def waiting_for_processing_list(request):
    """
    Waiting for Processing LIST view
    ✅ Table-based view (NOT form)
    ✅ Employee sees only assigned
    ✅ Admin sees all
    """
    
    # Role-based filtering
    if request.user.role == 'admin':
        applications = LoanApplication.objects.filter(
            status='Waiting for Processing'
        )
    elif request.user.role == 'employee':
        applications = LoanApplication.objects.filter(
            status='Waiting for Processing',
            assigned_employee=request.user
        )
    elif request.user.role == 'agent':
        agent = request.user.agent_profile
        applications = LoanApplication.objects.filter(
            status='Waiting for Processing',
            assigned_agent=agent
        )
    else:
        return redirect('login')
    
    applications = applications.select_related(
        'applicant', 'assigned_employee', 'assigned_agent'
    ).order_by('-assigned_at')
    
    context = {
        'applications': applications,
        'app_count': applications.count(),
        'section': 'waiting',
        'show_form': False,  # EXPLICIT: No form in waiting
        'can_edit_form': False,
        'can_approve_reject': True,
    }
    
    return render(request, 'dashboard/waiting_list.html', context)


@login_required
def waiting_for_processing_detail(request, applicant_id):
    """
    Waiting for Processing DETAIL view
    ✅ Read-only details
    ✅ Approve/Reject buttons
    ❌ NO form
    ❌ NO assignment UI
    """
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        
        # CRITICAL CHECK: Must be Waiting status
        if loan_app.status != 'Waiting for Processing':
            messages.error(request, f'This application is {loan_app.status}.')
            return redirect('waiting_for_processing_list')
        
        # CRITICAL CHECK: Permission (assigned only or admin)
        if not can_access_waiting(request.user, loan_app):
            messages.error(request, 'You do not have access to this application.')
            return redirect('waiting_for_processing_list')
        
        documents = loan_app.documents.all()
        waiting_hours = (timezone.now() - loan_app.assigned_at).total_seconds() / 3600 if loan_app.assigned_at else 0
        
        context = {
            'applicant': applicant,
            'loan_app': loan_app,
            'documents': documents,
            'section': 'waiting',
            'show_form': False,  # EXPLICIT: No form
            'can_edit_form': False,  # EXPLICIT: Read-only
            'can_approve_reject': True,
            'waiting_hours': waiting_hours,
        }
        
        return render(request, 'dashboard/waiting_detail.html', context)
    
    except Applicant.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('waiting_for_processing_list')


# ============================================================================
# ADMIN SECTION - Required Follow-up (TABLE + REASSIGN)
# ============================================================================

@login_required
@admin_required
def required_followup_list(request):
    """
    Required Follow-up LIST view
    ✅ Table-based view (NOT form)
    ✅ Admin only
    ✅ Shows delay metrics
    """
    
    applications = LoanApplication.objects.filter(
        status='Required Follow-up'
    ).select_related(
        'applicant', 'assigned_employee', 'assigned_agent'
    ).order_by('-follow_up_scheduled_at')
    
    # Add delay calculation
    app_list = []
    for app in applications:
        delay_hours = (timezone.now() - app.follow_up_scheduled_at).total_seconds() / 3600 if app.follow_up_scheduled_at else 0
        app_list.append({
            'obj': app,
            'delay_hours': int(delay_hours),
            'is_overdue': delay_hours > 24,
        })
    
    context = {
        'applications': app_list,
        'app_count': len(app_list),
        'section': 'followup',
        'show_form': False,  # EXPLICIT: No form
        'can_edit_form': False,
        'can_reassign': True,
    }
    
    return render(request, 'admin/dashboard/followup_list.html', context)


@login_required
@admin_required
def required_followup_detail(request, applicant_id):
    """
    Required Follow-up DETAIL view
    ✅ Read-only summary
    ✅ Reassign button
    ✅ Force approve/reject
    ❌ NO form
    """
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        
        # CRITICAL CHECK: Must be Follow-up status
        if loan_app.status != 'Required Follow-up':
            messages.error(request, f'This application is {loan_app.status}.')
            return redirect('required_followup_list')
        
        documents = loan_app.documents.all()
        agents = Agent.objects.filter(status='active')
        employees = User.objects.filter(role='employee', is_active=True)
        
        context = {
            'applicant': applicant,
            'loan_app': loan_app,
            'documents': documents,
            'agents': agents,
            'employees': employees,
            'section': 'followup',
            'show_form': False,  # EXPLICIT: No form
            'can_edit_form': False,
            'can_reassign': True,
        }
        
        return render(request, 'admin/dashboard/followup_detail.html', context)
    
    except Applicant.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('required_followup_list')


# ============================================================================
# ADMIN SECTION - Approved (READ-ONLY TABLE)
# ============================================================================

@login_required
@admin_required
def approved_applications(request):
    """
    Approved Applications LIST view
    ✅ Table-based view (NOT form)
    ✅ Read-only
    ✅ Admin only
    """
    
    applications = LoanApplication.objects.filter(
        status='Approved'
    ).select_related(
        'applicant', 'approved_by'
    ).order_by('-approved_at')
    
    context = {
        'applications': applications,
        'app_count': applications.count(),
        'section': 'approved',
        'show_form': False,  # EXPLICIT: No form
        'can_edit_form': False,
    }
    
    return render(request, 'admin/dashboard/approved_list.html', context)


# ============================================================================
# ADMIN SECTION - Rejected (READ-ONLY TABLE)
# ============================================================================

@login_required
@admin_required
def rejected_applications(request):
    """
    Rejected Applications LIST view
    ✅ Table-based view (NOT form)
    ✅ Read-only
    ✅ Admin only
    """
    
    applications = LoanApplication.objects.filter(
        status='Rejected'
    ).select_related(
        'applicant', 'rejected_by'
    ).order_by('-rejected_at')
    
    context = {
        'applications': applications,
        'app_count': applications.count(),
        'section': 'rejected',
        'show_form': False,  # EXPLICIT: No form
        'can_edit_form': False,
    }
    
    return render(request, 'admin/dashboard/rejected_list.html', context)


# ============================================================================
# ADMIN/FINANCE SECTION - Disbursed (FINANCE TABLE)
# ============================================================================

@login_required
def disbursed_applications(request):
    """
    Disbursed Applications LIST view (Finance Summary)
    ✅ Table-based view (NOT form)
    ✅ Finance-specific columns
    ✅ Admin and Finance only
    """
    
    if request.user.role not in ['admin', 'finance']:
        messages.error(request, 'Only finance team can access this.')
        return redirect('dashboard')
    
    applications = LoanApplication.objects.filter(
        status='Disbursed'
    ).select_related(
        'applicant', 'approved_by'
    ).order_by('-approved_at')
    
    context = {
        'applications': applications,
        'app_count': applications.count(),
        'section': 'disbursed',
        'show_form': False,  # EXPLICIT: No form
        'can_edit_form': False,
    }
    
    return render(request, 'admin/dashboard/disbursed_list.html', context)


# ============================================================================
# AJAX - Real-time Dashboard Counts
# ============================================================================

@login_required
def get_dashboard_counts(request):
    """
    AJAX endpoint for real-time dashboard counts
    Returns JSON with counts for all sections
    """
    
    counts = {
        'new_entry': 0,
        'waiting': 0,
        'followup': 0,
        'approved': 0,
        'rejected': 0,
        'disbursed': 0,
    }
    
    if request.user.role == 'admin':
        counts['new_entry'] = LoanApplication.objects.filter(status='New Entry').count()
        counts['waiting'] = LoanApplication.objects.filter(status='Waiting for Processing').count()
        counts['followup'] = LoanApplication.objects.filter(status='Required Follow-up').count()
        counts['approved'] = LoanApplication.objects.filter(status='Approved').count()
        counts['rejected'] = LoanApplication.objects.filter(status='Rejected').count()
        counts['disbursed'] = LoanApplication.objects.filter(status='Disbursed').count()
    
    elif request.user.role == 'employee':
        counts['waiting'] = LoanApplication.objects.filter(
            status='Waiting for Processing',
            assigned_employee=request.user
        ).count()
    
    elif request.user.role == 'agent':
        agent = request.user.agent_profile
        counts['waiting'] = LoanApplication.objects.filter(
            status='Waiting for Processing',
            assigned_agent=agent
        ).count()
    
    return JsonResponse(counts)


@login_required
def get_dashboard_stats(request):
    """
    AJAX endpoint for detailed dashboard statistics
    Returns JSON with status distribution and metrics
    """
    
    if request.user.role == 'admin':
        stats = {
            'total_applications': LoanApplication.objects.count(),
            'pending': LoanApplication.objects.filter(
                status__in=['New Entry', 'Waiting for Processing', 'Required Follow-up']
            ).count(),
            'completed': LoanApplication.objects.filter(
                status__in=['Approved', 'Rejected', 'Disbursed']
            ).count(),
            'approval_rate': f"{(LoanApplication.objects.filter(status='Approved').count() / max(LoanApplication.objects.count(), 1) * 100):.1f}%",
            'avg_processing_time': '24 hours',  # Can be calculated from timestamps
        }
    elif request.user.role == 'employee':
        stats = {
            'assigned_count': LoanApplication.objects.filter(
                assigned_employee=request.user,
                status__in=['Waiting for Processing', 'Required Follow-up']
            ).count(),
            'approved_by_me': LoanApplication.objects.filter(
                approved_by=request.user
            ).count(),
            'rejected_by_me': LoanApplication.objects.filter(
                rejected_by=request.user
            ).count(),
        }
    elif request.user.role == 'agent':
        agent = request.user.agent_profile
        stats = {
            'assigned_count': LoanApplication.objects.filter(
                assigned_agent=agent,
                status__in=['Waiting for Processing', 'Required Follow-up']
            ).count(),
            'approved_count': LoanApplication.objects.filter(
                assigned_agent=agent,
                status='Approved'
            ).count(),
        }
    else:
        stats = {}
    
    return JsonResponse(stats)


# ============================================================================
# HELPER - Check and trigger 24-hour auto follow-up
# ============================================================================

@login_required
@admin_required
def trigger_followup_check(request):
    """
    Admin endpoint to manually trigger 24-hour check
    (In production, use Celery beat or cron job)
    """
    moved_count = check_and_move_to_followup()
    messages.success(request, f'Moved {moved_count} applications to Follow-up.')
    return redirect('required_followup_list')


# ============================================================================
# REQUIRED FOLLOW-UP DETAIL VIEW - Admin only
# ============================================================================

@login_required
@admin_required
def required_followup_detail(request, applicant_id):
    """
    Read-only detail view for required follow-up applications
    Admin can reassign or force approve from here
    """
    try:
        application = LoanApplication.objects.select_related(
            'applicant', 'assigned_employee', 'assigned_agent'
        ).get(applicant__id=applicant_id)
    except LoanApplication.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('required_followup_list')
    
    # Status validation
    if application.status != 'Required Follow-up':
        messages.warning(request, 'Application status has changed.')
        return redirect('required_followup_list')
    
    # Calculate follow-up delay
    if application.assigned_at:
        delay_hours = int((timezone.now() - application.assigned_at).total_seconds() / 3600)
    else:
        delay_hours = 0
    
    context = {
        'application': application,
        'can_edit_form': False,
        'can_reassign': True,
        'delay_hours': delay_hours,
        'available_employees': User.objects.filter(role='employee'),
        'available_agents': Agent.objects.filter(status='Active'),
    }
    
    return render(request, 'admin/dashboard/followup_detail.html', context)


# ============================================================================
# APPROVED DETAIL VIEW - Admin only
# ============================================================================

@login_required
@admin_required
def approved_detail(request, applicant_id):
    """
    Read-only detail view for approved applications
    Shows approval information and readiness for disbursement
    """
    try:
        application = LoanApplication.objects.select_related(
            'applicant', 'approved_by'
        ).get(applicant__id=applicant_id)
    except LoanApplication.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('approved_list')
    
    # Status validation
    if application.status != 'Approved':
        messages.warning(request, 'Application status has changed.')
        return redirect('approved_list')
    
    context = {
        'application': application,
        'can_edit_form': False,
    }
    
    return render(request, 'admin/dashboard/approved_detail.html', context)


# ============================================================================
# REJECTED DETAIL VIEW - Admin only
# ============================================================================

@login_required
@admin_required
def rejected_detail(request, applicant_id):
    """
    Read-only detail view for rejected applications
    Shows rejection reason and details (final status)
    """
    try:
        application = LoanApplication.objects.select_related(
            'applicant', 'rejected_by'
        ).get(applicant__id=applicant_id)
    except LoanApplication.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('rejected_list')
    
    # Status validation
    if application.status != 'Rejected':
        messages.warning(request, 'Application status has changed.')
        return redirect('rejected_list')
    
    context = {
        'application': application,
        'can_edit_form': False,
    }
    
    return render(request, 'admin/dashboard/rejected_detail.html', context)


# ============================================================================
# DISBURSED DETAIL VIEW - Finance only
# ============================================================================

@login_required
def disbursed_detail(request, applicant_id):
    """
    Read-only detail view for disbursed applications
    Finance-specific: Shows bank details, UTR, transfer verification
    """
    # Permission check
    if request.user.role not in ['admin', 'finance']:
        messages.error(request, 'You do not have permission to view this.')
        return redirect('dashboard')
    
    try:
        application = LoanApplication.objects.select_related(
            'applicant'
        ).get(applicant__id=applicant_id)
    except LoanApplication.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('disbursed_list')
    
    # Status validation
    if application.status != 'Disbursed':
        messages.warning(request, 'Application status has changed.')
        return redirect('disbursed_list')
    
    context = {
        'application': application,
        'can_edit_form': False,
    }
    
    return render(request, 'admin/dashboard/disbursed_detail.html', context)


# ============================================================================
# REASSIGN FOLLOW-UP TO NEW EMPLOYEE - Admin only
# ============================================================================

@login_required
@admin_required
def reassign_followup_employee(request, applicant_id):
    """
    Reassign a follow-up application to a new employee
    Changes status back to "Waiting for Processing"
    """
    if request.method != 'POST':
        return redirect('required_followup_detail', applicant_id=applicant_id)
    
    try:
        application = LoanApplication.objects.get(applicant__id=applicant_id)
        employee_id = request.POST.get('employee_id')
        
        if not employee_id:
            messages.error(request, 'Please select an employee.')
            return redirect('required_followup_detail', applicant_id=applicant_id)
        
        try:
            new_employee = User.objects.get(id=employee_id, role='employee', is_active=True)
        except User.DoesNotExist:
            messages.error(request, 'Selected employee is not valid.')
            return redirect('required_followup_detail', applicant_id=applicant_id)
        
        # Update assignment
        application.assigned_employee = new_employee
        application.assigned_by = request.user
        application.assigned_at = timezone.now()
        application.status = 'Waiting for Processing'  # Change status back to Waiting for Processing
        application.save()
        
        messages.success(request, f'Application reassigned to {new_employee.first_name} {new_employee.last_name}. Status changed to "Waiting for Processing".')
        return redirect('required_followup_list')
        
    except LoanApplication.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('required_followup_list')
