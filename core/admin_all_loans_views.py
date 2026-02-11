# ============ ADMIN ALL LOANS - MASTER DATABASE VIEW ============

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Sum, Count, F, Prefetch
from django.core.paginator import Paginator
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
import json
import logging
from datetime import datetime

from .models import (
    LoanApplication, Applicant, ApplicantDocument, LoanAssignment, 
    LoanStatusHistory, User, Agent
)
from .decorators import admin_required

logger = logging.getLogger(__name__)


@login_required(login_url='admin_login')
@admin_required
def admin_all_loans(request):
    """
    Main All Loans page - Master view of entire loan database
    Displays all loans in comprehensive table format
    """
    from .models import Loan
    
    # Get all loans ordered by creation date (newest first)
    loans = Loan.objects.all().order_by('-created_at')
    
    # Apply search filter if provided
    search_query = request.GET.get('q', '').strip()
    if search_query:
        loans = loans.filter(
            Q(full_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(mobile_number__icontains=search_query) |
            Q(user_id__icontains=search_query)
        )
    
    context = {
        'page_title': 'All Loans - Master Database',
        'loans': loans,
        'search_query': search_query,
        'total_loans': Loan.objects.count(),
    }
    return render(request, 'core/admin/all_loans.html', context)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_all_loans(request):
    """
    API endpoint to fetch all loans with filtering by status
    Returns paginated list of loans
    """
    try:
        # Get filter parameters
        status_filter = request.GET.get('status', 'all')
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 25))
        search = request.GET.get('search', '').strip()
        
        # Build query
        query = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
            'assigned_by',
            'approved_by',
            'rejected_by',
            'disbursed_by'
        ).prefetch_related(
            'documents',
            'status_history',
            'assignments'
        )
        
        # Apply status filter
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
        
        # Apply search filter
        if search:
            query = query.filter(
                Q(applicant__full_name__icontains=search) |
                Q(applicant__email__icontains=search) |
                Q(applicant__mobile__icontains=search) |
                Q(id__icontains=search)
            )
        
        # Get total count before pagination
        total_count = query.count()
        
        # Order by created_at descending
        query = query.order_by('-created_at')
        
        # Paginate
        paginator = Paginator(query, per_page)
        page_obj = paginator.get_page(page)
        
        # Format loans data
        loans_data = []
        for loan in page_obj.object_list:
            # Get assigned employee name
            employee_name = loan.assigned_employee.get_full_name() if loan.assigned_employee else "Unassigned"
            
            # Get agent name
            agent_name = loan.assigned_agent.name if loan.assigned_agent else "N/A"
            
            # Get most recent status change
            last_update = loan.status_history.first()
            last_updated_date = last_update.changed_at if last_update else loan.created_at
            
            loans_data.append({
                'id': loan.id,
                'loan_id': f"LOAN-{loan.id:06d}",
                'applicant_name': loan.applicant.full_name,
                'applicant_email': loan.applicant.email or 'N/A',
                'applicant_phone': loan.applicant.mobile or 'N/A',
                'loan_type': loan.applicant.loan_type or 'N/A',
                'loan_amount': str(loan.applicant.loan_amount) if loan.applicant.loan_amount else '0.00',
                'agent_name': agent_name,
                'employee_name': employee_name,
                'status': loan.status,
                'status_display': loan.get_status_display(),
                'submitted_date': loan.created_at.strftime('%Y-%m-%d %H:%M'),
                'last_updated_date': last_updated_date.strftime('%Y-%m-%d %H:%M'),
                'days_since_submission': (timezone.now() - loan.created_at).days,
            })
        
        return JsonResponse({
            'success': True,
            'loans': loans_data,
            'pagination': {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'total_count': total_count,
                'per_page': per_page,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            }
        })
    
    except Exception as e:
        logger.error(f"Error fetching loans: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
def admin_loan_detail(request, loan_id):
    """
    Detailed view page for a single loan
    Shows complete applicant, loan, and document information
    """
    try:
        loan = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
            'assigned_by',
            'approved_by',
            'rejected_by',
            'disbursed_by'
        ).prefetch_related(
            'documents',
            'status_history',
            'assignments'
        ).get(id=loan_id)
        
        context = {
            'page_title': f'Loan Details - {loan.applicant.full_name}',
            'loan': loan,
            'applicant': loan.applicant,
            'documents': loan.documents.all(),
            'status_history': loan.status_history.all(),
            'assignment_info': loan.assignments.filter(status='active').first(),
        }
        
        return render(request, 'core/admin/all_loans_detail.html', context)
    
    except LoanApplication.DoesNotExist:
        return redirect('admin_all_loans')
    except Exception as e:
        logger.error(f"Error loading loan detail: {str(e)}")
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
            'assigned_by',
            'approved_by',
            'rejected_by',
            'disbursed_by'
        ).prefetch_related(
            'documents',
            'status_history',
            'assignments'
        ).get(id=loan_id)
        
        # Format applicant details
        applicant_data = {
            'full_name': loan.applicant.full_name,
            'email': loan.applicant.email or 'N/A',
            'mobile': loan.applicant.mobile or 'N/A',
            'city': loan.applicant.city or 'N/A',
            'state': loan.applicant.state or 'N/A',
            'pin_code': loan.applicant.pin_code or 'N/A',
            'gender': getattr(loan.applicant, 'gender', 'N/A'),
        }
        
        # Format loan details
        loan_data = {
            'loan_type': loan.applicant.loan_type or 'N/A',
            'loan_amount': str(loan.applicant.loan_amount) if loan.applicant.loan_amount else '0.00',
            'tenure_months': loan.applicant.tenure_months or 'N/A',
            'interest_rate': str(loan.applicant.interest_rate) if loan.applicant.interest_rate else 'N/A',
            'emi': str(loan.applicant.emi) if loan.applicant.emi else '0.00',
            'loan_purpose': loan.applicant.loan_purpose or 'N/A',
            'bank_name': loan.applicant.bank_name or 'N/A',
            'bank_type': loan.applicant.bank_type or 'N/A',
            'account_number': loan.applicant.account_number or 'N/A',
            'ifsc_code': loan.applicant.ifsc_code or 'N/A',
        }
        
        # Format documents
        documents_data = []
        for doc in loan.documents.all():
            documents_data.append({
                'id': doc.id,
                'type': doc.get_document_type_display(),
                'file_url': doc.file.url if doc.file else '#',
                'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M'),
            })
        
        # Format assignment info
        assignment_data = None
        active_assignment = loan.assignments.filter(status='active').first()
        if active_assignment:
            assignment_data = {
                'employee_name': active_assignment.assigned_to.get_full_name(),
                'assigned_by': active_assignment.assigned_by.get_full_name() if active_assignment.assigned_by else 'System',
                'assigned_at': active_assignment.assigned_at.strftime('%Y-%m-%d %H:%M:%S'),
                'hours_assigned': active_assignment.hours_assigned,
                'notes': active_assignment.assignment_notes or 'No notes',
            }
        
        # Format status history
        status_history_data = []
        for history in loan.status_history.all():
            status_history_data.append({
                'from_status': history.get_from_status_display() if history.from_status else 'Initial',
                'to_status': history.get_to_status_display(),
                'changed_by': history.changed_by.get_full_name() if history.changed_by else 'System',
                'changed_at': history.changed_at.strftime('%Y-%m-%d %H:%M:%S'),
                'reason': history.reason or 'No reason provided',
                'is_auto_triggered': history.is_auto_triggered,
            })
        
        return JsonResponse({
            'success': True,
            'loan_id': loan.id,
            'status': loan.status,
            'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'applicant': applicant_data,
            'loan_details': loan_data,
            'documents': documents_data,
            'assignment_info': assignment_data,
            'status_history': status_history_data,
        })
    
    except LoanApplication.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Loan not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error fetching loan detail: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
