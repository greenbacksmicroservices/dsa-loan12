"""
Professional Loan Management API - Real-time AJAX endpoints
Production-ready endpoints for dashboard management and real-time updates
"""

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Sum, Q, F
from django.utils import timezone
from django.core.paginator import Paginator
from datetime import timedelta
import json

from .models import (
    User, Agent, Loan, Complaint, ComplaintComment, 
    ActivityLog, LoanDocument, LoanApplication, Applicant
)
from .decorators import admin_required, employee_required
from .followup_utils import auto_move_overdue_to_follow_up


def _follow_up_pending_q():
    return Q(status__in=['new_entry', 'waiting']) & Q(remarks__icontains='Revert Remark ')


# ============================================================================
# NEW LOAN APPLICATIONS API (AJAX Only)
# ============================================================================

@login_required
@require_http_methods(["GET"])
def api_get_new_loan_applications(request):
    """
    Get paginated list of new loan applications
    Used by admin dashboard with manual refresh
    """
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    page = request.GET.get('page', 1)
    search = request.GET.get('search', '').strip()
    per_page = int(request.GET.get('per_page', 10))
    
    # Get new loan applications
    queryset = Loan.objects.filter(
        status='new_entry',
        applicant_type='agent'
    ).select_related('assigned_agent', 'created_by').order_by('-created_at')
    
    # Apply search filter
    if search:
        queryset = queryset.filter(
            Q(full_name__icontains=search) |
            Q(mobile_number__icontains=search) |
            Q(email__icontains=search)
        )
    
    # Paginate
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(page)
    
    # Format data
    applications = []
    for loan in page_obj:
        applications.append({
            'id': loan.id,
            'name': loan.full_name,
            'email': loan.email,
            'phone': loan.mobile_number,
            'loan_type': loan.get_loan_type_display(),
            'loan_amount': float(loan.loan_amount),
            'status': loan.status,
            'created_at': loan.created_at.isoformat(),
            'days_old': (timezone.now() - loan.created_at).days,
            'agent': loan.assigned_agent.name if loan.assigned_agent else 'Unassigned',
        })
    
    return JsonResponse({
        'success': True,
        'data': applications,
        'pagination': {
            'current_page': page_obj.number,
            'total_pages': paginator.num_pages,
            'total_count': paginator.count,
            'has_next': page_obj.has_next(),
            'has_prev': page_obj.has_previous(),
        }
    })


@login_required
@require_http_methods(["GET"])
def api_get_loan_detail(request, loan_id):
    """
    Get full details of a loan application for modal/detail view
    Shows applicant, loan, bank, and document details
    """
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        loan = Loan.objects.select_related(
            'assigned_agent', 
            'assigned_employee', 
            'created_by'
        ).prefetch_related('documents').get(id=loan_id)
    except Loan.DoesNotExist:
        return JsonResponse({'error': 'Loan not found'}, status=404)
    
    # Applicant details
    applicant_data = {
        'full_name': loan.full_name,
        'mobile': loan.mobile_number,
        'email': loan.email,
        'city': loan.city,
        'state': loan.state,
        'pin_code': loan.pin_code,
        'permanent_address': loan.permanent_address,
        'current_address': loan.current_address,
        'username': loan.username,
        'user_id': loan.user_id,
    }
    
    # Loan details
    loan_data = {
        'type': loan.get_loan_type_display(),
        'amount': float(loan.loan_amount),
        'tenure_months': loan.tenure_months,
        'interest_rate': float(loan.interest_rate) if loan.interest_rate else 0,
        'emi': float(loan.emi) if loan.emi else 0,
        'purpose': loan.loan_purpose,
        'status': loan.status,
    }
    
    # Bank details
    bank_data = {
        'name': loan.bank_name,
        'account_number': loan.bank_account_number,
        'ifsc_code': loan.bank_ifsc_code,
        'type': loan.get_bank_type_display() if loan.bank_type else 'N/A',
    }
    
    # Documents
    documents = []
    for doc in loan.documents.all():
        documents.append({
            'id': doc.id,
            'type': doc.get_document_type_display(),
            'file_url': doc.file.url if doc.file else None,
            'uploaded_at': doc.uploaded_at.isoformat(),
        })
    
    # Assignment panel data
    assignment_data = {
        'assigned_employee': {
            'id': loan.assigned_employee.id if loan.assigned_employee else None,
            'name': loan.assigned_employee.get_full_name() if loan.assigned_employee else 'Unassigned',
        },
        'assigned_agent': {
            'id': loan.assigned_agent.id if loan.assigned_agent else None,
            'name': loan.assigned_agent.name if loan.assigned_agent else 'Unassigned',
        },
        'assigned_at': loan.assigned_at.isoformat() if loan.assigned_at else None,
        'action_taken_at': loan.action_taken_at.isoformat() if loan.action_taken_at else None,
    }
    
    return JsonResponse({
        'success': True,
        'data': {
            'id': loan.id,
            'applicant': applicant_data,
            'loan': loan_data,
            'bank': bank_data,
            'documents': documents,
            'assignment': assignment_data,
            'remarks': loan.remarks,
            'created_at': loan.created_at.isoformat(),
        }
    })


