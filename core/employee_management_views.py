"""
Employee Management Views - Admin Panel
Handles CRUD operations for employee management
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.hashers import make_password
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Q, Count, Sum
from django.core.paginator import Paginator
import json

from .models import User, EmployeeProfile, LoanApplication
from django.contrib.auth.models import Group


def is_admin(user):
    """Check if user is admin"""
    return user.is_authenticated and user.role == 'admin'


@login_required(login_url='admin_login')
@user_passes_test(is_admin, login_url='admin_login')
def employee_management(request):
    """
    Main Employee Management Page - Admin Only
    Displays list of employees and handles employee operations
    """
    context = {
        'page_title': 'Employees',
        'page_subtitle': 'Manage internal employees & loan processors',
    }
    return render(request, 'core/admin/employee_management.html', context)


@login_required(login_url='admin_login')
@user_passes_test(is_admin, login_url='admin_login')
@require_http_methods(["GET"])
def api_get_employees(request):
    """
    API Endpoint: Get list of all employees with pagination and search
    Returns JSON data for table population
    """
    try:
        search_query = request.GET.get('search', '').strip()
        page = request.GET.get('page', 1)
        per_page = request.GET.get('per_page', 10)
        
        # Build query
        employees = User.objects.filter(role='employee')
        
        # Search by name or email
        if search_query:
            employees = employees.filter(
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(employee_id__icontains=search_query)
            )
        
        # Paginate
        paginator = Paginator(employees, per_page)
        page_obj = paginator.get_page(page)
        
        # Serialize employee data
        employee_list = []
        for user in page_obj:
            employee_profile = getattr(user, 'employee_profile', None)
            
            # Get assigned loans count
            assigned_loans = LoanApplication.objects.filter(
                assigned_employee=user
            ).count()
            
            employee_data = {
                'id': user.id,
                'employee_id': user.employee_id or f'EMP{user.id:04d}',
                'name': user.get_full_name() or user.username,
                'email': user.email,
                'phone': user.phone or 'N/A',
                'photo_url': user.profile_photo.url if user.profile_photo else '/static/images/default-avatar.png',
                'role': employee_profile.get_employee_role_display() if employee_profile else 'Loan Processor',
                'status': 'Active' if user.is_active else 'Inactive',
                'is_active': user.is_active,
                'total_leads': employee_profile.total_leads if employee_profile else 0,
                'approved_loans': employee_profile.approved_loans if employee_profile else 0,
                'rejected_loans': employee_profile.rejected_loans if employee_profile else 0,
                'total_disbursed': float(employee_profile.total_disbursed_amount) if employee_profile else 0.0,
                'assigned_loans': assigned_loans,
            }
            employee_list.append(employee_data)
        
        return JsonResponse({
            'success': True,
            'employees': employee_list,
            'total_count': paginator.count,
            'total_pages': paginator.num_pages,
            'current_page': int(page),
            'per_page': int(per_page),
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@user_passes_test(is_admin, login_url='admin_login')
@require_http_methods(["POST"])
def api_add_employee(request):
    """
    API Endpoint: Add new employee
    Creates User and EmployeeProfile records
    """
    try:
        data = json.loads(request.body)
        
        # Validation
        required_fields = ['full_name', 'email', 'phone', 'password']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({
                    'success': False,
                    'error': f'{field.replace("_", " ").title()} is required'
                }, status=400)
        
        # Check email uniqueness
        if User.objects.filter(email=data['email']).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already exists'
            }, status=400)
        
        # Parse full name
        full_name = data['full_name'].strip().split(' ', 1)
        first_name = full_name[0]
        last_name = full_name[1] if len(full_name) > 1 else ''
        
        # Create User
        user = User.objects.create_user(
            username=data['email'].split('@')[0],  # Username from email
            email=data['email'],
            password=data['password'],
            first_name=first_name,
            last_name=last_name,
            phone=data['phone'],
            role='employee',
            gender=data.get('gender', 'Other'),
            address=data.get('address', ''),
            is_active=data.get('status', 'active') == 'active',
        )
        
        # Create EmployeeProfile
        employee_profile = EmployeeProfile.objects.create(
            user=user,
            employee_role=data.get('role', 'loan_processor'),
            notes=data.get('notes', ''),
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Employee added successfully',
            'employee_id': user.id,
        }, status=201)
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@user_passes_test(is_admin, login_url='admin_login')
@require_http_methods(["POST"])
def api_update_employee(request, employee_id):
    """
    API Endpoint: Update employee details
    """
    try:
        user = get_object_or_404(User, id=employee_id, role='employee')
        data = json.loads(request.body)
        
        # Update User fields
        if 'email' in data:
            # Check email uniqueness (excluding current user)
            if User.objects.filter(email=data['email']).exclude(id=user.id).exists():
                return JsonResponse({
                    'success': False,
                    'error': 'Email already exists'
                }, status=400)
            user.email = data['email']
        
        if 'full_name' in data:
            full_name = data['full_name'].strip().split(' ', 1)
            user.first_name = full_name[0]
            user.last_name = full_name[1] if len(full_name) > 1 else ''
        
        if 'phone' in data:
            user.phone = data['phone']
        
        if 'address' in data:
            user.address = data['address']
        
        if 'gender' in data:
            user.gender = data['gender']
        
        if 'password' in data and data['password']:
            user.set_password(data['password'])
        
        if 'status' in data:
            user.is_active = data['status'] == 'active'
        
        user.save()
        
        # Update EmployeeProfile
        try:
            profile = user.employee_profile
            if 'role' in data:
                profile.employee_role = data['role']
            if 'notes' in data:
                profile.notes = data['notes']
            profile.save()
        except EmployeeProfile.DoesNotExist:
            EmployeeProfile.objects.create(
                user=user,
                employee_role=data.get('role', 'loan_processor'),
                notes=data.get('notes', ''),
            )
        
        return JsonResponse({
            'success': True,
            'message': 'Employee updated successfully'
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@user_passes_test(is_admin, login_url='admin_login')
@require_http_methods(["GET"])
def api_get_employee(request, employee_id):
    """
    API Endpoint: Get single employee details
    """
    try:
        user = get_object_or_404(User, id=employee_id, role='employee')
        profile = getattr(user, 'employee_profile', None)
        
        assigned_loans = LoanApplication.objects.filter(
            assigned_employee=user
        ).count()
        
        return JsonResponse({
            'success': True,
            'employee': {
                'id': user.id,
                'employee_id': user.employee_id or f'EMP{user.id:04d}',
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'phone': user.phone or '',
                'address': user.address or '',
                'gender': user.gender or 'Other',
                'role': profile.employee_role if profile else 'loan_processor',
                'status': 'active' if user.is_active else 'inactive',
                'total_leads': profile.total_leads if profile else 0,
                'approved_loans': profile.approved_loans if profile else 0,
                'rejected_loans': profile.rejected_loans if profile else 0,
                'total_disbursed': float(profile.total_disbursed_amount) if profile else 0.0,
                'assigned_loans': assigned_loans,
                'notes': profile.notes if profile else '',
            }
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@user_passes_test(is_admin, login_url='admin_login')
@require_http_methods(["POST"])
def api_delete_employee(request, employee_id):
    """
    API Endpoint: Delete (soft delete) employee
    Sets is_active to False instead of hard delete
    """
    try:
        user = get_object_or_404(User, id=employee_id, role='employee')
        
        # Soft delete
        user.is_active = False
        user.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Employee deleted successfully'
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@user_passes_test(is_admin, login_url='admin_login')
@require_http_methods(["POST"])
def api_toggle_employee_status(request, employee_id):
    """
    API Endpoint: Activate/Deactivate employee
    """
    try:
        user = get_object_or_404(User, id=employee_id, role='employee')
        data = json.loads(request.body)
        
        user.is_active = data.get('is_active', not user.is_active)
        user.save()
        
        status_text = 'activated' if user.is_active else 'deactivated'
        
        return JsonResponse({
            'success': True,
            'message': f'Employee {status_text} successfully',
            'is_active': user.is_active
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@user_passes_test(is_admin, login_url='admin_login')
@require_http_methods(["GET"])
def api_employee_stats(request):
    """
    API Endpoint: Get overall employee statistics
    """
    try:
        employees = User.objects.filter(role='employee', is_active=True)
        
        total_employees = employees.count()
        total_leads = EmployeeProfile.objects.aggregate(Sum('total_leads'))['total_leads__sum'] or 0
        total_approved = EmployeeProfile.objects.aggregate(Sum('approved_loans'))['approved_loans__sum'] or 0
        total_disbursed = EmployeeProfile.objects.aggregate(Sum('total_disbursed_amount'))['total_disbursed_amount__sum'] or 0.0
        
        return JsonResponse({
            'success': True,
            'stats': {
                'total_employees': total_employees,
                'total_leads': total_leads,
                'total_approved': total_approved,
                'total_disbursed': float(total_disbursed),
            }
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@login_required(login_url='admin_login')
@user_passes_test(is_admin, login_url='admin_login')
@require_http_methods(["GET"])
def employee_detail(request, employee_id):
    """
    Employee Detail Page - Shows full employee information with statistics
    """
    try:
        employee = get_object_or_404(User, id=employee_id, role='employee')
        
        # Get employee statistics
        loans = LoanApplication.objects.filter(assigned_employee=employee)
        approved_loans = loans.filter(status='Approved').count()
        total_disbursed = loans.filter(status='Disbursed').aggregate(
            total=Sum('loan_amount')
        )['total'] or 0
        
        context = {
            'employee': employee,
            'total_leads': loans.count(),
            'approved_loans': approved_loans,
            'total_disbursed': total_disbursed,
        }
        
        return render(request, 'core/admin/employee_detail.html', context)
    
    except Exception as e:
        return redirect('employee_management')