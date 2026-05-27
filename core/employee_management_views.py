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
from collections import defaultdict
import json
import re

from .models import User, EmployeeProfile, LoanApplication, Loan, UserOnboardingProfile, UserOnboardingDocument, Agent, AgentAssignment
from .onboarding_utils import collect_onboarding_payload, collect_onboarding_documents, collect_user_document_payload
from .decorators import admin_required
from .id_utils import generate_user_sequence_id
from .account_notifications import send_account_credentials_email
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


SUBADMIN_TAG_PATTERN = re.compile(r'\[subadmin:\d+\]', flags=re.IGNORECASE)


def _set_employee_under_subadmin(employee_user, subadmin_user=None):
    profile, _ = EmployeeProfile.objects.get_or_create(user=employee_user)
    notes = SUBADMIN_TAG_PATTERN.sub('', str(profile.notes or '')).strip()
    notes = re.sub(r'\n{3,}', '\n\n', notes)
    if subadmin_user:
        tag = f"[subadmin:{subadmin_user.id}]"
        notes = f"{notes}\n{tag}".strip() if notes else tag
    profile.notes = notes
    profile.save(update_fields=['notes', 'updated_at'])
    return profile


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


def _parse_channel_partner_ids(raw_values):
    ids = []
    for value in raw_values or []:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            ids.append(parsed)
    return sorted(set(ids))


