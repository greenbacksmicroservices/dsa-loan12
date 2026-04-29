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
import re

from .models import User, EmployeeProfile, LoanApplication, Loan, UserOnboardingProfile, UserOnboardingDocument
from .onboarding_utils import collect_onboarding_payload, collect_onboarding_documents
from .decorators import admin_required
from django.contrib.auth.models import Group


def is_admin(user):
    """Check if user is admin"""
    return user.is_authenticated and user.role == 'admin'


def _role_label(user_obj):
    role = getattr(user_obj, 'role', '') or ''
    return {
        'admin': 'Admin',
        'subadmin': 'Partner',
        'employee': 'Employee',
        'agent': 'Channel Partner',
        'dsa': 'DSA',
    }.get(role, role.title() if role else 'System')


def _extract_subadmin_id(notes):
    match = re.search(r'\[subadmin:(\d+)\]', str(notes or ''), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _resolve_creator_info(user_obj, onboarding_payload=None, employee_profile=None):
    payload = onboarding_payload or {}
    meta = payload.get('_meta') if isinstance(payload, dict) else None
    creator_role = ''
    creator_name = ''

    if isinstance(meta, dict):
        creator_role = str(meta.get('created_by_role') or '').strip()
        creator_name = str(meta.get('created_by_name') or '').strip()

    if not creator_role or not creator_name:
        profile = employee_profile or getattr(user_obj, 'employee_profile', None)
        subadmin_id = _extract_subadmin_id(getattr(profile, 'notes', '')) if profile else None
        if subadmin_id:
            subadmin = User.objects.filter(id=subadmin_id, role='subadmin').only('first_name', 'last_name', 'username').first()
            if subadmin:
                creator_role = 'Partner'
                creator_name = subadmin.get_full_name() or subadmin.username or 'Partner'

    if not creator_role or not creator_name:
        creator_role = 'Admin'
        creator_name = 'System'

    return {
        'role': creator_role,
        'name': creator_name,
        'display': f"{creator_role} - {creator_name}",
    }


def _extract_location(onboarding_payload, user_obj=None):
    payload = onboarding_payload or {}
    section1 = payload.get('section1') if isinstance(payload, dict) else {}
    perm = (section1 or {}).get('permanent_address') or {}
    city = (perm.get('city') or '').strip()
    pin = (perm.get('pin_code') or '').strip()
    district = (perm.get('district') or '').strip()

    if not city and isinstance(payload, dict):
        city = str(payload.get('city') or '').strip()
    if not pin and isinstance(payload, dict):
        pin = str(payload.get('pin_code') or payload.get('pin') or '').strip()
    if not district and isinstance(payload, dict):
        district = str(payload.get('district') or '').strip()

    if user_obj and (not city or not pin or not district):
        address_text = str(getattr(user_obj, 'address', '') or '')
        if address_text:
            if not city:
                city_match = re.search(r'City:\s*([^|,\n]+)', address_text, flags=re.IGNORECASE)
                if city_match:
                    city = city_match.group(1).strip()
            if not district:
                district_match = re.search(r'District:\s*([^|,\n]+)', address_text, flags=re.IGNORECASE)
                if district_match:
                    district = district_match.group(1).strip()
            if not pin:
                pin_match = re.search(r'PIN:\s*([A-Za-z0-9-]+)', address_text, flags=re.IGNORECASE)
                if pin_match:
                    pin = pin_match.group(1).strip()

    return city, pin, district


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
def employee_add_new(request):
    """
    Form page to add a new employee - Admin Only
    """
    context = {
        'page_title': 'Add New Employee',
        'page_subtitle': 'Create a new employee account with basic details',
    }
    return render(request, 'core/admin/employee_add_new.html', context)



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
        employees = User.objects.filter(role='employee').select_related('employee_profile', 'onboarding_profile')
        
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
            onboarding_payload = {}
            if hasattr(user, 'onboarding_profile') and user.onboarding_profile:
                onboarding_payload = user.onboarding_profile.data or {}
            creator_info = _resolve_creator_info(user, onboarding_payload, employee_profile)
            city, pin_code, district = _extract_location(onboarding_payload, user)
            
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
                'gender': user.gender or 'Other',
                'state': ((onboarding_payload.get('section1') or {}).get('permanent_address') or {}).get('state') or '-',
                'city': city or '-',
                'district': district or '-',
                'address': user.address or '-',
                'pin_code': pin_code or '-',
                'created_under': creator_info['display'],
                'role': employee_profile.get_employee_role_display() if employee_profile else 'Loan Processor',
                'status': 'active' if user.is_active else 'inactive',
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
@admin_required
@require_http_methods(["POST"])
def api_add_employee(request):
    """
    API Endpoint: Add new employee with photo and address details
    Accepts FormData including file upload
    Creates User and EmployeeProfile records
    """
    try:
        # Get form data and files
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '').strip()
        gender = request.POST.get('gender', 'Other').strip()
        address = request.POST.get('address', '').strip()
        pin_code = request.POST.get('pin_code', '').strip() or request.POST.get('onb_perm_pin', '').strip()
        state = request.POST.get('state', '').strip() or request.POST.get('onb_perm_state', '').strip()
        city = request.POST.get('city', '').strip() or request.POST.get('onb_perm_city', '').strip()
        district = request.POST.get('district', '').strip() or request.POST.get('onb_perm_district', '').strip()
        dob = request.POST.get('onb_dob', '').strip()
        profile_photo = request.FILES.get('profile_photo', None)
        
        # Validation
        required_fields = {
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'password': password,
            'city': city,
            'district': district,
            'pin_code': pin_code,
        }
        
        for field_name, field_value in required_fields.items():
            if not field_value:
                return JsonResponse({
                    'success': False,
                    'error': f'{field_name.replace("_", " ").title()} is required'
                }, status=400)
        
        if len(password) < 6:
            return JsonResponse({
                'success': False,
                'error': 'Password must be at least 6 characters'
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
        
        # Validate phone format (basic)
        if len(phone) < 10 or len(phone) > 15:
            return JsonResponse({
                'success': False,
                'error': 'Phone number must be 10-15 digits'
            }, status=400)

        if not pin_code.isdigit() or len(pin_code) != 6:
            return JsonResponse({
                'success': False,
                'error': 'PIN code must be 6 digits'
            }, status=400)
        
        # Parse full name
        name_parts = full_name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        # Create User
        # Store address-related fields in address text (User model does not have city/state/pin_code columns)
        address_parts = [address]
        if city:
            address_parts.append(f"City: {city}")
        if district:
            address_parts.append(f"District: {district}")
        if state:
            address_parts.append(f"State: {state}")
        if pin_code:
            address_parts.append(f"PIN: {pin_code}")
        normalized_address = " | ".join([part for part in address_parts if part])

        base_username = email.split('@')[0]
        username = base_username
        suffix = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{suffix}"
            suffix += 1

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            role='employee',
            gender=gender,
            address=normalized_address,
            is_active=True,
            date_of_birth=dob or None,
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
        
        # Create EmployeeProfile
        employee_profile = EmployeeProfile.objects.create(
            user=user,
            employee_role='loan_processor',
        )

        onboarding_payload = collect_onboarding_payload(request)
        creator_info = {
            'created_by_id': request.user.id,
            'created_by_name': request.user.get_full_name() or request.user.username or 'System',
            'created_by_role': _role_label(request.user),
        }
        if isinstance(onboarding_payload, dict):
            onboarding_payload['_meta'] = creator_info
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
        
        created_under = f"{creator_info['created_by_role']} - {creator_info['created_by_name']}"
        return JsonResponse({
            'success': True,
            'message': 'Employee added successfully',
            'employee': {
                'id': user.id,
                'name': user.get_full_name() or user.username,
                'email': user.email,
                'phone': user.phone or '',
                'gender': user.gender or 'Other',
                'address': user.address or '',
                'photo_url': user.profile_photo.url if user.profile_photo else '',
                'created_at': user.date_joined.strftime('%b %d, %Y') if user.date_joined else '',
                'status': 'active',
                'city': city or '-',
                'pin_code': pin_code or '-',
                'district': district or '-',
                'created_under': created_under,
            }
        }, status=201)
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error: {str(e)}'
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

        loans_submitted_qs = Loan.objects.filter(created_by=user)
        loans_assigned_qs = Loan.objects.filter(assigned_employee=user)
        loans_qs = Loan.objects.filter(
            Q(created_by=user) | Q(assigned_employee=user)
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

        def get_owner_display(loan_obj):
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
        for loan in loans_qs[:250]:
            owner_role, owner_name = get_owner_display(loan)
            source = 'Submitted' if loan.created_by_id == user.id else 'Assigned'
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
                'under_whom': f"{owner_role} - {owner_name}",
                'owner_role': owner_role,
                'owner_name': owner_name,
                'bank_remark': latest_bank_remark(loan),
                'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else '',
            })

        assigned_loans = loans_assigned_qs.count()
        total_applications = loans_qs.count()
        approved_count = loans_qs.filter(status='approved').count()
        rejected_count = loans_qs.filter(status='rejected').count()
        followup_count = loans_qs.filter(status='follow_up').count()
        waiting_count = loans_qs.filter(status='waiting').count()
        disbursed_count = loans_qs.filter(status='disbursed').count()

        summary = {
            'total_submitted_applications': loans_submitted_qs.count(),
            'total_assigned_applications': assigned_loans,
            'total_applications': total_applications,
            'approved': approved_count,
            'rejected': rejected_count,
            'banking_processing': followup_count,
            'waiting': waiting_count,
            'disbursed': disbursed_count,
            'total_customers': total_applications,
        }

        onboarding = {}
        documents = []
        if hasattr(user, 'onboarding_profile') and user.onboarding_profile:
            onboarding = user.onboarding_profile.data or {}
        if hasattr(user, 'onboarding_documents'):
            documents = [
                {
                    'type': doc.document_type or 'other',
                    'url': doc.file.url if doc.file else '',
                    'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else '',
                }
                for doc in user.onboarding_documents.all()
            ]
        creator_info = _resolve_creator_info(user, onboarding, profile)
        city, pin_code, district = _extract_location(onboarding, user)

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
                'disbursed_amount': float(profile.total_disbursed_amount) if profile else 0.0,
                'assigned_loans': assigned_loans,
                'notes': profile.notes if profile else '',
                'city': city or '-',
                'pin_code': pin_code or '-',
                'district': district or '-',
                'created_under': creator_info['display'],
                'created_by_role': creator_info['role'],
                'created_by_name': creator_info['name'],
            }
            ,
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
