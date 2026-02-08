# ============ ADMIN PROFILE & SETTINGS VIEWS ============

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Sum, Count
from rest_framework.decorators import api_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
import json
import logging

from .models import User, Loan, EmployeeProfile, LoanApplication, Agent
from .decorators import admin_required

logger = logging.getLogger(__name__)


@login_required(login_url='admin_login')
def admin_profile(request):
    """Admin profile page"""
    if request.user.role != 'admin':
        return redirect('admin_all_loans')
    return render(request, 'core/admin/profile.html')


@login_required(login_url='admin_login')
@require_POST
def api_update_admin_profile(request):
    """API endpoint to update admin profile"""
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Not authorized'}, status=403)
    
    try:
        user = request.user
        data = json.loads(request.body)
        
        # Update profile fields
        if 'first_name' in data:
            user.first_name = data['first_name']
        if 'last_name' in data:
            user.last_name = data['last_name']
        if 'phone' in data:
            user.phone = data['phone']
        if 'address' in data:
            user.address = data['address']
        
        user.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Profile updated successfully',
            'user': {
                'id': user.id,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'phone': user.phone,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error updating admin profile: {str(e)}")
        return JsonResponse({'error': str(e)}, status=400)


@login_required(login_url='admin_login')
@require_POST
def api_change_password(request):
    """API endpoint to change admin password"""
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Not authorized'}, status=403)
    
    try:
        user = request.user
        data = json.loads(request.body)
        
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')
        
        # Validate current password
        if not user.check_password(current_password):
            return JsonResponse({'error': 'Current password is incorrect'}, status=400)
        
        # Check password match
        if new_password != confirm_password:
            return JsonResponse({'error': 'New passwords do not match'}, status=400)
        
        # Check password strength
        if len(new_password) < 8:
            return JsonResponse({'error': 'Password must be at least 8 characters long'}, status=400)
        
        # Set new password
        user.set_password(new_password)
        user.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Password changed successfully'
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error changing password: {str(e)}")
        return JsonResponse({'error': str(e)}, status=400)


@login_required(login_url='admin_login')
def admin_processing_requests(request):
    """Admin view for processing requests"""
    if request.user.role != 'admin':
        return redirect('admin_all_loans')
    return render(request, 'core/admin/processing_requests.html')


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_processing_requests(request):
    """API endpoint to get processing requests for admin"""
    try:
        user = request.user
        status_filter = request.GET.get('status', '')
        page = request.GET.get('page', 1)
        per_page = request.GET.get('per_page', 10)
        search = request.GET.get('search', '').strip()
        
        # Build base queryset
        loans = Loan.objects.select_related(
            'assigned_employee',
            'assigned_agent',
            'created_by'
        ).prefetch_related('documents')
        
        # Role-based filtering
        if user.role == 'employee':
            loans = loans.filter(assigned_employee=user)
        elif user.role == 'agent':
            loans = loans.filter(assigned_agent__user=user)
        # Admin sees all
        
        # Filter by status
        if status_filter:
            loans = loans.filter(status=status_filter)
        else:
            loans = loans.filter(status__in=['waiting', 'follow_up'])
        
        # Search
        if search:
            loans = loans.filter(
                Q(full_name__icontains=search) |
                Q(mobile_number__icontains=search) |
                Q(email__icontains=search)
            )
        
        loans = loans.order_by('-assigned_at')
        
        # Pagination
        from django.core.paginator import Paginator
        paginator = Paginator(loans, per_page)
        page_obj = paginator.get_page(page)
        
        # Serialize data
        requests_list = []
        for loan in page_obj:
            hours_since = loan.get_hours_since_assignment()
            
            request_data = {
                'id': loan.id,
                'applicant_name': loan.full_name,
                'applicant_email': loan.email or 'N/A',
                'applicant_phone': loan.mobile_number,
                'loan_type': loan.get_loan_type_display(),
                'loan_amount': float(loan.loan_amount),
                'status': loan.get_status_display(),
                'status_value': loan.status,
                'assigned_to': {
                    'id': loan.assigned_employee.id if loan.assigned_employee else None,
                    'name': loan.assigned_employee.get_full_name() if loan.assigned_employee else 'Unassigned',
                    'type': 'employee'
                } if loan.assigned_employee else {
                    'id': loan.assigned_agent.id if loan.assigned_agent else None,
                    'name': loan.assigned_agent.name if loan.assigned_agent else 'Unassigned',
                    'type': 'agent'
                } if loan.assigned_agent else {'id': None, 'name': 'Unassigned', 'type': 'none'},
                'assigned_at': loan.assigned_at.isoformat() if loan.assigned_at else None,
                'hours_since_assignment': hours_since,
                'requires_followup': loan.requires_follow_up or hours_since >= 24,
                'action_buttons': {
                    'approve': user.role in ['admin', 'employee', 'agent'],
                    'reject': user.role in ['admin', 'employee', 'agent'],
                    'reassign': user.role == 'admin',
                    'followup': user.role == 'admin',
                }
            }
            requests_list.append(request_data)
        
        return JsonResponse({
            'success': True,
            'requests': requests_list,
            'total_count': paginator.count,
            'total_pages': paginator.num_pages,
            'current_page': int(page),
            'per_page': int(per_page),
            'user_role': user.role,
        })
    
    except Exception as e:
        logger.error(f"Error fetching processing requests: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
        