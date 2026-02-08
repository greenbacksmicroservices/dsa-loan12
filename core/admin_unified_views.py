"""
Unified Admin Views for New Entries and Loan Details
Implements complete loan lifecycle workflow with real-time updates
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count
from django.utils import timezone
from django.http import JsonResponse
import re


def get_status_css_class(status_string):
    """Convert status string to CSS-safe class name
    Example: 'New Entry' -> 'new-entry', 'Waiting for Processing' -> 'waiting-for-processing'
    """
    return re.sub(r'[^a-z0-9]+', '-', status_string.lower()).strip('-')
from django.views.decorators.http import require_POST, require_http_methods
from datetime import timedelta
from .models import Applicant, LoanApplication, ApplicantDocument, Agent, User
from .decorators import admin_required


@admin_required
def admin_new_entries(request):
    """
    Unified New Entries page - Shows all NEW Entry applications
    Accessible from both dashboard cards and sidebar menu
    Features:
    - List all new applications submitted by agents
    - Show which agent submitted the application
    - Click to view full details with documents
    - Admin can assign to employee
    """
    # Get filter from query params
    page = request.GET.get('page', 1)
    search = request.GET.get('search', '')
    sort_by = request.GET.get('sort', '-created_at')  # -created_at, loan_amount, applicant__full_name
    
    # Get all NEW Entry applications
    applications = LoanApplication.objects.filter(
        status='New Entry'
    ).select_related('applicant', 'assigned_agent', 'assigned_employee').prefetch_related('documents')
    
    # Apply search filter
    if search:
        applications = applications.filter(
            Q(applicant__full_name__icontains=search) |
            Q(applicant__email__icontains=search) |
            Q(applicant__mobile__icontains=search)
        )
    
    # Apply sorting
    valid_sorts = ['-created_at', 'created_at', 'loan_amount', '-loan_amount', 'applicant__full_name']
    if sort_by not in valid_sorts:
        sort_by = '-created_at'
    
    applications = applications.order_by(sort_by)
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(applications, 25)
    page_obj = paginator.get_page(page)
    
    context = {
        'page_title': 'New Loan Applications',
        'page_obj': page_obj,
        'applications': page_obj.object_list,
        'search': search,
        'sort_by': sort_by,
        'total_count': paginator.count,
    }
    
    return render(request, 'core/admin/new_entries_list.html', context)


@admin_required
def admin_loan_detail(request, applicant_id):
    """
    Loan Application Detail View (READ-ONLY)
    Shows complete application with:
    - Full applicant and loan details (read-only)
    - All documents (view/download capability)
    ❌ NO edit capability
    - Assignment to employee (ONLY control)
    - Status tracking
    """
    applicant = get_object_or_404(Applicant, id=applicant_id)
    loan_app = applicant.loan_application
    documents = loan_app.documents.all()
    employees = User.objects.filter(role='employee', is_active=True).order_by('first_name')
    
    # Calculate hours since assignment
    hours_since_assignment = None
    follow_up_due = None
    is_overdue = False
    
    if loan_app.assigned_at and loan_app.status == 'Waiting for Processing':
        time_diff = timezone.now() - loan_app.assigned_at
        hours_since_assignment = int(time_diff.total_seconds() / 3600)
        minutes_since = int((time_diff.total_seconds() % 3600) / 60)
        follow_up_due = loan_app.assigned_at + timedelta(hours=24)
        is_overdue = timezone.now() > follow_up_due
    
    # Get application status history if available
    status_history = []
    if hasattr(loan_app, 'status_history'):
        status_history = loan_app.status_history.all().order_by('-changed_at')
    
    context = {
        'page_title': f'Loan Application - {applicant.full_name}',
        'applicant': applicant,
        'loan_app': loan_app,
        'documents': documents,
        'employees': employees,
        'hours_since_assignment': hours_since_assignment,
        'follow_up_due': follow_up_due,
        'is_overdue': is_overdue,
        'status_history': status_history,
        'status_css_class': get_status_css_class(loan_app.status),
        'can_edit': False,  # NO EDIT - READ-ONLY ONLY
        'can_assign': loan_app.status == 'New Entry' and not loan_app.assigned_employee,
        'can_upload_docs': False,  # NO UPLOADS
        'readonly': True,  # EXPLICIT READ-ONLY
    }
    
    return render(request, 'core/admin/loan_detail.html', context)


@admin_required
@require_POST
def admin_assign_employee(request, applicant_id):
    """
    Assign loan application to employee
    Changes status from 'New Entry' to 'Waiting for Processing'
    Records assignment timestamp
    """
    applicant = get_object_or_404(Applicant, id=applicant_id)
    loan_app = applicant.loan_application
    
    # Only allow assignment for New Entry status
    if loan_app.status != 'New Entry':
        return JsonResponse({'success': False, 'message': 'Application must be in New Entry status'}, status=400)
    
    employee_id = request.POST.get('employee_id')
    if not employee_id:
        return JsonResponse({'success': False, 'message': 'Employee ID required'}, status=400)
    
    try:
        employee = User.objects.get(id=employee_id, role='employee', is_active=True)
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Invalid employee selected'}, status=400)
    
    # Update loan application
    loan_app.assigned_employee = employee
    loan_app.assigned_at = timezone.now()
    loan_app.assigned_by = request.user
    loan_app.status = 'Waiting for Processing'
    loan_app.save()
    
    messages.success(request, f'Application assigned to {employee.get_full_name() or employee.username}')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Assignment successful'})
    
    return redirect('admin_loan_detail', applicant_id=applicant_id)


@admin_required
def admin_loan_details_all(request):
    """
    Unified Loan Details page - accessible from sidebar
    Shows all loans across all statuses with:
    - Status, applicant name, loan type, assigned employee
    - Date assigned, hours since assignment
    - Follow-up due date and overdue indicator
    - Quick action buttons
    - Real-time data persistence
    """
    # Get filters from query params
    page = request.GET.get('page', 1)
    status_filter = request.GET.get('status', '')  # Filter by status
    search = request.GET.get('search', '')
    sort_by = request.GET.get('sort', '-created_at')
    only_overdue = request.GET.get('overdue', '') == '1'
    
    # Base queryset
    loans = LoanApplication.objects.select_related(
        'applicant', 'assigned_employee', 'assigned_agent', 'assigned_by'
    ).prefetch_related('documents')
    
    # Apply status filter
    if status_filter:
        loans = loans.filter(status=status_filter)
    
    # Apply search
    if search:
        loans = loans.filter(
            Q(applicant__full_name__icontains=search) |
            Q(applicant__email__icontains=search) |
            Q(applicant__mobile__icontains=search)
        )
    
    # Apply overdue filter
    if only_overdue:
        # Only show loans waiting for processing that are overdue 24 hours
        loans = loans.filter(status='Waiting for Processing', assigned_at__lt=timezone.now() - timedelta(hours=24))
    
    # Apply sorting
    valid_sorts = ['-created_at', 'created_at', 'applicant__full_name', 'loan_amount', '-loan_amount']
    if sort_by not in valid_sorts:
        sort_by = '-created_at'
    
    loans = loans.order_by(sort_by)
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(loans, 30)
    page_obj = paginator.get_page(page)
    
    # Add computed fields for each loan
    loan_list = []
    for loan in page_obj.object_list:
        hours_since = None
        follow_up_due = None
        is_overdue = False
        
        if loan.assigned_at and loan.status == 'Waiting for Processing':
            time_diff = timezone.now() - loan.assigned_at
            hours_since = int(time_diff.total_seconds() / 3600)
            follow_up_due = loan.assigned_at + timedelta(hours=24)
            is_overdue = timezone.now() > follow_up_due
        
        loan_list.append({
            'loan': loan,
            'hours_since_assignment': hours_since,
            'follow_up_due': follow_up_due,
            'is_overdue': is_overdue,
            'status_css_class': get_status_css_class(loan.status),
        })
    
    # Get status counts
    status_counts = {
        'new_entry': LoanApplication.objects.filter(status='New Entry').count(),
        'waiting': LoanApplication.objects.filter(status='Waiting for Processing').count(),
        'followup': LoanApplication.objects.filter(status='Required Follow-up').count(),
        'approved': LoanApplication.objects.filter(status='Approved').count(),
        'rejected': LoanApplication.objects.filter(status='Rejected').count(),
        'disbursed': LoanApplication.objects.filter(status='Disbursed').count(),
    }
    
    overdue_count = LoanApplication.objects.filter(
        status='Waiting for Processing',
        assigned_at__lt=timezone.now() - timedelta(hours=24)
    ).count()
    
    context = {
        'page_title': 'All Loan Details',
        'page_obj': page_obj,
        'loan_list': loan_list,
        'search': search,
        'status_filter': status_filter,
        'sort_by': sort_by,
        'total_count': paginator.count,
        'status_counts': status_counts,
        'overdue_count': overdue_count,
        'only_overdue': only_overdue,
    }
    
    return render(request, 'core/admin/loan_details_all.html', context)


@admin_required
@require_http_methods(["GET", "POST"])
def admin_edit_application(request, applicant_id):
    """
    Edit loan application details (admin only)
    Only allowed for New Entry status
    """
    applicant = get_object_or_404(Applicant, id=applicant_id)
    loan_app = applicant.loan_application
    
    # Only allow editing for New Entry status
    if loan_app.status != 'New Entry':
        messages.error(request, 'Only New Entry applications can be edited')
        return redirect('admin_loan_detail', applicant_id=applicant_id)
    
    if request.method == 'POST':
        # Update applicant details
        applicant.full_name = request.POST.get('full_name', applicant.full_name)
        applicant.mobile = request.POST.get('mobile', applicant.mobile)
        applicant.email = request.POST.get('email', applicant.email)
        applicant.city = request.POST.get('city', applicant.city)
        applicant.state = request.POST.get('state', applicant.state)
        applicant.pin_code = request.POST.get('pin_code', applicant.pin_code)
        applicant.save()
        
        # Update loan details
        loan_app.loan_type = request.POST.get('loan_type', loan_app.loan_type)
        loan_app.loan_amount = request.POST.get('loan_amount', loan_app.loan_amount)
        loan_app.tenure_months = request.POST.get('tenure_months', loan_app.tenure_months)
        loan_app.interest_rate = request.POST.get('interest_rate', loan_app.interest_rate)
        loan_app.bank_name = request.POST.get('bank_name', loan_app.bank_name)
        loan_app.account_number = request.POST.get('account_number', loan_app.account_number)
        loan_app.ifsc_code = request.POST.get('ifsc_code', loan_app.ifsc_code)
        loan_app.save()
        
        # Recalculate EMI
        applicant.calculate_emi()
        applicant.save()
        
        messages.success(request, 'Application updated successfully')
        return redirect('admin_loan_detail', applicant_id=applicant_id)
    
    context = {
        'page_title': f'Edit Application - {applicant.full_name}',
        'applicant': applicant,
        'loan_app': loan_app,
    }
    
    return render(request, 'core/admin/edit_application.html', context)


@admin_required
@require_POST
def admin_upload_document(request, applicant_id):
    """
    Upload or update document for loan application
    """
    applicant = get_object_or_404(Applicant, id=applicant_id)
    loan_app = applicant.loan_application
    
    document_type = request.POST.get('document_type')
    file = request.FILES.get('file')
    
    if not document_type or not file:
        return JsonResponse({'success': False, 'message': 'Document type and file required'}, status=400)
    
    try:
        # Delete existing document of this type
        loan_app.documents.filter(document_type=document_type).delete()
        
        # Create new document
        doc = ApplicantDocument.objects.create(
            loan_application=loan_app,
            document_type=document_type,
            file=file
        )
        
        messages.success(request, f'{document_type.replace("_", " ").title()} uploaded successfully')
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'document_id': doc.id})
        
        return redirect('admin_loan_detail', applicant_id=applicant_id)
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)


@admin_required
def admin_trigger_followup(request, applicant_id):
    """
    Manually trigger follow-up for application
    Changes status from 'Waiting for Processing' to 'Required Follow-up'
    """
    applicant = get_object_or_404(Applicant, id=applicant_id)
    loan_app = applicant.loan_application
    
    if loan_app.status != 'Waiting for Processing':
        messages.error(request, 'Follow-up can only be triggered for Waiting status')
        return redirect('admin_loan_detail', applicant_id=applicant_id)
    
    loan_app.status = 'Required Follow-up'
    loan_app.save()
    
    messages.success(request, 'Application moved to Follow-up status')
    return redirect('admin_loan_detail', applicant_id=applicant_id)


@admin_required
def admin_update_status(request, applicant_id):
    """
    Update loan status (for admin manual intervention)
    Allowed statuses: New Entry, Waiting for Processing, Required Follow-up, Approved, Rejected, Disbursed
    """
    if request.method != 'POST':
        return redirect('admin_loan_detail', applicant_id=applicant_id)
    
    applicant = get_object_or_404(Applicant, id=applicant_id)
    loan_app = applicant.loan_application
    
    new_status = request.POST.get('status')
    valid_statuses = ['New Entry', 'Waiting for Processing', 'Required Follow-up', 'Approved', 'Rejected', 'Disbursed']
    
    if new_status not in valid_statuses:
        messages.error(request, 'Invalid status')
        return redirect('admin_loan_detail', applicant_id=applicant_id)
    
    old_status = loan_app.status
    loan_app.status = new_status
    loan_app.save()
    
    messages.success(request, f'Status updated from "{old_status}" to "{new_status}"')
    return redirect('admin_loan_detail', applicant_id=applicant_id)


# API Endpoints for Real-time Updates

@admin_required
def api_dashboard_stats(request):
    """
    API endpoint for real-time dashboard statistics
    Returns count of loans in each status
    Used for AJAX polling to update dashboard cards
    """
    stats = {
        'new_entry': LoanApplication.objects.filter(status='New Entry').count(),
        'waiting': LoanApplication.objects.filter(status='Waiting for Processing').count(),
        'followup': LoanApplication.objects.filter(status='Required Follow-up').count(),
        'approved': LoanApplication.objects.filter(status='Approved').count(),
        'rejected': LoanApplication.objects.filter(status='Rejected').count(),
        'disbursed': LoanApplication.objects.filter(status='Disbursed').count(),
        'overdue': LoanApplication.objects.filter(
            status='Waiting for Processing',
            assigned_at__lt=timezone.now() - timedelta(hours=24)
        ).count(),
        'timestamp': timezone.now().isoformat(),
    }
    
    return JsonResponse(stats)


@admin_required
def api_loan_list(request):
    """
    API endpoint for loan list with filtering
    Supports: status, search, sort, limit, offset
    Returns JSON for dynamic table updates
    """
    status_filter = request.GET.get('status', '')
    search = request.GET.get('search', '')
    limit = min(int(request.GET.get('limit', '50')), 100)
    offset = int(request.GET.get('offset', '0'))
    
    loans = LoanApplication.objects.select_related('applicant', 'assigned_employee')
    
    if status_filter:
        loans = loans.filter(status=status_filter)
    
    if search:
        loans = loans.filter(
            Q(applicant__full_name__icontains=search) |
            Q(applicant__email__icontains=search)
        )
    
    total = loans.count()
    loans = loans.order_by('-created_at')[offset:offset + limit]
    
    data = {
        'total': total,
        'count': len(loans),
        'offset': offset,
        'limit': limit,
        'loans': [
            {
                'id': loan.id,
                'applicant_name': loan.applicant.full_name,
                'loan_type': loan.loan_type,
                'loan_amount': str(loan.loan_amount),
                'status': loan.status,
                'assigned_employee': loan.assigned_employee.get_full_name() if loan.assigned_employee else 'Unassigned',
                'created_at': loan.created_at.isoformat(),
            }
            for loan in loans
        ]
    }
    
    return JsonResponse(data)


@admin_required
@require_http_methods(["POST"])
def admin_update_application(request, applicant_id):
    """
    Update applicant information inline from loan detail page
    Accepts POST request with updated fields
    """
    try:
        applicant = get_object_or_404(Applicant, id=applicant_id)
        
        # Update applicant fields
        applicant.full_name = request.POST.get('full_name', applicant.full_name)
        applicant.mobile = request.POST.get('mobile', applicant.mobile)
        applicant.email = request.POST.get('email', applicant.email)
        applicant.gender = request.POST.get('gender', applicant.gender)
        applicant.city = request.POST.get('city', applicant.city)
        applicant.state = request.POST.get('state', applicant.state)
        applicant.pin_code = request.POST.get('pin_code', applicant.pin_code)
        
        applicant.save()
        
        messages.success(request, 'Applicant information updated successfully!')
        return redirect('admin_loan_detail', applicant_id=applicant_id)
        
    except Exception as e:
        messages.error(request, f'Error updating applicant: {str(e)}')
        return redirect('admin_loan_detail', applicant_id=applicant_id)

