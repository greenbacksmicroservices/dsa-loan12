"""
Admin Panel API Endpoints
Handles all admin-related API requests for employees, processing requests, and profile management
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, Sum, F
from django.utils import timezone
from django.utils.crypto import get_random_string
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
import json

from .models import User, Loan, EmployeeProfile, LoanApplication, Agent, UserOnboardingProfile, UserOnboardingDocument
from .decorators import admin_required
from .onboarding_utils import collect_onboarding_payload, collect_onboarding_documents


# ============= PROCESSING REQUESTS / ASSIGN / APPLICATIONS =============

@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_processing_requests(request):
    """
    API Endpoint: Get all processing requests (waiting applications)
    Admin sees all, employees see only theirs
    Returns: JSON with loan details, assigned employee, status
    """
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
            # Employees see only their assigned loans
            loans = loans.filter(assigned_employee=user)
        elif user.role == 'agent':
            # Agents see only their assigned loans
            loans = loans.filter(assigned_agent__user=user)
        # Admin sees all
        
        # Filter by status - processing requests usually means waiting/follow_up
        if status_filter:
            loans = loans.filter(status=status_filter)
        else:
            # Default: show waiting and follow-up
            loans = loans.filter(status__in=['waiting', 'follow_up'])
        
        # Search by applicant name, phone, email
        if search:
            loans = loans.filter(
                Q(full_name__icontains=search) |
                Q(mobile_number__icontains=search) |
                Q(email__icontains=search)
            )
        
        # Order by assignment date (oldest first for follow-up priority)
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
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_reassign_processing_request(request):
    """
    API Endpoint: Reassign loan to different employee/agent
    Admin only
    """
    try:
        data = json.loads(request.body)
        loan = get_object_or_404(Loan, id=data.get('loan_id'))
        
        assignee_type = data.get('assignee_type', 'employee')  # 'employee' or 'agent'
        assignee_id = data.get('assignee_id')
        
        if assignee_type == 'employee':
            assignee = get_object_or_404(User, id=assignee_id, role='employee')
            loan.assigned_employee = assignee
            loan.assigned_agent = None
        else:
            assignee = get_object_or_404(Agent, id=assignee_id)
            loan.assigned_agent = assignee
            loan.assigned_employee = None
        
        loan.assigned_at = timezone.now()
        loan.status = 'waiting'
        loan.action_taken_at = None
        loan.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Loan reassigned successfully to {assignee}'
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


# ============= PROFILE MANAGEMENT API =============

@login_required
@require_GET
def api_get_user_profile(request):
    """
    API Endpoint: Get current user profile
    Works for admin and employee
    """
    try:
        user = request.user
        
        profile_data = {
            'id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'phone': user.phone or '',
            'address': user.address or '',
            'gender': user.gender or 'Other',
            'role': user.get_role_display(),
            'photo_url': user.profile_photo.url if user.profile_photo else '/static/images/default-avatar.png',
            'is_active': user.is_active,
            'created_at': user.created_at.isoformat() if hasattr(user, 'created_at') else None,
        }
        
        # Add employee profile info if employee
        if hasattr(user, 'employee_profile') and user.role == 'employee':
            emp_profile = user.employee_profile
            profile_data.update({
                'employee_role': emp_profile.get_employee_role_display(),
                'total_leads': emp_profile.total_leads,
                'approved_loans': emp_profile.approved_loans,
                'rejected_loans': emp_profile.rejected_loans,
                'total_disbursed': float(emp_profile.total_disbursed_amount),
            })
        
        return JsonResponse({
            'success': True,
            'profile': profile_data
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@require_POST
def api_update_user_profile(request):
    """
    API Endpoint: Update user profile
    Admin and employee can update their own profile
    """
    try:
        user = request.user
        data = json.loads(request.body)
        
        # Update basic user info
        if 'first_name' in data:
            user.first_name = data['first_name']
        if 'last_name' in data:
            user.last_name = data['last_name']
        if 'phone' in data:
            user.phone = data['phone']
        if 'address' in data:
            user.address = data['address']
        if 'gender' in data:
            user.gender = data['gender']
        
        # Email change (check uniqueness)
        if 'email' in data:
            if User.objects.filter(email=data['email']).exclude(id=user.id).exists():
                return JsonResponse({
                    'success': False,
                    'error': 'Email already in use'
                }, status=400)
            user.email = data['email']
        
        user.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Profile updated successfully',
            'profile': {
                'id': user.id,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'phone': user.phone or '',
                'address': user.address or '',
                'gender': user.gender or 'Other',
            }
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
        }, status=400)


@login_required
@require_POST
def api_change_user_password(request):
    """
    API Endpoint: Change user password
    """
    try:
        user = request.user
        data = json.loads(request.body)
        
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')
        
        # Validate current password
        if not user.check_password(current_password):
            return JsonResponse({
                'success': False,
                'error': 'Current password is incorrect'
            }, status=400)
        
        # Check passwords match
        if new_password != confirm_password:
            return JsonResponse({
                'success': False,
                'error': 'New passwords do not match'
            }, status=400)
        
        # Check password strength
        if len(new_password) < 8:
            return JsonResponse({
                'success': False,
                'error': 'Password must be at least 8 characters long'
            }, status=400)
        
        # Set new password
        user.set_password(new_password)
        user.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Password changed successfully'
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
        }, status=400)


@login_required
@require_POST
def api_upload_profile_photo(request):
    """
    API Endpoint: Upload profile photo
    """
    try:
        user = request.user
        
        if 'photo' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': 'No photo provided'
            }, status=400)
        
        photo = request.FILES['photo']
        
        # Validate file type
        allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
        if photo.content_type not in allowed_types:
            return JsonResponse({
                'success': False,
                'error': 'Invalid file type. Allowed: JPG, PNG, GIF, WebP'
            }, status=400)
        
        # Validate file size (max 5MB)
        if photo.size > 5 * 1024 * 1024:
            return JsonResponse({
                'success': False,
                'error': 'File size exceeds 5MB limit'
            }, status=400)
        
        user.profile_photo = photo
        user.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Photo uploaded successfully',
            'photo_url': user.profile_photo.url
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


# ============= ADMIN-ONLY STATISTICS =============

@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_dashboard_stats(request):
    """
    API Endpoint: Get admin dashboard statistics
    """
    try:
        from datetime import timedelta
        
        # Count loans by status
        new_entries = Loan.objects.filter(status='new_entry').count()
        waiting = Loan.objects.filter(status='waiting').count()
        follow_up = Loan.objects.filter(status='follow_up').count()
        approved = Loan.objects.filter(status='approved').count()
        rejected = Loan.objects.filter(status='rejected').count()
        disbursed = Loan.objects.filter(status='disbursed').count()
        
        # Financial stats
        total_loan_amount = Loan.objects.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
        disbursed_amount = Loan.objects.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
        
        # Employee stats
        total_employees = User.objects.filter(role='employee', is_active=True).count()
        total_agents = Agent.objects.filter(status='active').count()
        
        # Daily loan trend (last 7 days)
        daily_trend = []
        today = timezone.now().date()
        for i in range(6, -1, -1):  # Last 7 days
            date = today - timedelta(days=i)
            count = Loan.objects.filter(created_at__date=date).count()
            daily_trend.append({
                'date': date.strftime('%m/%d'),
                'day': date.strftime('%a'),
                'count': count
            })
        
        return JsonResponse({
            'success': True,
            'total_new_entry': new_entries,
            'waiting_for_processing': waiting,
            'required_follow_up': follow_up,
            'approved': approved,
            'rejected': rejected,
            'disbursed': disbursed,
            'total_applications': new_entries + waiting + follow_up + approved + rejected + disbursed,
            'total_loan_amount': float(total_loan_amount),
            'disbursed_amount': float(disbursed_amount),
            'total_employees': total_employees,
            'total_agents': total_agents,
            'loan_status_breakdown': {
                'new_entry': new_entries,
                'waiting': waiting,
                'follow_up': follow_up,
                'approved': approved,
                'rejected': rejected,
                'disbursed': disbursed
            },
            'daily_loan_trend': daily_trend
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

# ============= NEW ENTRY ASSIGN ENDPOINTS =============

@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_new_entries(request):
    """
    API Endpoint: Get all new/unassigned loan applications for admin to assign to employees
    """
    try:
        search = request.GET.get('search', '').strip()
        status_filter = request.GET.get('status', '').strip()
        page = request.GET.get('page', 1)
        per_page = int(request.GET.get('per_page', 10))
        
        # Get applications with 'new_entry' or 'assigned' but not yet processing status
        applications = Loan.objects.filter(
            Q(status='new_entry') | Q(status='assigned')
        ).select_related('assigned_agent', 'assigned_employee', 'created_by')
        
        # Apply status filter
        if status_filter:
            if status_filter == 'pending':
                applications = applications.filter(status='new_entry', assigned_employee__isnull=True)
            elif status_filter == 'assigned':
                applications = applications.filter(assigned_employee__isnull=False, status='assigned')
            elif status_filter == 'processing':
                applications = applications.filter(status='processing')
            elif status_filter == 'completed':
                applications = applications.filter(status__in=['approved', 'disbursed', 'rejected'])
        
        # Apply search filter
        if search:
            applications = applications.filter(
                Q(full_name__icontains=search) |
                Q(loan_id__icontains=search) |
                Q(mobile_number__icontains=search) |
                Q(email__icontains=search)
            )
        
        # Order by creation date
        applications = applications.order_by('-created_at')
        
        # Pagination
        from django.core.paginator import Paginator
        paginator = Paginator(applications, per_page)
        page_obj = paginator.get_page(page)
        
        # Serialize data
        apps_list = []
        for app in page_obj:
            # Determine status for assignment
            if app.status == 'new_entry' and not app.assigned_employee:
                app_status = 'pending'
            elif app.assigned_employee and app.status == 'assigned':
                app_status = 'assigned'
            elif app.status == 'processing':
                app_status = 'processing'
            else:
                app_status = 'completed'
            
            apps_list.append({
                'id': app.id,
                'loan_id': app.loan_id or f'LOAN-{app.id}',
                'applicant_name': app.full_name,
                'applicant_phone': app.mobile_number,
                'applicant_email': app.email or 'N/A',
                'applicant_address': app.get('address', '') if isinstance(app.extra_details, dict) else '',
                'agent_name': app.assigned_agent.name if app.assigned_agent else 'Unknown Agent',
                'loan_amount': float(app.loan_amount),
                'loan_type': app.get_loan_type_display(),
                'duration_months': app.duration_months if hasattr(app, 'duration_months') else 12,
                'interest_rate': app.interest_rate if hasattr(app, 'interest_rate') else 0,
                'processing_fee': float(app.processing_fee) if hasattr(app, 'processing_fee') else 0,
                'status': app_status,
                'assigned_employee': app.assigned_employee.get_full_name() if app.assigned_employee else None,
                'created_at': app.created_at.isoformat() if app.created_at else None
            })
        
        return JsonResponse({
            'success': True,
            'applications': apps_list,
            'total_count': paginator.count,
            'page_count': paginator.num_pages,
            'current_page': page_obj.number
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_new_entry_detail(request, applicant_id):
    """
    API Endpoint: Get detailed information about a specific loan application
    """
    try:
        app = get_object_or_404(Loan, id=applicant_id)
        
        return JsonResponse({
            'success': True,
            'application': {
                'id': app.id,
                'loan_id': app.loan_id or f'LOAN-{app.id}',
                'applicant_name': app.full_name,
                'applicant_phone': app.mobile_number,
                'applicant_email': app.email or 'N/A',
                'applicant_address': getattr(app, 'address', '') if app.extra_details and isinstance(app.extra_details, dict) else '',
                'agent_name': app.assigned_agent.name if app.assigned_agent else 'Unknown Agent',
                'loan_amount': float(app.loan_amount),
                'loan_type': app.get_loan_type_display(),
                'duration_months': app.duration_months if hasattr(app, 'duration_months') else 12,
                'interest_rate': app.interest_rate if hasattr(app, 'interest_rate') else 0,
                'processing_fee': float(app.processing_fee) if hasattr(app, 'processing_fee') else 0,
                'status': app.status,
                'assigned_employee': app.assigned_employee.get_full_name() if app.assigned_employee else None,
                'created_at': app.created_at.isoformat() if app.created_at else None
            }
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_admin_assign_application_to_employee(request, applicant_id):
    """
    API Endpoint: Assign a loan application to an employee for processing
    """
    try:
        app = get_object_or_404(Loan, id=applicant_id)
        data = json.loads(request.body)
        
        employee_id = data.get('employee_id')
        notes = data.get('notes', '')
        
        if not employee_id:
            return JsonResponse({
                'success': False,
                'error': 'Employee ID is required'
            }, status=400)
        
        employee = get_object_or_404(User, id=employee_id, role='employee')
        
        # Assign the application
        app.assigned_employee = employee
        app.status = 'assigned'
        app.assigned_at = timezone.now()
        
        # Store assignment notes
        if app.extra_details is None:
            app.extra_details = {}
        if isinstance(app.extra_details, dict):
            app.extra_details['assignment_notes'] = notes
            app.extra_details['assigned_by'] = request.user.get_full_name()
        
        app.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Application assigned to {employee.get_full_name()} successfully'
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


# ============= EMPLOYEE ASSIGNED LOANS ENDPOINTS =============

@login_required(login_url='login')
@require_GET
def api_employee_assigned_loans(request):
    """
    API Endpoint: Get loans assigned to the current employee
    """
    try:
        if request.user.role != 'employee':
            return JsonResponse({
                'success': False,
                'error': 'Access denied'
            }, status=403)
        
        search = request.GET.get('search', '').strip()
        status_filter = request.GET.get('status', '').strip()
        page = request.GET.get('page', 1)
        per_page = int(request.GET.get('per_page', 10))
        
        # Get loans assigned to this employee
        loans = Loan.objects.filter(assigned_employee=request.user)
        
        # Apply status filter
        if status_filter:
            loans = loans.filter(status=status_filter)
        
        # Apply search filter
        if search:
            loans = loans.filter(
                Q(full_name__icontains=search) |
                Q(loan_id__icontains=search) |
                Q(mobile_number__icontains=search) |
                Q(email__icontains=search)
            )
        
        # Order by assignment date
        loans = loans.order_by('-assigned_at')
        
        # Pagination
        from django.core.paginator import Paginator
        paginator = Paginator(loans, per_page)
        page_obj = paginator.get_page(page)
        
        # Serialize data
        loans_list = []
        for loan in page_obj:
            loans_list.append({
                'id': loan.id,
                'loan_id': loan.loan_id or f'LOAN-{loan.id}',
                'applicant_name': loan.full_name,
                'applicant_phone': loan.mobile_number,
                'applicant_email': loan.email or 'N/A',
                'applicant_address': getattr(loan, 'address', '') if loan.extra_details and isinstance(loan.extra_details, dict) else '',
                'loan_amount': float(loan.loan_amount),
                'loan_type': loan.get_loan_type_display(),
                'duration_months': loan.duration_months if hasattr(loan, 'duration_months') else 12,
                'interest_rate': loan.interest_rate if hasattr(loan, 'interest_rate') else 0,
                'processing_fee': float(loan.processing_fee) if hasattr(loan, 'processing_fee') else 0,
                'status': loan.status,
                'assigned_at': loan.assigned_at.isoformat() if loan.assigned_at else None,
                'created_at': loan.created_at.isoformat() if loan.created_at else None
            })
        
        return JsonResponse({
            'success': True,
            'loans': loans_list,
            'total_count': paginator.count,
            'page_count': paginator.num_pages,
            'current_page': page_obj.number
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='login')
@require_POST
def api_employee_loan_action(request, loan_id):
    """
    API Endpoint: Employee performs action on assigned loan (approve/reject/disburse/process)
    """
    try:
        if request.user.role != 'employee':
            return JsonResponse({
                'success': False,
                'error': 'Access denied'
            }, status=403)
        
        loan = get_object_or_404(Loan, id=loan_id, assigned_employee=request.user)
        data = json.loads(request.body)
        
        action = data.get('action')
        notes = data.get('notes', '')
        
        if action == 'processing':
            loan.status = 'processing'
        elif action == 'approve':
            loan.status = 'approved'
        elif action == 'reject':
            loan.status = 'rejected'
        elif action == 'disburse':
            loan.status = 'disbursed'
            # Store disbursement details
            if loan.extra_details is None:
                loan.extra_details = {}
            if isinstance(loan.extra_details, dict):
                loan.extra_details['disbursement_details'] = {
                    'account_holder': data.get('account_holder'),
                    'account_number': data.get('account_number'),
                    'ifsc_code': data.get('ifsc_code'),
                    'bank_name': data.get('bank_name'),
                    'disbursed_date': timezone.now().isoformat(),
                    'notes': notes
                }
        else:
            return JsonResponse({
                'success': False,
                'error': 'Invalid action'
            }, status=400)
        
        # Store action notes
        if loan.extra_details is None:
            loan.extra_details = {}
        if isinstance(loan.extra_details, dict):
            loan.extra_details[f'{action}_notes'] = notes
            loan.extra_details[f'{action}_by'] = request.user.get_full_name()
            loan.extra_details[f'{action}_at'] = timezone.now().isoformat()
        
        loan.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Loan {action}d successfully'
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='login')
@require_POST
def api_employee_loan_update_status(request, loan_id):
    """
    API Endpoint: Employee updates loan status
    """
    try:
        if request.user.role != 'employee':
            return JsonResponse({
                'success': False,
                'error': 'Access denied'
            }, status=403)
        
        loan = get_object_or_404(Loan, id=loan_id, assigned_employee=request.user)
        data = json.loads(request.body)
        
        status = data.get('status')
        notes = data.get('notes', '')
        
        valid_statuses = ['assigned', 'processing', 'approved', 'rejected', 'disbursed']
        if status not in valid_statuses:
            return JsonResponse({
                'success': False,
                'error': 'Invalid status'
            }, status=400)
        
        loan.status = status
        
        # Store status update notes
        if loan.extra_details is None:
            loan.extra_details = {}
        if isinstance(loan.extra_details, dict):
            loan.extra_details['status_notes'] = notes
            loan.extra_details['updated_by'] = request.user.get_full_name()
            loan.extra_details['updated_at'] = timezone.now().isoformat()
        
        loan.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Loan status updated successfully'
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


# ============= CREATE NEW EMPLOYEE =============

@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_create_employee(request):
    """
    API Endpoint: Create new employee
    Admin only
    """
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        required_fields = ['first_name', 'email', 'phone', 'employee_id', 'username', 'password']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({
                    'success': False,
                    'error': f'{field} is required'
                }, status=400)
        
        # Check if email already exists
        if User.objects.filter(email=data['email']).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already exists'
            }, status=400)
        
        # Check if username already exists
        if User.objects.filter(username=data['username']).exists():
            return JsonResponse({
                'success': False,
                'error': 'Username already exists'
            }, status=400)
        
        # Create new employee user
        employee = User.objects.create_user(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            role='employee',
            is_active=True
        )
        
        # Create employee profile
        EmployeeProfile.objects.create(
            user=employee,
            phone=data.get('phone', ''),
            employee_id=data.get('employee_id', ''),
            department=data.get('department', 'General')
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Employee created successfully',
            'employee_id': employee.id,
            'employee_name': employee.get_full_name()
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


# ============= CREATE NEW AGENT =============

@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_create_agent(request):
    """
    API Endpoint: Create new agent
    Admin only
    """
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        required_fields = ['name', 'email', 'phone', 'agent_id', 'username', 'password']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({
                    'success': False,
                    'error': f'{field} is required'
                }, status=400)
        
        # Check if email already exists
        if User.objects.filter(email=data['email']).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already exists'
            }, status=400)
        
        # Check if username already exists
        if User.objects.filter(username=data['username']).exists():
            return JsonResponse({
                'success': False,
                'error': 'Username already exists'
            }, status=400)
        
        # Parse name into first and last name
        name_parts = data['name'].split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        # Create new agent user
        agent_user = User.objects.create_user(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            first_name=first_name,
            last_name=last_name,
            role='agent',
            is_active=True
        )
        
        # Create agent profile
        Agent.objects.create(
            user=agent_user,
            agent_id=data.get('agent_id', ''),
            phone=data.get('phone', ''),
            city=data.get('city', ''),
            status=data.get('status', 'active'),
            assigned_loans_count=0
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Agent created successfully',
            'agent_id': agent_user.id,
            'agent_name': agent_user.get_full_name()
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_add_agent(request):
    """
    API Endpoint: Add new agent with photo and address details (FormData)
    Admin only
    """
    try:
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        gender = request.POST.get('gender', 'Other').strip()
        address = request.POST.get('address', '').strip()
        password = request.POST.get('password', '').strip()
        profile_photo = request.FILES.get('profile_photo', None)

        # Validation
        if not name or not email or not phone or not password:
            return JsonResponse({
                'success': False,
                'error': 'Name, Email, Phone, and Password are required'
            }, status=400)

        # Check email uniqueness
        if User.objects.filter(email=email).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already registered'
            }, status=400)

        # Check phone uniqueness
        if User.objects.filter(phone=phone).exists() or Agent.objects.filter(phone=phone).exists():
            return JsonResponse({
                'success': False,
                'error': 'Phone number already registered'
            }, status=400)

        # Validate phone format (basic)
        phone_digits = phone.replace('+', '')
        if not phone_digits.isdigit() or len(phone_digits) < 10 or len(phone_digits) > 15:
            return JsonResponse({
                'success': False,
                'error': 'Phone number must be 10-15 digits'
            }, status=400)

        if len(password) < 6:
            return JsonResponse({
                'success': False,
                'error': 'Password must be at least 6 characters'
            }, status=400)

        # Generate username from email
        base_username = email.split('@')[0]
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        # Parse full name
        name_parts = name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        # Create User
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role='agent',
            phone=phone,
            gender=gender,
            address=address,
            is_active=True,
        )

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

        # Create Agent profile
        agent = Agent.objects.create(
            user=user,
            name=name,
            email=email,
            phone=phone,
            address=address,
            gender=gender,
            status='active',
            created_by=request.user
        )
        agent.city = request.POST.get('onb_perm_city', '').strip() or agent.city
        agent.state = request.POST.get('onb_perm_state', '').strip() or agent.state
        agent.pin_code = request.POST.get('onb_perm_pin', '').strip() or agent.pin_code
        agent.save()

        # Reuse user photo if available
        if user.profile_photo:
            agent.profile_photo = user.profile_photo
            agent.save()
        elif profile_photo:
            agent.profile_photo = profile_photo
            agent.save()

        onboarding_payload = collect_onboarding_payload(request)
        if onboarding_payload:
            profile, _ = UserOnboardingProfile.objects.get_or_create(
                user=user,
                defaults={'role': user.role, 'data': onboarding_payload},
            )
            if profile.data != onboarding_payload or profile.role != user.role:
                profile.data = onboarding_payload
                profile.role = user.role
                profile.save()

        for doc_type, doc_file in collect_onboarding_documents(request):
            if not doc_file:
                continue
            if doc_file.size > 10 * 1024 * 1024:
                continue
            UserOnboardingDocument.objects.create(
                user=user,
                document_type=doc_type or 'other',
                file=doc_file,
            )

        return JsonResponse({
            'success': True,
            'message': 'Agent added successfully',
            'agent': {
                'id': agent.id,
                'name': agent.name,
                'email': agent.email or '',
                'phone': agent.phone or '',
                'status': agent.status,
                'photo_url': agent.profile_photo.url if agent.profile_photo else '',
                'created_at': agent.created_at.strftime('%b %d, %Y') if agent.created_at else '',
            }
        }, status=201)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error: {str(e)}'
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_agent(request, agent_id):
    """API Endpoint: Get single agent details"""
    try:
        agent = get_object_or_404(Agent, id=agent_id)

        agent_user = agent.user
        submitted_qs = Loan.objects.none()
        if agent_user:
            submitted_qs = Loan.objects.filter(created_by=agent_user)

        assigned_qs = Loan.objects.filter(assigned_agent=agent)
        combined_qs = Loan.objects.filter(
            Q(assigned_agent=agent) | (Q(created_by=agent_user) if agent_user else Q(id__in=[]))
        ).select_related(
            'created_by',
            'assigned_employee',
            'assigned_agent',
        ).order_by('-created_at').distinct()

        status_map = {
            'new_entry': 'New Entry',
            'waiting': 'Waiting for Processing',
            'follow_up': 'Banking Processing',
            'approved': 'Approved',
            'rejected': 'Rejected',
            'disbursed': 'Disbursed',
            'forclose': 'For Close',
            'draft': 'Draft',
            'disputed': 'Disputed',
        }

        def owner_display(loan_obj):
            owner = loan_obj.created_by
            if not owner:
                return 'System', '-'
            role_label = {
                'admin': 'Admin',
                'subadmin': 'SubAdmin',
                'employee': 'Employee',
                'agent': 'Agent',
                'dsa': 'DSA',
            }.get(owner.role, owner.role.title() if owner.role else 'User')
            owner_name = owner.get_full_name() or owner.username or '-'
            return role_label, owner_name

        def latest_bank_remark(loan_obj):
            remarks = []
            if loan_obj.remarks:
                remarks.append(str(loan_obj.remarks).strip())

            related_app = None
            if loan_obj.email and loan_obj.mobile_number:
                related_app = LoanApplication.objects.filter(
                    applicant__email__iexact=loan_obj.email,
                    applicant__mobile=loan_obj.mobile_number,
                ).first()
            if not related_app and loan_obj.full_name and loan_obj.mobile_number:
                related_app = LoanApplication.objects.filter(
                    applicant__full_name__iexact=loan_obj.full_name,
                    applicant__mobile=loan_obj.mobile_number,
                ).first()

            if related_app:
                if related_app.approval_notes:
                    remarks.append(str(related_app.approval_notes).strip())
                if related_app.rejection_reason:
                    remarks.append(str(related_app.rejection_reason).strip())
                reasons = list(
                    related_app.status_history.exclude(reason__isnull=True)
                    .exclude(reason__exact='')
                    .values_list('reason', flat=True)[:5]
                )
                remarks.extend([str(r).strip() for r in reasons if r])

            seen = set()
            unique = []
            for item in remarks:
                clean = (item or '').strip()
                if not clean:
                    continue
                key = clean.lower()
                if key in seen:
                    continue
                seen.add(key)
                unique.append(clean)
            return " | ".join(unique)[:500] if unique else '-'

        customers = []
        for loan in combined_qs[:250]:
            role_label, role_name = owner_display(loan)
            source = 'Submitted' if agent_user and loan.created_by_id == agent_user.id else 'Assigned'
            assigned_to = '-'
            if loan.assigned_employee:
                assigned_to = f"Employee - {loan.assigned_employee.get_full_name() or loan.assigned_employee.username}"
            elif loan.assigned_agent:
                assigned_to = f"Agent - {loan.assigned_agent.name}"

            customers.append({
                'loan_id': loan.id,
                'loan_uid': loan.user_id or f'LOAN-{loan.id}',
                'customer_name': loan.full_name or '-',
                'mobile': loan.mobile_number or '-',
                'email': loan.email or '-',
                'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else (loan.loan_type or '-'),
                'loan_amount': float(loan.loan_amount or 0),
                'status': loan.status,
                'status_display': status_map.get(loan.status, loan.status),
                'source': source,
                'assigned_to': assigned_to,
                'under_whom': f"{role_label} - {role_name}",
                'owner_role': role_label,
                'owner_name': role_name,
                'bank_remark': latest_bank_remark(loan),
                'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else '',
            })

        summary = {
            'total_submitted_applications': submitted_qs.count(),
            'total_assigned_applications': assigned_qs.count(),
            'total_applications': combined_qs.count(),
            'approved': combined_qs.filter(status='approved').count(),
            'rejected': combined_qs.filter(status='rejected').count(),
            'banking_processing': combined_qs.filter(status='follow_up').count(),
            'waiting': combined_qs.filter(status='waiting').count(),
            'disbursed': combined_qs.filter(status='disbursed').count(),
            'total_customers': combined_qs.count(),
        }

        onboarding = {}
        documents = []
        if agent_user and hasattr(agent_user, 'onboarding_profile') and agent_user.onboarding_profile:
            onboarding = agent_user.onboarding_profile.data or {}
        if agent_user and hasattr(agent_user, 'onboarding_documents'):
            documents = [
                {
                    'type': doc.document_type or 'other',
                    'url': doc.file.url if doc.file else '',
                    'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else '',
                }
                for doc in agent_user.onboarding_documents.all()
            ]

        return JsonResponse({
            'success': True,
            'agent': {
                'id': agent.id,
                'name': agent.name,
                'email': agent.email or '',
                'phone': agent.phone or '',
                'address': agent.address or '',
                'gender': agent.gender or 'Other',
                'status': agent.status or 'active',
                'photo_url': agent.profile_photo.url if agent.profile_photo else '',
            },
            'summary': summary,
            'customers': customers,
            'onboarding': onboarding,
            'documents': documents,
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_update_agent(request, agent_id):
    """API Endpoint: Update agent details"""
    try:
        agent = get_object_or_404(Agent, id=agent_id)
        data = json.loads(request.body)

        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        address = data.get('address', '').strip()
        gender = data.get('gender', '').strip()
        status_val = data.get('status', '').strip()

        # Validate required fields
        if not name or not email or not phone:
            return JsonResponse({
                'success': False,
                'error': 'Name, Email, and Phone are required'
            }, status=400)

        # Email uniqueness (exclude current user)
        if User.objects.filter(email=email).exclude(id=getattr(agent.user, 'id', None)).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already exists'
            }, status=400)

        # Phone uniqueness
        if User.objects.filter(phone=phone).exclude(id=getattr(agent.user, 'id', None)).exists():
            return JsonResponse({
                'success': False,
                'error': 'Phone number already exists'
            }, status=400)

        # Update agent fields
        agent.name = name
        agent.email = email
        agent.phone = phone
        agent.address = address
        if gender:
            agent.gender = gender
        if status_val in ['active', 'blocked']:
            agent.status = status_val
        agent.save()

        # Update linked user if exists
        if agent.user:
            name_parts = name.split(' ', 1)
            agent.user.first_name = name_parts[0]
            agent.user.last_name = name_parts[1] if len(name_parts) > 1 else ''
            agent.user.email = email
            agent.user.phone = phone
            agent.user.address = address
            if gender:
                agent.user.gender = gender
            if status_val in ['active', 'blocked']:
                agent.user.is_active = status_val == 'active'
            agent.user.save()

        return JsonResponse({
            'success': True,
            'message': 'Agent updated successfully'
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
@admin_required
@require_POST
def api_delete_agent(request, agent_id):
    """API Endpoint: Delete (soft block) agent"""
    try:
        agent = get_object_or_404(Agent, id=agent_id)
        agent.status = 'blocked'
        agent.save()

        if agent.user:
            agent.user.is_active = False
            agent.user.save()

        return JsonResponse({
            'success': True,
            'message': 'Agent deleted successfully'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