def admin_edit_loan(request, loan_id):
    """
    Edit loan page - Admin only
    """
    try:
        loan = LoanApplication.objects.select_related('applicant').get(id=loan_id)
        
        if request.method == 'POST':
            # Handle form submission
            data = json.loads(request.body)
            
            # Update applicant details
            applicant = loan.applicant
            if 'full_name' in data:
                applicant.full_name = data['full_name']
            if 'email' in data:
                applicant.email = data['email']
            if 'mobile' in data:
                applicant.mobile = data['mobile']
            if 'city' in data:
                applicant.city = data['city']
            if 'state' in data:
                applicant.state = data['state']
            if 'pin_code' in data:
                applicant.pin_code = data['pin_code']
            
            applicant.save()
            
            # Update loan details if needed
            if 'approval_notes' in data:
                loan.approval_notes = data['approval_notes']
            
            loan.updated_at = timezone.now()
            loan.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Loan updated successfully'
            })
        
        context = {
            'page_title': f'Edit Loan - {loan.applicant.full_name}',
            'loan': loan,
            'applicant': loan.applicant,
        }
        
        return render(request, 'core/admin/edit_loan_master.html', context)
    
    except LoanApplication.DoesNotExist:
        return redirect('admin_all_loans')
    except Exception as e:
        logger.error(f"Error editing loan: {str(e)}")
        return JsonResponse({'error': str(e)}, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_delete_loan(request, loan_id):
    """
    Delete loan (soft delete) - Admin only
    Requires confirmation
    """
    try:
        data = json.loads(request.body)
        
        if not data.get('confirm'):
            return JsonResponse({
                'success': False,
                'error': 'Please confirm deletion'
            }, status=400)
        
        loan = LoanApplication.objects.get(id=loan_id)
        
        # Implement soft delete - add a is_deleted field if needed
        # For now, we can use a different approach
        # Create an archive by updating status to 'archived' or similar
        
        # Option 1: Actually delete (if soft delete not implemented)
        # Option 2: Mark as deleted via a flag
        
        # Using soft delete approach with status
        original_status = loan.status
        
        # Create status history entry
        LoanStatusHistory.objects.create(
            loan_application=loan,
            from_status=original_status,
            to_status='Archived',  # New status for deleted loans
            changed_by=request.user,
            reason=f"Soft deleted by {request.user.get_full_name()}",
            is_auto_triggered=False
        )
        
        # Actually delete or archive
        loan.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Loan {loan_id} has been deleted successfully'
        })
    
    except LoanApplication.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Loan not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error deleting loan: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_reassign_loan(request, loan_id):
    """
    Reassign loan to a different employee
    """
    try:
        data = json.loads(request.body)
        employee_id = data.get('employee_id')
        notes = data.get('notes', '')
        
        if not employee_id:
            return JsonResponse({
                'success': False,
                'error': 'Employee ID is required'
            }, status=400)
        
        loan = LoanApplication.objects.get(id=loan_id)
        new_employee = User.objects.get(id=employee_id, role='employee')
        
        # Mark old assignment as reassigned
        old_assignment = loan.assignments.filter(status='active').first()
        if old_assignment:
            old_assignment.reassign()
        
        # Create new assignment
        new_assignment = LoanAssignment.objects.create(
            loan_application=loan,
            assigned_to=new_employee,
            assigned_by=request.user,
            assignment_notes=notes,
            status='active'
        )
        
        # Update loan
        loan.assigned_employee = new_employee
        loan.assigned_by = request.user
        loan.assigned_at = timezone.now()
        loan.save()
        
        # Create status history
        LoanStatusHistory.objects.create(
            loan_application=loan,
            from_status=loan.status,
            to_status=loan.status,
            changed_by=request.user,
            reason=f"Reassigned to {new_employee.get_full_name()}",
            is_auto_triggered=False
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Loan reassigned to {new_employee.get_full_name()}',
            'new_employee': new_employee.get_full_name()
        })
    
    except (LoanApplication.DoesNotExist, User.DoesNotExist) as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=404)
    except Exception as e:
        logger.error(f"Error reassigning loan: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_loan_stats(request):
    """
    Get overall loan statistics for dashboard
    """
    try:
        total_loans = LoanApplication.objects.count()
        approved_loans = LoanApplication.objects.filter(status='Approved').count()
        rejected_loans = LoanApplication.objects.filter(status='Rejected').count()
        disbursed_loans = LoanApplication.objects.filter(status='Disbursed').count()
        new_entry = LoanApplication.objects.filter(status='New Entry').count()
        waiting = LoanApplication.objects.filter(status='Waiting for Processing').count()
        follow_up = LoanApplication.objects.filter(status='Required Follow-up').count()
        
        # Total amount stats
        total_approved_amount = LoanApplication.objects.filter(
            status='Approved'
        ).aggregate(
            total=Sum('applicant__loan_amount')
        )['total'] or 0
        
        total_disbursed_amount = LoanApplication.objects.filter(
            status='Disbursed'
        ).aggregate(
            total=Sum('applicant__loan_amount')
        )['total'] or 0
        
        return JsonResponse({
            'success': True,
            'stats': {
                'total_loans': total_loans,
                'approved': approved_loans,
                'rejected': rejected_loans,
                'disbursed': disbursed_loans,
                'new_entry': new_entry,
                'waiting': waiting,
                'follow_up': follow_up,
                'total_approved_amount': str(total_approved_amount),
                'total_disbursed_amount': str(total_disbursed_amount),
            }
        })
    
    except Exception as e:
        logger.error(f"Error fetching loan stats: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