@login_required
@require_http_methods(["POST"])
def api_assign_loan_to_employee(request, loan_id):
    """
    AJAX endpoint to assign loan to employee
    Returns updated loan data
    """
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        data = json.loads(request.body)
        employee_id = data.get('employee_id')
        
        if not employee_id:
            return JsonResponse({'error': 'Employee ID required'}, status=400)
        
        loan = Loan.objects.get(id=loan_id)
        employee = User.objects.get(id=employee_id, role='employee')
        
        # Assign loan
        loan.assigned_employee = employee
        loan.assigned_at = timezone.now()
        loan.status = 'waiting'
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='status_updated',
            description=f"Loan for {loan.full_name} assigned to {employee.get_full_name()}",
            user=request.user,
            related_loan=loan
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Loan assigned to {employee.get_full_name()}',
            'assigned_to': employee.get_full_name(),
        })
    
    except Loan.DoesNotExist:
        return JsonResponse({'error': 'Loan not found'}, status=404)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Employee not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def api_approve_loan_ajax(request, loan_id):
    """
    AJAX endpoint for employee to approve loan
    """
    try:
        data = json.loads(request.body)
        approval_notes = data.get('notes', '')
        
        loan = Loan.objects.get(id=loan_id)
        
        # Check permission
        if loan.assigned_employee != request.user and request.user.role != 'admin':
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        # Approve
        loan.status = 'approved'
        loan.action_taken_at = timezone.now()
        loan.remarks = approval_notes
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_approved',
            description=f"Loan for {loan.full_name} approved by {request.user.get_full_name()}",
            user=request.user,
            related_loan=loan
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Loan approved successfully',
            'status': 'approved',
        })
    
    except Loan.DoesNotExist:
        return JsonResponse({'error': 'Loan not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def api_reject_loan_ajax(request, loan_id):
    """
    AJAX endpoint for employee to reject loan
    """
    try:
        data = json.loads(request.body)
        reason = data.get('reason', '')
        
        loan = Loan.objects.get(id=loan_id)
        
        # Check permission
        if loan.assigned_employee != request.user and request.user.role != 'admin':
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        # Reject
        loan.status = 'rejected'
        loan.action_taken_at = timezone.now()
        loan.remarks = reason
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_rejected',
            description=f"Loan for {loan.full_name} rejected by {request.user.get_full_name()}. Reason: {reason}",
            user=request.user,
            related_loan=loan
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Loan rejected successfully',
            'status': 'rejected',
        })
    
    except Loan.DoesNotExist:
        return JsonResponse({'error': 'Loan not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def api_disburse_loan_ajax(request, loan_id):
    """
    AJAX endpoint for admin to disburse loan
    """
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        data = json.loads(request.body)
        disbursement_date = data.get('disbursement_date')
        
        loan = Loan.objects.get(id=loan_id)
        
        # Disburse
        loan.status = 'disbursed'
        loan.action_taken_at = timezone.now()
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_disbursed',
            description=f"Loan for {loan.full_name} disbursed on {disbursement_date}",
            user=request.user,
            related_loan=loan
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Loan disbursed successfully',
            'status': 'disbursed',
        })
    
    except Loan.DoesNotExist:
        return JsonResponse({'error': 'Loan not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ============================================================================
# DASHBOARD REAL-TIME API
# ============================================================================

@login_required
@require_http_methods(["GET"])
def api_dashboard_stats(request):
    """
    Get real-time dashboard statistics
    Returns counts and percentages for all statuses
    """
    auto_move_overdue_to_follow_up()

    if request.user.role == 'admin':
        # Admin gets all statistics
        base_qs = Loan.objects.all()
        follow_up_pending = base_qs.filter(_follow_up_pending_q()).count()
        new_entries = base_qs.filter(status='new_entry').exclude(remarks__icontains='Revert Remark ').count()
        waiting = base_qs.filter(status='waiting').exclude(remarks__icontains='Revert Remark ').count()
        follow_up = base_qs.filter(status='follow_up').count()
        approved = base_qs.filter(status='approved').count()
        rejected = base_qs.filter(status='rejected').count()
        disbursed = base_qs.filter(status='disbursed').count()
        total = base_qs.count()

        total_amount_disbursed = base_qs.filter(
            status='disbursed'
        ).aggregate(total=Sum('loan_amount'))['total'] or 0

        total_amount_pending = base_qs.filter(
            status__in=['new_entry', 'waiting', 'approved']
        ).aggregate(total=Sum('loan_amount'))['total'] or 0

    elif request.user.role == 'employee':
        # Employee sees only assigned loans
        base_qs = Loan.objects.filter(assigned_employee=request.user)
        follow_up_pending = base_qs.filter(_follow_up_pending_q()).count()
        new_entries = base_qs.filter(status='new_entry').exclude(remarks__icontains='Revert Remark ').count()
        waiting = base_qs.filter(status='waiting').exclude(remarks__icontains='Revert Remark ').count()
        follow_up = base_qs.filter(status='follow_up').count()
        approved = base_qs.filter(status='approved').count()
        rejected = base_qs.filter(status='rejected').count()
        disbursed = base_qs.filter(status='disbursed').count()
        total = base_qs.count()

        total_amount_disbursed = base_qs.filter(
            status='disbursed'
        ).aggregate(total=Sum('loan_amount'))['total'] or 0

        total_amount_pending = base_qs.filter(
            status__in=['new_entry', 'waiting', 'approved']
        ).aggregate(total=Sum('loan_amount'))['total'] or 0
    else:
        return JsonResponse({
            'success': False,
            'role_mismatch': True,
            'message': 'Dashboard realtime stats not available for this role',
            'data': {
                'new_entries': 0,
                'waiting': 0,
                'follow_up': 0,
                'follow_up_pending': 0,
                'approved': 0,
                'rejected': 0,
                'disbursed': 0,
                'total': 0,
                'total_amount_disbursed': 0.0,
                'total_amount_pending': 0.0,
            }
        }, status=200)
    
    return JsonResponse({
        'success': True,
        'data': {
            'new_entries': new_entries,
            'waiting': waiting,
            'follow_up': follow_up,
            'follow_up_pending': follow_up_pending,
            'approved': approved,
            'rejected': rejected,
            'disbursed': disbursed,
            'total': total,
            'total_amount_disbursed': float(total_amount_disbursed),
            'total_amount_pending': float(total_amount_pending),
        }
    })


@login_required
@require_http_methods(["GET"])
def api_get_recent_complaints(request):
    """
    Get recent complaints for admin
    Real-time updates without page refresh
    """
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    limit = int(request.GET.get('limit', 10))
    complaints = Complaint.objects.select_related(
        'loan', 'filed_by_employee', 'filed_by_agent', 'assigned_admin'
    ).order_by('-created_at')[:limit]
    
    data = []
    for complaint in complaints:
        data.append({
            'id': complaint.id,
            'complaint_id': complaint.complaint_id,
            'customer_name': complaint.customer_name,
            'type': complaint.get_complaint_type_display(),
            'priority': complaint.get_priority_display(),
            'status': complaint.get_status_display(),
            'created_at': complaint.created_at.isoformat(),
            'updated_at': complaint.updated_at.isoformat(),
            'hours_ago': int((timezone.now() - complaint.created_at).total_seconds() / 3600),
        })
    
    return JsonResponse({
        'success': True,
        'data': data,
    })


# ============================================================================
# EMPLOYEE MANAGEMENT API
# ============================================================================

@admin_required
@require_http_methods(["GET"])
def api_get_employees_list(request):
    """
    Get all employees for management panel
    """
    search = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    
    queryset = User.objects.filter(role='employee', is_active=True)
    
    if search:
        queryset = queryset.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(employee_id__icontains=search)
        )
    
    if status_filter:
        queryset = queryset.filter(is_active=(status_filter == 'active'))
    
    employees = []
    for emp in queryset.order_by('first_name'):
        # Get employee statistics
        leads_count = Loan.objects.filter(assigned_employee=emp).count()
        approved_count = Loan.objects.filter(
            assigned_employee=emp, status='approved'
        ).count()
        disbursed_amount = Loan.objects.filter(
            assigned_employee=emp, status='disbursed'
        ).aggregate(total=Sum('loan_amount'))['total'] or 0
        
        employees.append({
            'id': emp.id,
            'employee_id': emp.employee_id,
            'name': emp.get_full_name(),
            'email': emp.email,
            'phone': emp.phone,
            'photo_url': emp.profile_photo.url if emp.profile_photo else None,
            'leads': leads_count,
            'approved': approved_count,
            'total_disbursed': float(disbursed_amount),
            'status': 'active' if emp.is_active else 'inactive',
        })
    
    return JsonResponse({
        'success': True,
        'data': employees,
    })


@admin_required
@require_http_methods(["POST"])
def api_create_employee(request):
    """
    Create new employee with photo
    """
    try:
        # Get form data
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        gender = request.POST.get('gender')
        address = request.POST.get('address')
        password = request.POST.get('password')
        employee_id = request.POST.get('employee_id')
        
        # Validate required fields
        if not all([first_name, email, password, employee_id]):
            return JsonResponse({
                'error': 'Missing required fields'
            }, status=400)
        
        # Check if email or employee_id already exists
        if User.objects.filter(email=email).exists():
            return JsonResponse({'error': 'Email already exists'}, status=400)
        if User.objects.filter(employee_id=employee_id).exists():
            return JsonResponse({'error': 'Employee ID already exists'}, status=400)
        
        # Create user
        username = email.split('@')[0]
        while User.objects.filter(username=username).exists():
            username = f"{username}{User.objects.count()}"
        
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role='employee',
            employee_id=employee_id,
            phone=phone,
            gender=gender,
            address=address,
        )
        
        # Handle photo upload
        if 'photo' in request.FILES:
            user.profile_photo = request.FILES['photo']
            user.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='agent_registered',
            description=f"New employee '{user.get_full_name()}' created by {request.user.get_full_name()}",
            user=request.user
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Employee {user.get_full_name()} created successfully',
            'employee': {
                'id': user.id,
                'name': user.get_full_name(),
                'email': user.email,
                'phone': user.phone,
            }
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@admin_required
@require_http_methods(["POST"])
def api_delete_employee(request, employee_id):
    """
    Soft delete employee (deactivate account)
    """
    try:
        employee = User.objects.get(id=employee_id, role='employee')
        employee.is_active = False
        employee.save()
        
        ActivityLog.objects.create(
            action='status_updated',
            description=f"Employee '{employee.get_full_name()}' deactivated by {request.user.get_full_name()}",
            user=request.user
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Employee {employee.get_full_name()} deactivated'
        })
    
    except User.DoesNotExist:
        return JsonResponse({'error': 'Employee not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ============================================================================
# REPORT DOWNLOAD API
# ============================================================================

@login_required
@require_http_methods(["GET"])
def api_download_report(request):
    """
    Download report for specified period
    Formats: CSV, PDF, Excel
    """
    from django.http import HttpResponse
    import csv
    from datetime import datetime, timedelta
    
    period = request.GET.get('period', '1month')  # 1month, 6months, 1year
    format_type = request.GET.get('format', 'csv')  # csv, pdf, excel
    
    # Calculate date range
    now = timezone.now()
    if period == '1month':
        start_date = now - timedelta(days=30)
    elif period == '6months':
        start_date = now - timedelta(days=180)
    else:  # 1year
        start_date = now - timedelta(days=365)
    
    # Get loans
    if request.user.role == 'admin':
        loans = Loan.objects.filter(created_at__gte=start_date)
    else:
        loans = Loan.objects.filter(
            created_at__gte=start_date,
            assigned_employee=request.user
        )
    
    if format_type == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="loan_report_{period}.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Name', 'Email', 'Phone', 'Loan Type', 'Amount',
            'Status', 'Agent', 'Employee', 'Created Date'
        ])
        
        for loan in loans:
            writer.writerow([
                loan.full_name,
                loan.email,
                loan.mobile_number,
                loan.get_loan_type_display(),
                float(loan.loan_amount),
                loan.status,
                loan.assigned_agent.name if loan.assigned_agent else 'N/A',
                loan.assigned_employee.get_full_name() if loan.assigned_employee else 'N/A',
                loan.created_at.strftime('%Y-%m-%d'),
            ])
        
        return response
    
    return JsonResponse({'error': 'Format not supported yet'}, status=400)
