"""
Admin Assignment Views - Real-Time Loan Assignment to Employees
Ensures loans immediately appear in Employee panel after assignment
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST
from django.http import JsonResponse
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import json
import logging

from .models import Loan, User, ActivityLog, LoanStatusHistory
from .decorators import admin_required
from .loan_sync import (
    application_status_to_loan_status,
    find_related_loan_application,
    sync_loan_to_application,
)

logger = logging.getLogger(__name__)

# ============================================================
# ADMIN ASSIGN LOAN TO EMPLOYEE (REAL-TIME)
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_assign_loan_to_employee(request):
    """
    Admin assigns a loan to an employee
    
    Flow:
    1. Admin sends: loan_id, employee_id
    2. System sets:
       - assigned_employee = employee
       - assigned_at = NOW
       - status remains NEW_ENTRY (first processor action decides next stage)
    3. Loan IMMEDIATELY appears in:
       - Employee -> New Entry Requests
       - Employee -> All Loans
       - Admin -> All Loans (with assignment info)
    
    NO page refresh needed - proper Django queries + real-time updates
    """
    
    # Verify admin only
    if request.user.role != 'admin':
        return Response({
            'success': False,
            'error': 'Only admins can assign loans'
        }, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Get data
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        loan_id = data.get('loan_id')
        employee_id = data.get('employee_id')
        
        if not loan_id or not employee_id:
            return Response({
                'success': False,
                'error': 'loan_id and employee_id are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get loan
        try:
            loan = Loan.objects.get(id=loan_id)
        except Loan.DoesNotExist:
            return Response({
                'success': False,
                'error': f'Loan {loan_id} not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get employee
        try:
            employee = User.objects.get(id=employee_id, role='employee')
        except User.DoesNotExist:
            return Response({
                'success': False,
                'error': f'Employee {employee_id} not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Verify loan is in NEW_ENTRY status
        if loan.status != 'new_entry':
            return Response({
                'success': False,
                'error': f'Loan must be in NEW_ENTRY status. Current status: {loan.status}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # ===== PERFORM ASSIGNMENT =====
        related_application = find_related_loan_application(loan)
        previous_app_status_key = application_status_to_loan_status(related_application.status) if related_application else None
        previous_assigned_employee_id = related_application.assigned_employee_id if related_application else None

        loan.assigned_employee = employee
        loan.assigned_at = timezone.now()
        loan.status = 'new_entry'
        assignment_line = f"Assigned By Admin: {request.user.get_full_name() or request.user.username} -> Employee: {employee.get_full_name() or employee.username}"
        loan.remarks = f"{loan.remarks}\n{assignment_line}".strip() if loan.remarks else assignment_line
        loan.save()

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
                    reason=f'Assigned to {employee.get_full_name() or employee.username} by admin',
                    is_auto_triggered=False,
                )
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_assigned',
            description=f"Admin {request.user.get_full_name()} assigned loan {loan.full_name} to employee {employee.get_full_name()}",
            user=request.user,
            related_loan=loan
        )
        
        logger.info(f"Loan {loan_id} assigned to employee {employee_id} by admin {request.user.id}")
        
        return Response({
            'success': True,
            'message': f'Loan assigned to {employee.get_full_name()} successfully',
            'loan': {
                'id': loan.id,
                'applicant_name': loan.full_name,
                'status': loan.status,
                'assigned_employee': employee.get_full_name(),
                'assigned_at': loan.assigned_at.isoformat(),
            }
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error assigning loan: {str(e)}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_reassign_loan(request, loan_id):
    """
    Admin reassigns loan from one employee to another
    """
    
    if request.user.role != 'admin':
        return Response({
            'success': False,
            'error': 'Only admins can reassign loans'
        }, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Get data
        data = request.data if hasattr(request, 'data') else json.loads(request.body)
        new_employee_id = data.get('employee_id')
        
        if not new_employee_id:
            return Response({
                'success': False,
                'error': 'employee_id is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get loan
        loan = get_object_or_404(Loan, id=loan_id)
        
        # Get new employee
        new_employee = get_object_or_404(User, id=new_employee_id, role='employee')
        
        # Store old assignment info for log
        old_employee = loan.assigned_employee
        related_application = find_related_loan_application(loan)
        previous_app_status_key = application_status_to_loan_status(related_application.status) if related_application else None
        previous_assigned_employee_id = related_application.assigned_employee_id if related_application else None
        
        # Reassign
        loan.assigned_employee = new_employee
        loan.assigned_at = timezone.now()
        reopen_note = None

        # If loan was in follow-up, move it back to waiting and reset follow-up flags
        if loan.status == 'follow_up':
            loan.status = 'waiting'
            loan.requires_follow_up = False
            loan.follow_up_triggered_at = None
        elif loan.status == 'rejected':
            loan.status = 'new_entry'
            loan.requires_follow_up = False
            loan.follow_up_triggered_at = None
            reopen_note = 'Reopened from Rejected to New Entry for fresh processing'

        assignment_line = f"Assigned By Admin: {request.user.get_full_name() or request.user.username} -> Employee: {new_employee.get_full_name() or new_employee.username}"
        notes_to_add = [assignment_line]
        if reopen_note:
            notes_to_add.append(reopen_note)
        joined_notes = '\n'.join(notes_to_add).strip()
        loan.remarks = f"{loan.remarks}\n{joined_notes}".strip() if loan.remarks else joined_notes
        loan.save()

        synced_application = sync_loan_to_application(
            loan,
            assigned_by_user=request.user,
            create_if_missing=True,
        )
        if synced_application:
            current_app_status_key = application_status_to_loan_status(synced_application.status)
            if previous_app_status_key != current_app_status_key or previous_assigned_employee_id != new_employee.id:
                LoanStatusHistory.objects.create(
                    loan_application=synced_application,
                    from_status=previous_app_status_key,
                    to_status=current_app_status_key,
                    changed_by=request.user,
                    reason=f'Reassigned to {new_employee.get_full_name() or new_employee.username} by admin',
                    is_auto_triggered=False,
                )
        
        # Log activity
        old_emp_name = old_employee.get_full_name() if old_employee else 'None'
        ActivityLog.objects.create(
            action='loan_reassigned',
            description=f"Admin {request.user.get_full_name()} reassigned loan {loan.full_name} from {old_emp_name} to {new_employee.get_full_name()}",
            user=request.user,
            related_loan=loan
        )
        
        return Response({
            'success': True,
            'message': f'Loan reassigned to {new_employee.get_full_name()} successfully',
            'loan': {
                'id': loan.id,
                'applicant_name': loan.full_name,
                'status': loan.status,
                'assigned_employee': new_employee.get_full_name(),
                'assigned_at': loan.assigned_at.isoformat(),
            }
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error reassigning loan: {str(e)}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_get_assignment_status(request, loan_id):
    """
    Get current assignment status of a loan
    Used to verify real-time updates
    """
    
    if request.user.role != 'admin':
        return Response({
            'success': False,
            'error': 'Only admins can access'
        }, status=status.HTTP_403_FORBIDDEN)
    
    try:
        loan = Loan.objects.select_related('assigned_employee', 'assigned_agent').get(id=loan_id)
        
        return Response({
            'success': True,
            'loan': {
                'id': loan.id,
                'applicant_name': loan.full_name,
                'status': loan.status,
                'assigned_employee': loan.assigned_employee.get_full_name() if loan.assigned_employee else None,
                'assigned_employee_id': loan.assigned_employee.id if loan.assigned_employee else None,
                'assigned_agent': loan.assigned_agent.name if loan.assigned_agent else None,
                'assigned_at': loan.assigned_at.isoformat() if loan.assigned_at else None,
                'hours_since_assignment': loan.get_hours_since_assignment() if hasattr(loan, 'get_hours_since_assignment') else 0,
            }
        }, status=status.HTTP_200_OK)
    
    except Loan.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Loan not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