def _sync_employee_channel_partners(employee_user, channel_partner_ids, assigned_by_user=None):
    """
    Keep AgentAssignment rows in sync for a single employee.
    Admin scope: any active agent can be linked.
    """
    valid_ids = set(
        Agent.objects.filter(id__in=channel_partner_ids, status='active').values_list('id', flat=True)
    )

    AgentAssignment.objects.filter(employee=employee_user).exclude(agent_id__in=valid_ids).delete()
    existing_ids = set(
        AgentAssignment.objects.filter(employee=employee_user, agent_id__in=valid_ids).values_list('agent_id', flat=True)
    )
    create_rows = [
        AgentAssignment(agent_id=agent_id, employee=employee_user, assigned_by=assigned_by_user)
        for agent_id in valid_ids
        if agent_id not in existing_ids
    ]
    if create_rows:
        AgentAssignment.objects.bulk_create(create_rows, ignore_conflicts=True)

    Agent.objects.filter(under_employee=employee_user).exclude(id__in=valid_ids).update(under_employee=None)
    Agent.objects.filter(id__in=valid_ids).update(under_employee=employee_user)

    profile = getattr(employee_user, 'employee_profile', None)
    subadmin_id = _extract_subadmin_id(getattr(profile, 'notes', '')) if profile else None
    if subadmin_id:
        subadmin = User.objects.filter(id=subadmin_id, role='subadmin', is_active=True).first()
        if subadmin:
            Agent.objects.filter(id__in=valid_ids).update(created_by=subadmin)
    elif assigned_by_user and getattr(assigned_by_user, 'role', '') == 'admin':
        Agent.objects.filter(id__in=valid_ids).update(created_by=assigned_by_user)


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
        employees = User.objects.filter(role='employee').select_related(
            'employee_profile',
            'onboarding_profile',
        ).order_by('-date_joined', '-id')
        
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
                'employee_id': user.employee_id or f'EDC-EMP-{user.id:04d}',
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
        username = request.POST.get('username', '').strip()
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
        assigned_subadmin_id = request.POST.get('assigned_subadmin_id', '').strip()
        channel_partner_ids = _parse_channel_partner_ids(request.POST.getlist('channel_partner_ids'))
        profile_photo = request.FILES.get('profile_photo') or request.FILES.get('photo')
        
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

        # Deleted/inactive employees do not reserve contact details.
        if User.objects.filter(email__iexact=email, is_active=True).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already registered for an active employee'
            }, status=400)

        selected_subadmin = None
        if assigned_subadmin_id:
            try:
                selected_subadmin = User.objects.get(
                    id=int(assigned_subadmin_id),
                    role='subadmin',
                    is_active=True,
                )
            except (TypeError, ValueError, User.DoesNotExist):
                return JsonResponse({
                    'success': False,
                    'error': 'Selected partner was not found'
                }, status=400)

        # Check phone uniqueness against active records only.
        if User.objects.filter(phone=phone, is_active=True).exists():
            return JsonResponse({
                'success': False,
                'error': 'Phone number already registered for an active employee'
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

        if username:
            if User.objects.filter(username=username).exists():
                return JsonResponse({
                    'success': False,
                    'error': 'Username already registered'
                }, status=400)
        else:
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
            employee_id=generate_user_sequence_id('employee'),
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

        if selected_subadmin:
            from .subadmin_views import _mark_employee_under_subadmin
            _mark_employee_under_subadmin(user, selected_subadmin)

        _sync_employee_channel_partners(user, channel_partner_ids, assigned_by_user=request.user)

        onboarding_payload = collect_onboarding_payload(request)
        creator_user = selected_subadmin or request.user
        creator_info = {
            'created_by_id': creator_user.id,
            'created_by_name': creator_user.get_full_name() or creator_user.username or 'System',
            'created_by_role': _role_label(creator_user),
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
        email_sent, email_detail = send_account_credentials_email(
            request=request,
            email=user.email,
            full_name=user.get_full_name() or user.username,
            username=user.username,
            password=password,
            role=user.role,
            account_id=user.employee_id,
        )
        return JsonResponse({
            'success': True,
            'message': 'Employee added successfully',
            'email_sent': email_sent,
            'email_message': email_detail,
            'employee': {
                'id': user.id,
                'employee_id': user.employee_id or '',
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
                'assigned_subadmin_id': selected_subadmin.id if selected_subadmin else '',
                'assigned_channel_partner_ids': channel_partner_ids,
                'channel_partner_count': len(channel_partner_ids),
                'total_applications': 0,
                'approved_applications': 0,
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
        is_json = bool(request.content_type and 'application/json' in request.content_type)
        data = json.loads(request.body) if is_json else request.POST
        channel_partner_ids = None
        if 'channel_partner_ids' in data:
            channel_partner_ids = _parse_channel_partner_ids(
                data.get('channel_partner_ids') if is_json else request.POST.getlist('channel_partner_ids')
            )
        assigned_subadmin_present = 'assigned_subadmin_id' in data
        selected_subadmin = None
        if assigned_subadmin_present:
            assigned_subadmin_id = str(data.get('assigned_subadmin_id', '') or '').strip()
            if assigned_subadmin_id:
                try:
                    selected_subadmin = User.objects.get(
                        id=int(assigned_subadmin_id),
                        role='subadmin',
                        is_active=True,
                    )
                except (TypeError, ValueError, User.DoesNotExist):
                    return JsonResponse({
                        'success': False,
                        'error': 'Selected partner was not found'
                    }, status=400)
        
        # Update User fields
        if 'email' in data:
            # Check email uniqueness (excluding current user)
            if (
                User.objects.filter(email__iexact=data['email'], is_active=True)
                .exclude(id=user.id)
                .exists()
            ):
                return JsonResponse({
                    'success': False,
                    'error': 'Email already exists for an active employee'
                }, status=400)
            user.email = data['email']
        
        if 'full_name' in data:
            full_name = data['full_name'].strip().split(' ', 1)
            user.first_name = full_name[0]
            user.last_name = full_name[1] if len(full_name) > 1 else ''
        
        if 'phone' in data:
            if User.objects.filter(phone=data['phone'], is_active=True).exclude(id=user.id).exists():
                return JsonResponse({
                    'success': False,
                    'error': 'Phone number already exists for an active employee'
                }, status=400)
            user.phone = data['phone']
        
        if 'address' in data:
            user.address = data['address']
        
        if 'gender' in data:
            user.gender = data['gender']
        
        if 'password' in data and data['password']:
            user.set_password(data['password'])
        
        if 'status' in data:
            user.is_active = data['status'] == 'active'

        profile_photo = request.FILES.get('profile_photo') or request.FILES.get('photo')
        if profile_photo:
            if profile_photo.size > 5 * 1024 * 1024:
                return JsonResponse({
                    'success': False,
                    'error': 'Profile photo must be less than 5MB'
                }, status=400)
            user.profile_photo = profile_photo
        
        user.save()

        if channel_partner_ids is not None:
            _sync_employee_channel_partners(user, channel_partner_ids, assigned_by_user=request.user)
        if assigned_subadmin_present:
            _set_employee_under_subadmin(user, selected_subadmin)
        
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

        if assigned_subadmin_present:
            _set_employee_under_subadmin(user, selected_subadmin)
            if channel_partner_ids is not None:
                _sync_employee_channel_partners(user, channel_partner_ids, assigned_by_user=request.user)
        
        return JsonResponse({
            'success': True,
            'message': 'Employee updated successfully',
            'photo_url': user.profile_photo.url if user.profile_photo else '',
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
        from .subadmin_views import _serialize_subadmin_loan_details

        def get_owner_display(loan_obj):
            owner = loan_obj.created_by
            if not owner:
                return 'System', '-'
            role_label = {
                'admin': 'Admin',
                'subadmin': 'Partner',
                'employee': 'Employee',
                'agent': 'Channel Partner',
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
        channel_partner_loans_counter = defaultdict(int)
        for loan in loans_qs[:250]:
            serialized = _serialize_subadmin_loan_details(loan) or {}
            owner_role, owner_name = get_owner_display(loan)
            source = 'Submitted' if loan.created_by_id == user.id else 'Assigned'
            assigned_to = '-'
            if loan.assigned_employee:
                assigned_to = f"Employee - {loan.assigned_employee.get_full_name() or loan.assigned_employee.username}"
            elif loan.assigned_agent:
                assigned_to = f"Channel Partner - {loan.assigned_agent.name}"
            if loan.assigned_agent_id:
                channel_partner_loans_counter[loan.assigned_agent_id] += 1

            customers.append({
                'loan_id': loan.id,
                'loan_uid': loan.user_id or 'Pending Manual ID',
                'customer_name': loan.full_name or '-',
                'mobile': loan.mobile_number or '-',
                'email': loan.email or '-',
                'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else (loan.loan_type or '-'),
                'loan_amount': float(loan.loan_amount or 0),
                'status': loan.status,
                'status_display': serialized.get('status_display') or status_map.get(loan.status, loan.status),
                'source': source,
                'assigned_to': assigned_to,
                'under_whom': f"{owner_role} - {owner_name}",
                'owner_role': owner_role,
                'owner_name': owner_name,
                'assigned_by': serialized.get('assigned_by') or '-',
                'bank_remark': serialized.get('bank_remark') or latest_bank_remark(loan),
                'created_at': serialized.get('created_at') or (loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else ''),
                'updated_at': serialized.get('updated_at') or (loan.updated_at.strftime('%Y-%m-%d %H:%M') if loan.updated_at else ''),
                'assigned_at': loan.assigned_at.strftime('%Y-%m-%d %H:%M') if loan.assigned_at else '-',
                'action_taken_at': loan.action_taken_at.strftime('%Y-%m-%d %H:%M') if loan.action_taken_at else '-',
                'follow_up_triggered_at': loan.follow_up_triggered_at.strftime('%Y-%m-%d %H:%M') if loan.follow_up_triggered_at else '-',
                'remarks': serialized.get('remarks') or (loan.remarks or '-'),
                'remarks_lines': serialized.get('remarks_lines') or [],
                'documents': serialized.get('documents') or [],
                'status_timeline': serialized.get('status_timeline') or [],
                'full_application_details': serialized.get('full_application_details') or [],
                'loan_purpose': serialized.get('loan_purpose') or (loan.loan_purpose or '-'),
                'tenure_months': serialized.get('tenure_months') or (loan.tenure_months or '-'),
                'interest_rate': serialized.get('interest_rate') if serialized.get('interest_rate') is not None else (float(loan.interest_rate) if loan.interest_rate is not None else '-'),
                'emi': serialized.get('emi') if serialized.get('emi') is not None else (float(loan.emi) if loan.emi is not None else '-'),
                'bank_name': serialized.get('bank_name') or (loan.bank_name or '-'),
                'bank_account_number': serialized.get('bank_account_number') or (loan.bank_account_number or '-'),
                'bank_ifsc_code': serialized.get('bank_ifsc_code') or (loan.bank_ifsc_code or '-'),
                'bank_type': serialized.get('bank_type') or (loan.bank_type or '-'),
                'sm_name': serialized.get('sm_name') or (loan.sm_name or '-'),
                'sm_phone_number': serialized.get('sm_phone_number') or (loan.sm_phone_number or '-'),
                'sm_email': serialized.get('sm_email') or (loan.sm_email or '-'),
                'assigned_employee_id': loan.assigned_employee_id,
                'assigned_agent_id': loan.assigned_agent_id,
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
        if hasattr(user, 'onboarding_profile') and user.onboarding_profile:
            onboarding = user.onboarding_profile.data or {}
        documents = collect_user_document_payload(user)
        creator_info = _resolve_creator_info(user, onboarding, profile)
        assigned_subadmin_id = _extract_subadmin_id(getattr(profile, 'notes', '')) if profile else None
        city, pin_code, district = _extract_location(onboarding, user)
        section1 = onboarding.get('section1') if isinstance(onboarding, dict) else {}
        perm = (section1 or {}).get('permanent_address') or {}
        section6 = onboarding.get('section6') if isinstance(onboarding, dict) else {}
        assigned_partner_links = list(
            AgentAssignment.objects.filter(employee=user)
            .select_related('agent')
            .order_by('-assigned_at')
        )
        assigned_channel_partners = []
        seen_channel_partner_ids = set()
        for link in assigned_partner_links:
            if not link.agent_id or link.agent_id in seen_channel_partner_ids:
                continue
            seen_channel_partner_ids.add(link.agent_id)
            agent = link.agent
            assigned_channel_partners.append({
                'id': link.agent_id,
                'name': (agent.name if agent else '-') or '-',
                'email': (agent.email if agent else '') or 'N/A',
                'phone': (agent.phone if agent else '') or 'N/A',
                'photo_url': agent.profile_photo.url if agent and agent.profile_photo else (
                    agent.user.profile_photo.url if agent and agent.user and agent.user.profile_photo else ''
                ),
                'status': str((agent.status if agent else 'active') or 'active').title(),
                'application_count': channel_partner_loans_counter.get(link.agent_id, 0),
            })
        assigned_channel_partner_ids = [item['id'] for item in assigned_channel_partners]
        summary['channel_partner_count'] = len(assigned_channel_partners)

        return JsonResponse({
            'success': True,
            'employee': {
                'id': user.id,
                'employee_id': user.employee_id or f'EDC-EMP-{user.id:04d}',
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'phone': user.phone or '',
                'address': user.address or '',
                'photo_url': user.profile_photo.url if user.profile_photo else '',
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
                'state': str(perm.get('state') or '').strip() or '-',
                'aadhar_number': str((section6 or {}).get('aadhar_number') or '').strip() or '-',
                'created_under': creator_info['display'],
                'created_by_role': creator_info['role'],
                'created_by_name': creator_info['name'],
                'assigned_subadmin_id': assigned_subadmin_id or '',
                'assigned_channel_partners': assigned_channel_partners,
                'assigned_channel_partner_ids': assigned_channel_partner_ids,
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
