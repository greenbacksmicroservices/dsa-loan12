from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncMonth, TruncDay
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import datetime, timedelta
import logging
import re
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import User, Agent, Loan, Complaint, ComplaintComment, ActivityLog, LoanDocument, Applicant, LoanApplication, ApplicantDocument, SubAdminEntry, EmployeeProfile, LoanStatusHistory, LoanAssignment
from .serializers import (
    UserSerializer, AgentSerializer, LoanSerializer,
    ComplaintSerializer, ComplaintCommentSerializer,
    ActivityLogSerializer, DashboardStatsSerializer, LoanDocumentSerializer,
    ApplicantDocumentSerializer, ApplicantSerializer, LoanApplicationSerializer
)
from .decorators import admin_required, employee_required
from .forms import (
    ApplicantStep1Form,
    ApplicantStep2Form,
    DocumentUploadForm,
    EmployeeRegistrationStep1Form,
    EmployeeResumeUploadForm,
)
from .permissions import IsAdminUser, IsEmployeeUser, IsAgentUser, IsLoanOwnerOrAdmin
from .loan_sync import (
    extract_assignment_context,
    find_related_loan,
    find_related_loan_application,
    sync_loan_to_application,
)
from .followup_utils import auto_move_overdue_to_follow_up

logger = logging.getLogger(__name__)


# Authentication Views
def login_view(request):
    if request.user.is_authenticated:
        # Redirect based on role
        if request.user.role == 'admin':
            return redirect('admin_dashboard')
        elif request.user.role == 'subadmin':
            return redirect('/subadmin/dashboard/')
        elif request.user.role == 'agent':
            return redirect('agent_dashboard')
        else:
            return redirect('dashboard')
    
    if request.method == 'POST':
        email_input = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        
        from django.contrib.auth import authenticate
        
        # Try to authenticate with email first (preferred)
        user = None
        error_message = 'Invalid email or password. Please check your credentials.'
        
        if email_input and '@' in email_input:
            # Try email-based login
            try:
                user_obj = User.objects.get(email=email_input)
                user = authenticate(request, username=user_obj.username, password=password)
            except User.DoesNotExist:
                # Email doesn't exist
                error_message = 'Email not found. Please check your credentials.'
        elif email_input:
            # Try username as fallback
            user = authenticate(request, username=email_input, password=password)

            # If not found, try agent_id mapping
            if user is None:
                try:
                    agent = Agent.objects.get(agent_id=email_input)
                    if agent.user:
                        user = authenticate(request, username=agent.user.username, password=password)
                except Agent.DoesNotExist:
                    pass
        
        if user is not None and user.is_active:
            login(request, user)
            # Redirect based on role
            if user.role == 'admin':
                return redirect('admin_dashboard')
            elif user.role == 'subadmin':
                return redirect('/subadmin/dashboard/')
            elif user.role == 'agent':
                return redirect('agent_dashboard')
            else:
                return redirect('dashboard')
        else:
            messages.error(request, error_message)
    
    return render(request, 'core/login.html', {'messages': messages.get_messages(request)})


def admin_login_view(request):
    """
    Custom Admin/SubAdmin Login View
    Allows both ADMIN and SUBADMIN role users to login
    """
    if request.user.is_authenticated:
        if request.user.role == 'admin':
            return redirect('admin_dashboard')
        elif request.user.role == 'subadmin':
            return redirect('subadmin_dashboard')
    
    if request.method == 'POST':
        username_or_email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        remember_me = request.POST.get('remember_me', False)
        
        if not username_or_email or not password:
            messages.error(request, 'Please enter username/email and password')
            return redirect('admin_login')
        
        # Try to authenticate with username or email
        user = None
        if '@' in username_or_email:
            # Try email
            try:
                user_obj = User.objects.get(email=username_or_email)
                user = authenticate(request, username=user_obj.username, password=password)
            except User.DoesNotExist:
                pass
        else:
            # Try username
            user = authenticate(request, username=username_or_email, password=password)
        
        if user is not None and user.is_active:
            # Check if user is ADMIN or SUBADMIN
            if user.role in ['admin', 'subadmin']:
                login(request, user)
                
                # Set session expiry based on remember me
                if remember_me:
                    request.session.set_expiry(1209600)  # 2 weeks
                else:
                    request.session.set_expiry(0)  # Browser session
                
                # Log activity
                ActivityLog.objects.create(
                    action='loan_added',  # Using existing action type
                    description=f"{user.role.capitalize()} '{user.username}' logged in",
                    user=user
                )
                
                messages.success(request, f'Welcome, {user.username}!')
                
                # Redirect based on role
                if user.role == 'admin':
                    return redirect('admin_dashboard')
                else:
                    return redirect('subadmin_dashboard')
            else:
                messages.error(request, 'Unauthorized access. Admin/Partner privileges required.')
        else:
            messages.error(request, 'Invalid email/username or password.')
    
    return render(request, 'core/admin_login.html')


@login_required
def admin_logout_view(request):
    """Admin Logout View"""
    logout(request)
    messages.info(request, 'You have been logged out successfully.')
    return redirect('admin_login')


@login_required
def logout_view(request):
    logout(request)
    return redirect('login')


# Admin Subadmin Management
@login_required
def admin_subadmin_management(request):
    """SubAdmin Management - View and manage all subadmins"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    from django.db.models import Count, Prefetch
    
    # Fetch all subadmins
    subadmins = User.objects.filter(role='subadmin', is_active=True)
    
    # Count data for each subadmin
    subadmin_employees_count = {}
    subadmin_agents_count = {}
    subadmin_entries_count = {}
    subadmin_employees = {}
    subadmin_agents = {}
    subadmin_entries = {}
    
    for subadmin in subadmins:
        # Count and fetch employees - get unique employees from SubAdminEntry records
        # Since there's no direct created_by relationship, we show all employees
        employees_list = User.objects.filter(role='employee').all()
        subadmin_employees_count[subadmin.id] = employees_list.count()
        subadmin_employees[subadmin.id] = list(employees_list[:10])  # Limit to 10
        
        # Count and fetch agents created by subadmin
        agents_list = Agent.objects.filter(created_by=subadmin)
        subadmin_agents_count[subadmin.id] = agents_list.count()
        subadmin_agents[subadmin.id] = list(agents_list[:10])  # Limit to 10
        
        # Count and fetch SubAdminEntry entries
        entries_list = SubAdminEntry.objects.filter(subadmin=subadmin)
        subadmin_entries_count[subadmin.id] = entries_list.count()
        subadmin_entries[subadmin.id] = list(entries_list[:10])  # Limit to 10
    
    context = {
        'subadmins': subadmins,
        'subadmin_employees_count': subadmin_employees_count,
        'subadmin_agents_count': subadmin_agents_count,
        'subadmin_entries_count': subadmin_entries_count,
        'subadmin_employees': subadmin_employees,
        'subadmin_agents': subadmin_agents,
        'subadmin_entries': subadmin_entries,
    }
    
    return render(request, 'core/admin/subadmin_management.html', context)


@login_required
def admin_all_employees(request):
    """View all employees"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    employees = User.objects.filter(role='employee', is_active=True).select_related(
        'employee_profile',
        'onboarding_profile',
    ).order_by('-date_joined')
    
    # Count data for each employee
    employee_loans_count = {}
    employee_approved_count = {}
    employee_creator_display = {}
    employee_location_display = {}
    pending_subadmin_lookup = {}
    subadmin_ids = set()
    
    for employee in employees:
        employee_loans_count[employee.id] = Loan.objects.filter(assigned_employee=employee).count()
        employee_approved_count[employee.id] = Loan.objects.filter(
            assigned_employee=employee,
            status='approved'
        ).count()

        onboarding = {}
        if hasattr(employee, 'onboarding_profile') and employee.onboarding_profile:
            onboarding = employee.onboarding_profile.data or {}

        section1 = onboarding.get('section1') if isinstance(onboarding, dict) else {}
        perm = (section1 or {}).get('permanent_address') or {}
        city = (perm.get('city') or '').strip()
        pin = (perm.get('pin_code') or '').strip()
        district = (perm.get('district') or '').strip()

        if not city and isinstance(onboarding, dict):
            city = str(onboarding.get('city') or '').strip()
        if not pin and isinstance(onboarding, dict):
            pin = str(onboarding.get('pin_code') or onboarding.get('pin') or '').strip()
        if not district and isinstance(onboarding, dict):
            district = str(onboarding.get('district') or '').strip()

        if not city or not pin or not district:
            address_text = str(getattr(employee, 'address', '') or '')
            if address_text:
                if not city:
                    match_city = re.search(r'City:\s*([^|,\n]+)', address_text, flags=re.IGNORECASE)
                    if match_city:
                        city = match_city.group(1).strip()
                if not pin:
                    match_pin = re.search(r'PIN:\s*([A-Za-z0-9-]+)', address_text, flags=re.IGNORECASE)
                    if match_pin:
                        pin = match_pin.group(1).strip()
                if not district:
                    match_district = re.search(r'District:\s*([^|,\n]+)', address_text, flags=re.IGNORECASE)
                    if match_district:
                        district = match_district.group(1).strip()

        location_parts = []
        if city:
            location_parts.append(city)
        if district:
            location_parts.append(f"District {district}")
        if pin:
            location_parts.append(f"PIN {pin}")
        employee_location_display[employee.id] = " | ".join(location_parts) if location_parts else '-'

        creator_role = ''
        creator_name = ''
        meta = onboarding.get('_meta') if isinstance(onboarding, dict) else None
        if isinstance(meta, dict):
            creator_role = str(meta.get('created_by_role') or '').strip()
            creator_name = str(meta.get('created_by_name') or '').strip()

        if not creator_role or not creator_name:
            notes = ''
            profile = getattr(employee, 'employee_profile', None)
            if profile and getattr(profile, 'notes', None):
                notes = profile.notes
            match = re.search(r'\[subadmin:(\d+)\]', str(notes or ''), flags=re.IGNORECASE)
            if match:
                subadmin_id = int(match.group(1))
                pending_subadmin_lookup[employee.id] = subadmin_id
                subadmin_ids.add(subadmin_id)
            else:
                employee_creator_display[employee.id] = 'Admin - System'
                continue

        if creator_role and creator_name:
            employee_creator_display[employee.id] = f"{creator_role} - {creator_name}"

    subadmin_map = {
        user.id: user for user in User.objects.filter(id__in=list(subadmin_ids), role='subadmin').only('id', 'first_name', 'last_name', 'username')
    }
    for employee_id, subadmin_id in pending_subadmin_lookup.items():
        subadmin = subadmin_map.get(subadmin_id)
        if subadmin:
            name = subadmin.get_full_name() or subadmin.username or 'Partner'
            employee_creator_display[employee_id] = f"Partner - {name}"
        else:
            employee_creator_display[employee_id] = 'Admin - System'
    
    context = {
        'employees': employees,
        'employee_loans_count': employee_loans_count,
        'employee_approved_count': employee_approved_count,
        'employee_creator_display': employee_creator_display,
        'employee_location_display': employee_location_display,
    }
    
    return render(request, 'core/admin/employees_list.html', context)


@login_required
def admin_all_agents(request):
    """View all agents"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    agents = Agent.objects.filter(status='active').select_related(
        'created_by',
        'user',
        'user__onboarding_profile',
    ).order_by('-created_at')

    agent_location_display = {}
    for agent in agents:
        city = str(getattr(agent, 'city', '') or '').strip()
        pin = str(getattr(agent, 'pin_code', '') or '').strip()
        district = ''

        onboarding = {}
        agent_user = getattr(agent, 'user', None)
        if agent_user and hasattr(agent_user, 'onboarding_profile') and agent_user.onboarding_profile:
            onboarding = agent_user.onboarding_profile.data or {}

        section1 = onboarding.get('section1') if isinstance(onboarding, dict) else {}
        perm = (section1 or {}).get('permanent_address') or {}
        if not city:
            city = str(perm.get('city') or '').strip()
        if not pin:
            pin = str(perm.get('pin_code') or '').strip()
        district = str(perm.get('district') or '').strip()
        if not district and isinstance(onboarding, dict):
            district = str(onboarding.get('district') or '').strip()

        if not city or not pin or not district:
            address_text = str(
                getattr(agent, 'address', '') or getattr(agent_user, 'address', '') or ''
            )
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

        location_parts = []
        if city:
            location_parts.append(city)
        if district:
            location_parts.append(f"District {district}")
        if pin:
            location_parts.append(f"PIN {pin}")
        agent_location_display[agent.id] = " | ".join(location_parts) if location_parts else '-'
    
    context = {
        'agents': agents,
        'agent_location_display': agent_location_display,
    }
    
    return render(request, 'core/admin/agents_list.html', context)


@login_required
def admin_new_entries(request):
    """View New Entry applications"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    applications = LoanApplication.objects.filter(status='New Entry').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'New Applications',
        'applications': applications,
        'status_name': 'New Entry',
        'status_icon': 'fa-file-alt',
        'status_color': '#667eea',
    }
    
    return render(request, 'core/admin/applications_list.html', context)


@login_required
def admin_in_processing(request):
    """View In Processing applications"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    applications = LoanApplication.objects.filter(status='Waiting for Processing').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'Document Pending Applications',
        'applications': applications,
        'status_name': 'In Processing',
        'status_icon': 'fa-hourglass-half',
        'status_color': '#f5576c',
    }
    
    return render(request, 'core/admin/applications_list.html', context)


@login_required
def admin_follow_ups(request):
    """View Banking Processing applications"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    applications = LoanApplication.objects.filter(status='Required Follow-up').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'Banking Processing Applications',
        'applications': applications,
        'status_name': 'Banking Processing',
        'status_icon': 'fa-phone',
        'status_color': '#fa709a',
    }
    
    return render(request, 'core/admin/admin_loan_status_list.html', context)


@login_required
def admin_approved(request):
    """View Approved applications"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    applications = LoanApplication.objects.filter(status='Approved').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'Approved Applications',
        'applications': applications,
        'status_name': 'Approved',
        'status_icon': 'fa-check-circle',
        'status_color': '#30cfd0',
    }
    
    return render(request, 'core/admin/applications_list.html', context)


@login_required
def admin_rejected(request):
    """View Rejected applications"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    applications = LoanApplication.objects.filter(status='Rejected').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'Rejected Applications',
        'applications': applications,
        'status_name': 'Rejected',
        'status_icon': 'fa-times-circle',
        'status_color': '#ff6b6b',
    }
    
    return render(request, 'core/admin/applications_list.html', context)


@login_required
def admin_disbursed(request):
    """View Disbursed applications"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    applications = LoanApplication.objects.filter(status='Disbursed').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'Disbursed Applications',
        'applications': applications,
        'status_name': 'Disbursed',
        'status_icon': 'fa-money-bill-wave',
        'status_color': '#11998e',
    }
    
    return render(request, 'core/admin/applications_list.html', context)


@login_required
def admin_loan_detail(request, loan_id):
    """View loan details with documents and assignment option"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    try:
        loan = Loan.objects.select_related('assigned_employee').get(id=loan_id)
    except Loan.DoesNotExist:
        messages.error(request, 'Loan not found')
        return redirect('admin_dashboard')
    
    documents = LoanDocument.objects.filter(loan=loan)
    employees = User.objects.filter(role='employee', is_active=True)
    
    context = {
        'loan': loan,
        'documents': documents,
        'employees': employees,
    }
    
    return render(request, 'core/admin/admin_loan_detail.html', context)


@login_required
def admin_assign_employee(request, loan_id):
    """Assign employee to loan and update status"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    if request.method == 'POST':
        try:
            loan = Loan.objects.get(id=loan_id)
            employee_id = request.POST.get('employee_id')
            
            if employee_id:
                employee = User.objects.get(id=employee_id, role='employee')
                loan.assigned_employee = employee
                loan.status = 'in_processing'
                loan.assigned_at = timezone.now()
                loan.save()
                
                messages.success(request, f'Loan assigned to {employee.get_full_name()}')
            else:
                messages.error(request, 'Please select an employee')
        except (Loan.DoesNotExist, User.DoesNotExist):
            messages.error(request, 'Loan or Employee not found')
    
    return redirect('admin_loan_detail', loan_id=loan_id)


@login_required
@login_required
def admin_reports(request):
    """Admin Reports page with real data"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    try:
        # Get all applications
        all_apps = LoanApplication.objects.all()
        total_applications = all_apps.count()
        
        # Count by status
        new_count = all_apps.filter(status='New Entry').count()
        processing_count = all_apps.filter(status='Waiting for Processing').count()
        followup_count = all_apps.filter(status='Required Follow-up').count()
        approved_count = all_apps.filter(status='Approved').count()
        rejected_count = all_apps.filter(status='Rejected').count()
        disbursed_count = all_apps.filter(status='Disbursed').count()
        
        # Calculate percentages
        new_percent = int((new_count / total_applications * 100)) if total_applications > 0 else 0
        processing_percent = int((processing_count / total_applications * 100)) if total_applications > 0 else 0
        followup_percent = int((followup_count / total_applications * 100)) if total_applications > 0 else 0
        approved_percent = int((approved_count / total_applications * 100)) if total_applications > 0 else 0
        rejected_percent = int((rejected_count / total_applications * 100)) if total_applications > 0 else 0
        disbursed_percent = int((disbursed_count / total_applications * 100)) if total_applications > 0 else 0
        
        # Financial data
        total_amount = all_apps.aggregate(Sum('applicant__loan_amount'))['applicant__loan_amount__sum'] or 0
        approved_amount = all_apps.filter(status='Approved').aggregate(Sum('applicant__loan_amount'))['applicant__loan_amount__sum'] or 0
        disbursed_amount = all_apps.filter(status='Disbursed').aggregate(Sum('applicant__loan_amount'))['applicant__loan_amount__sum'] or 0
        pending_amount = (total_amount - disbursed_amount)
        avg_loan_value = (total_amount / total_applications) if total_applications > 0 else 0
        
        # Team data
        employees = User.objects.filter(role='employee')
        total_employees = employees.count()
        active_employees = employees.filter(is_active=True).count()
        
        agents = Agent.objects.all()
        total_agents = agents.count()
        active_agents = agents.filter(status='active').count()
        
        subadmins = User.objects.filter(role='subadmin')
        total_subadmins = subadmins.count()

        # Download selector list: employees + agents + subadmins (deduplicated by name)
        download_people = []
        seen_names = set()

        def append_download_person(raw_name, role_label):
            raw_name = (raw_name or '').strip()
            if not raw_name:
                return
            key = raw_name.lower()
            if key in seen_names:
                return
            seen_names.add(key)
            download_people.append({
                'name': raw_name,
                'role': role_label,
            })

        for emp in employees.order_by('first_name', 'last_name', 'username'):
            append_download_person(emp.get_full_name() or emp.username, 'Employee')

        for ag in agents.order_by('name', 'id'):
            append_download_person(ag.name or (ag.user.get_full_name() if ag.user else ''), 'Channel Partner')

        for subadmin in subadmins.order_by('first_name', 'last_name', 'username'):
            append_download_person(subadmin.get_full_name() or subadmin.username, 'Partner')

        download_people.sort(key=lambda person: (person['name'].lower(), person['role']))

        context = {
            'page_title': 'Reports & Analytics',
            'total_applications': total_applications,
            'new_count': new_count,
            'processing_count': processing_count,
            'followup_count': followup_count,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'disbursed_count': disbursed_count,
            'new_percent': new_percent,
            'processing_percent': processing_percent,
            'followup_percent': followup_percent,
            'approved_percent': approved_percent,
            'rejected_percent': rejected_percent,
            'disbursed_percent': disbursed_percent,
            'total_amount': total_amount,
            'approved_amount': approved_amount,
            'disbursed_amount': disbursed_amount,
            'pending_amount': pending_amount,
            'avg_loan_value': avg_loan_value,
            'total_employees': total_employees,
            'active_employees': active_employees,
            'total_agents': total_agents,
            'active_agents': active_agents,
            'total_subadmins': total_subadmins,
            'download_people': download_people,
        }
        
        return render(request, 'core/admin/admin_reports_enhanced.html', context)
    except Exception as e:
        logger.error(f"Error loading reports: {str(e)}")
        context = {
            'page_title': 'Reports & Analytics',
            'error': str(e)
        }
        return render(request, 'core/admin/admin_reports.html', context)


@login_required
def admin_complaints(request):
    """Admin Complaints page"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    complaints = Complaint.objects.select_related('loan', 'filed_by_employee', 'filed_by_agent', 'assigned_admin', 'created_by').order_by('-created_at')
    
    context = {
        'complaints': complaints,
    }
    
    return render(request, 'core/admin/admin_complaints.html', context)


@login_required
def admin_settings(request):
    """Admin Settings page"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    context = {}
    
    return render(request, 'core/admin/admin_settings.html', context)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_create_subadmin(request):
    """API endpoint to create a new SubAdmin"""
    if request.user.role != 'admin':
        return Response(
            {'success': False, 'message': 'Only admins can create subadmins'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        data = request.data
        
        # Check if username already exists
        if User.objects.filter(username=data.get('username')).exists():
            return Response(
                {'success': False, 'message': 'Username already exists'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if email already exists
        if User.objects.filter(email=data.get('email')).exists():
            return Response(
                {'success': False, 'message': 'Email already exists'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create new SubAdmin user
        user = User.objects.create_user(
            username=data.get('username'),
            email=data.get('email'),
            password=data.get('password'),
            first_name=data.get('full_name', '').split()[0] if data.get('full_name') else '',
            last_name=' '.join(data.get('full_name', '').split()[1:]) if data.get('full_name') else '',
            phone=data.get('phone'),
            role='subadmin',
            is_active=True
        )
        
        return Response(
            {'success': True, 'message': 'Partner created successfully', 'id': user.id},
            status=status.HTTP_201_CREATED
        )
    
    except Exception as e:
        return Response(
            {'success': False, 'message': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['POST'])
@login_required
def api_toggle_subadmin_status(request, subadmin_id):
    """API endpoint to toggle SubAdmin active/inactive status"""
    # Check if user is admin
    if request.user.role != 'admin':
        return Response(
            {'success': False, 'message': 'Only admins can toggle subadmin status'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        # Get the subadmin user
        subadmin = User.objects.get(id=subadmin_id, role='subadmin')
        
        # Toggle the is_active status
        old_status = subadmin.is_active
        subadmin.is_active = not subadmin.is_active
        subadmin.save()
        
        # Log the activity
        status_text = 'activated' if subadmin.is_active else 'deactivated'
        
        return Response(
            {
                'success': True,
                'message': f'Partner {subadmin.get_full_name()} has been {status_text}',
                'subadmin_id': subadmin_id,
                'new_status': subadmin.is_active,
                'old_status': old_status
            },
            status=status.HTTP_200_OK
        )
    
    except User.DoesNotExist:
        return Response(
            {'success': False, 'message': 'Partner not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'success': False, 'message': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )


@login_required
def admin_new_entry_assign(request):
    """Admin New Entry Assign - Assign new loan applications to employees"""
    if request.user.role != 'admin':
        return redirect('admin_dashboard')
    return render(request, 'core/admin/new_entry_assign.html')


@login_required
def employee_assigned_loans(request):
    """Employee view assigned loans and take actions"""
    if request.user.role != 'employee':
        return redirect('dashboard')
    return render(request, 'core/employee/assigned_loans.html')


@login_required
def agent_dashboard(request):
    """Agent Dashboard - Only accessible by AGENT role"""
    if request.user.role != 'agent':
        return redirect('dashboard')
    return render(request, 'core/agent_dashboard.html')


@login_required
def loan_application_form(request):
    """Display loan application form for creating new entries"""
    context = {
        'page_title': 'New Loan Application Entry',
    }
    return render(request, 'core/loan_application_form.html', context)


# Dashboard View (General)
@login_required
def dashboard(request):
    # Redirect admin users to admin dashboard
    if request.user.role == 'admin':
        return redirect('admin_dashboard')
    # Redirect agents to agent dashboard
    elif request.user.role == 'agent':
        return redirect('agent_dashboard')
    # Redirect employees to employee dashboard
    elif request.user.role == 'employee':
        return redirect('employee_dashboard')
    # Redirect to default dashboard
    return render(request, 'core/dashboard.html')


# Loan Entry View - Redirect to Loan Entry Form
@admin_required
def loan_entry(request):
    agents = Agent.objects.filter(status='active')
    return render(request, 'core/loan_entry.html', {'agents': agents})


# Document Upload View
@admin_required
def document_upload(request, loan_id):
    """Document upload page for a specific loan"""
    try:
        loan = Loan.objects.get(id=loan_id)
    except Loan.DoesNotExist:
        return redirect('admin_dashboard')
    
    if request.method == 'POST':
        # Handle document uploads
        for field_name in request.FILES:
            file = request.FILES[field_name]
            # Create or update LoanDocument
            LoanDocument.objects.update_or_create(
                loan=loan,
                document_type=field_name,
                defaults={'file': file}
            )
        messages.success(request, 'Documents uploaded successfully!')
        return redirect('admin_dashboard')
    
    return render(request, 'core/document_upload.html', {'loan': loan})


# Employee List View
@admin_required
def employee_list(request):
    employees = User.objects.filter(role='employee')
    return render(request, 'core/employee_list.html', {'employees': employees})


# Agent List View
@admin_required
def agent_list(request):
    agents = Agent.objects.all()
    return render(request, 'core/agent_list.html', {'agents': agents})


# New Admin Views for Employee, Agent, and Complaints Lists
@admin_required
def admin_employee_list(request):
    """Admin view for employee list with full details"""
    employees = User.objects.filter(role='employee').order_by('-created_at')
    context = {
        'employees': employees,
        'page_title': 'Employee List'
    }
    return render(request, 'admin/employee_list.html', context)


@admin_required
def admin_agent_list(request):
    """Admin view for agent/CP list with full details"""
    agents = Agent.objects.all().order_by('-created_at')
    context = {
        'agents': agents,
        'page_title': 'Agent/CP List'
    }
    return render(request, 'admin/agent_list.html', context)


@admin_required
def admin_complaints_list(request):
    """Admin view for complaints list with employee/agent information"""
    complaints = Complaint.objects.all().order_by('-created_at')
    
    # Apply filters
    status_filter = request.GET.get('status')
    priority_filter = request.GET.get('priority')
    
    if status_filter:
        complaints = complaints.filter(status=status_filter)
    if priority_filter:
        complaints = complaints.filter(priority=priority_filter)
    
    context = {
        'complaints': complaints,
        'page_title': 'Complaints List'
    }
    return render(request, 'admin/complaints_list.html', context)


# Reports View
@admin_required
def reports(request):
    return render(request, 'core/reports.html')


# Complaints View
@admin_required
def complaints(request):
    complaints_list = Complaint.objects.all()
    return render(request, 'core/complaints.html', {'complaints': complaints_list})


# REST API Viewsets
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['role', 'is_active']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    ordering_fields = ['created_at', 'username']
    
    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return User.objects.all()
        elif user.role == 'dsa':
            return User.objects.filter(role__in=['employee', 'dsa'])
        return User.objects.filter(id=user.id)
    
    def perform_create(self, serializer):
        password = self.request.data.get('password')
        user = serializer.save()
        if password:
            user.set_password(password)
            user.save()


class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.all()
    serializer_class = AgentSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status']
    search_fields = ['name', 'phone', 'email']
    ordering_fields = ['created_at', 'name']
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        ActivityLog.objects.create(
            action='agent_registered',
            description=f"New agent '{serializer.instance.name}' registered",
            user=self.request.user,
            related_agent=serializer.instance
        )


class LoanViewSet(viewsets.ModelViewSet):
    queryset = Loan.objects.all()
    serializer_class = LoanSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'loan_type', 'assigned_agent']
    search_fields = ['customer_name', 'mobile_number', 'bank_name', 'full_name']
    ordering_fields = ['created_at', 'loan_amount']
    
    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return Loan.objects.all()
        elif user.role == 'dsa':
            return Loan.objects.filter(assigned_agent__created_by=user)
        return Loan.objects.filter(created_by=user)
    
    def perform_create(self, serializer):
        loan = serializer.save(created_by=self.request.user)
        
        # Handle applicant type - Create user and link to Employee/Agent
        applicant_type = self.request.data.get('applicant_type', 'employee')
        username = self.request.data.get('username')
        password = self.request.data.get('password')

        # Employee-submitted applications should directly enter employee workflow.
        if self.request.user.role == 'employee':
            update_fields = []
            if loan.assigned_employee_id != self.request.user.id:
                loan.assigned_employee = self.request.user
                update_fields.append('assigned_employee')
            if loan.status in ['new_entry', 'draft']:
                loan.status = 'waiting'
                update_fields.append('status')
            if not loan.assigned_at:
                loan.assigned_at = timezone.now()
                update_fields.append('assigned_at')
            if loan.applicant_type != 'employee':
                loan.applicant_type = 'employee'
                update_fields.append('applicant_type')
            if update_fields:
                loan.save(update_fields=update_fields + ['updated_at'])
        
        if username and password and self.request.user.role != 'employee':
            # Create or get user
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': loan.full_name.split()[0] if loan.full_name else '',
                    'last_name': loan.full_name.split()[-1] if loan.full_name else '',
                    'email': self.request.data.get('email', ''),
                    'role': applicant_type,
                }
            )
            if created:
                user.set_password(password)
                user.save()
            
            # Link based on applicant type
            if applicant_type == 'employee':
                loan.assigned_employee = user
                loan.applicant_type = 'employee'
            elif applicant_type == 'agent':
                # Create or link to Agent
                agent, _ = Agent.objects.get_or_create(
                    user=user,
                    defaults={
                        'name': loan.full_name,
                        'phone': loan.mobile_number,
                        'email': loan.email,
                        'created_by': self.request.user,
                    }
                )
                loan.assigned_agent = agent
                loan.applicant_type = 'agent'
            
            loan.save()
        
        ActivityLog.objects.create(
            action='loan_added',
            description=f"New loan added for '{loan.full_name}' ({applicant_type})",
            user=self.request.user,
            related_loan=loan
        )
    
    def perform_update(self, serializer):
        old_status = serializer.instance.status
        serializer.save()
        new_status = serializer.instance.status
        
        if old_status != new_status:
            ActivityLog.objects.create(
                action='status_updated',
                description=f"Loan status updated from '{old_status}' to '{new_status}'",
                user=self.request.user,
                related_loan=serializer.instance
            )
            
            if new_status == 'approved':
                ActivityLog.objects.create(
                    action='loan_approved',
                    description=f"Loan approved for '{serializer.instance.full_name}'",
                    user=self.request.user,
                    related_loan=serializer.instance
                )
            elif new_status == 'rejected':
                ActivityLog.objects.create(
                    action='loan_rejected',
                    description=f"Loan rejected for '{serializer.instance.full_name}'",
                    user=self.request.user,
                    related_loan=serializer.instance
                )
            elif new_status == 'disbursed':
                ActivityLog.objects.create(
                    action='loan_disbursed',
                    description=f"Loan disbursed for '{serializer.instance.full_name}'",
                    user=self.request.user,
                    related_loan=serializer.instance
                )


class LoanDocumentViewSet(viewsets.ModelViewSet):
    queryset = LoanDocument.objects.all()
    serializer_class = LoanDocumentSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['loan', 'document_type', 'is_required']
    ordering_fields = ['uploaded_at', 'document_type']
    
    def get_queryset(self):
        """
        Filter documents based on user role:
        - Admin: Can see all documents
        - Employee: Can only see documents for loans assigned to them
        - Agent: Can only see documents for loans assigned to their agent profile
        """
        user = self.request.user
        if user.role == 'admin':
            return LoanDocument.objects.all()
        elif user.role == 'employee':
            return LoanDocument.objects.filter(loan__assigned_employee=user)
        elif user.role == 'agent':
            try:
                from core.models import Agent
                agent = Agent.objects.get(user=user)
                return LoanDocument.objects.filter(loan__assigned_agent=agent)
            except Agent.DoesNotExist:
                return LoanDocument.objects.none()
        else:
            return LoanDocument.objects.none()
    
    def perform_create(self, serializer):
        serializer.save()
        ActivityLog.objects.create(
            action='loan_added',
            description=f"Document uploaded for loan",
            user=self.request.user,
            related_loan=serializer.instance.loan
        )
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Download a specific document file"""
        document = self.get_object()
        
        # Check permission
        if request.user.role == 'admin':
            pass  # Admin can download all
        elif request.user.role == 'employee':
            if document.loan.assigned_employee != request.user:
                return Response({'error': 'You do not have permission to download this document'}, 
                              status=status.HTTP_403_FORBIDDEN)
        elif request.user.role == 'agent':
            try:
                from core.models import Agent
                agent = Agent.objects.get(user=request.user)
                if document.loan.assigned_agent != agent:
                    return Response({'error': 'You do not have permission to download this document'}, 
                                  status=status.HTTP_403_FORBIDDEN)
            except Agent.DoesNotExist:
                return Response({'error': 'Agent profile not found'}, status=status.HTTP_403_FORBIDDEN)
        else:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
        # Return file download response
        from django.http import FileResponse
        try:
            file_response = FileResponse(document.file.open('rb'))
            file_response['Content-Disposition'] = f'attachment; filename="{document.file.name}"'
            return file_response
        except FileNotFoundError:
            return Response({'error': 'File not found'}, status=status.HTTP_404_NOT_FOUND)


class LoanApplicationViewSet(viewsets.ModelViewSet):
    """ViewSet for Loan Applications with Employee/Agent Assignment"""
    queryset = LoanApplication.objects.all()
    serializer_class = LoanApplicationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'assigned_employee', 'assigned_agent']
    search_fields = ['applicant__full_name', 'applicant__email', 'applicant__mobile']
    ordering_fields = ['created_at', 'assigned_at']
    
    def get_queryset(self):
        """Filter based on user role"""
        user = self.request.user
        if user.role == 'admin':
            return LoanApplication.objects.all()
        elif user.role == 'employee':
            return LoanApplication.objects.filter(assigned_employee=user)
        elif user.role == 'agent':
            try:
                agent = Agent.objects.get(user=user)
                return LoanApplication.objects.filter(assigned_agent=agent)
            except Agent.DoesNotExist:
                return LoanApplication.objects.none()
        return LoanApplication.objects.none()
    
    def perform_create(self, serializer):
        """Create new loan application"""
        applicant_data = {
            'full_name': self.request.data.get('full_name'),
            'email': self.request.data.get('email'),
            'mobile': self.request.data.get('mobile'),
            'city': self.request.data.get('city'),
            'state': self.request.data.get('state'),
            'pin_code': self.request.data.get('pin_code'),
            'gender': self.request.data.get('gender'),
            'loan_type': self.request.data.get('loan_type'),
            'loan_amount': self.request.data.get('loan_amount'),
            'tenure_months': self.request.data.get('tenure_months'),
            'bank_name': self.request.data.get('bank_name'),
            'loan_purpose': self.request.data.get('loan_purpose'),
            'role': 'employee',  # Default role for loan applicants
            'username': self.request.data.get('email', '').split('@')[0],  # Generate username from email
        }
        
        # Create applicant
        applicant = Applicant.objects.create(**applicant_data)
        
        # Create loan application with assignment
        serializer.save(
            applicant=applicant,
            assigned_by=self.request.user
        )
        
        ActivityLog.objects.create(
            action='loan_application_created',
            description=f"New loan application created for '{applicant.full_name}'",
            user=self.request.user
        )


# New ViewSet for ApplicantDocuments with proper access control
class ApplicantDocumentViewSet(viewsets.ModelViewSet):
    queryset = ApplicantDocument.objects.all()
    serializer_class = ApplicantDocumentSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['loan_application', 'document_type']
    ordering_fields = ['uploaded_at', 'document_type']
    
    def get_queryset(self):
        """
        Filter documents based on user role:
        - Admin: Can see all applicant documents
        - Employee: Can only see documents for applications assigned to them
        - Agent: Can only see documents for applications assigned to their agent profile
        """
        user = self.request.user
        if user.role == 'admin':
            return ApplicantDocument.objects.all()
        elif user.role == 'employee':
            return ApplicantDocument.objects.filter(loan_application__assigned_employee=user)
        elif user.role == 'agent':
            try:
                agent = Agent.objects.get(user=user)
                return ApplicantDocument.objects.filter(loan_application__assigned_agent=agent)
            except Agent.DoesNotExist:
                return ApplicantDocument.objects.none()
        else:
            return ApplicantDocument.objects.none()
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Download a specific applicant document file"""
        document = self.get_object()
        
        # Check permission
        if request.user.role == 'admin':
            pass  # Admin can download all
        elif request.user.role == 'employee':
            if document.loan_application.assigned_employee != request.user:
                return Response({'error': 'You do not have permission to download this document'}, 
                              status=status.HTTP_403_FORBIDDEN)
        elif request.user.role == 'agent':
            try:
                agent = Agent.objects.get(user=request.user)
                if document.loan_application.assigned_agent != agent:
                    return Response({'error': 'You do not have permission to download this document'}, 
                                  status=status.HTTP_403_FORBIDDEN)
            except Agent.DoesNotExist:
                return Response({'error': 'Agent profile not found'}, status=status.HTTP_403_FORBIDDEN)
        else:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
        # Return file download response
        from django.http import FileResponse
        try:
            file_response = FileResponse(document.file.open('rb'))
            file_response['Content-Disposition'] = f'attachment; filename="{document.file.name}"'
            return file_response
        except FileNotFoundError:
            return Response({'error': 'File not found'}, status=status.HTTP_404_NOT_FOUND)


class ComplaintViewSet(viewsets.ModelViewSet):
    queryset = Complaint.objects.all()
    serializer_class = ComplaintSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'priority', 'complaint_type', 'assigned_admin']
    search_fields = ['complaint_id', 'customer_name']
    ordering_fields = ['created_at', 'priority']
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        ActivityLog.objects.create(
            action='complaint_raised',
            description=f"New complaint raised: {serializer.instance.complaint_id}",
            user=self.request.user,
            related_complaint=serializer.instance
        )
    
    @action(detail=True, methods=['post'])
    def add_comment(self, request, pk=None):
        complaint = self.get_object()
        comment = ComplaintComment.objects.create(
            complaint=complaint,
            comment=request.data.get('comment'),
            commented_by=request.user
        )
        serializer = ComplaintCommentSerializer(comment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ComplaintCommentViewSet(viewsets.ModelViewSet):
    queryset = ComplaintComment.objects.all()
    serializer_class = ComplaintCommentSerializer
    permission_classes = [IsAuthenticated]
    
    def perform_create(self, serializer):
        serializer.save(commented_by=self.request.user)


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ActivityLog.objects.all()
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['action']
    ordering_fields = ['created_at']


# API Endpoint for Complaints with Employee/Agent Information
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_complaints_with_filer(request):
    """Get complaints list with employee/agent who filed them"""
    if not request.user.is_authenticated or request.user.role != 'admin':
        return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)
    
    complaints = Complaint.objects.all().order_by('-created_at')
    
    # Apply filters
    status_filter = request.GET.get('status')
    priority_filter = request.GET.get('priority')
    complaint_type_filter = request.GET.get('complaint_type')
    
    if status_filter:
        complaints = complaints.filter(status=status_filter)
    if priority_filter:
        complaints = complaints.filter(priority=priority_filter)
    if complaint_type_filter:
        complaints = complaints.filter(complaint_type=complaint_type_filter)
    
    serializer = ComplaintSerializer(complaints, many=True, context={'request': request})
    return Response({
        'count': complaints.count(),
        'results': serializer.data
    })


# Admin Dashboard API Endpoint
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_dashboard_stats(request):
    """API endpoint for admin dashboard statistics - Admin only"""
    # Check if user is admin
    if not request.user.is_authenticated or request.user.role != 'admin':
        return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)
    
    # Query from LoanApplication model (correct source of truth)
    loan_app_queryset = LoanApplication.objects.all()
    complaint_queryset = Complaint.objects.all()
    
    # Stat cards data - Using LoanApplication statuses
    stats = {
        'total_new_entry': loan_app_queryset.filter(status='New Entry').count() or 0,
        'waiting_for_processing': loan_app_queryset.filter(status='Waiting for Processing').count() or 0,
        'required_follow_up': loan_app_queryset.filter(status='Required Follow-up').count() or 0,
        'approved': loan_app_queryset.filter(status='Approved').count() or 0,
        'rejected': loan_app_queryset.filter(status='Rejected').count() or 0,
        'disbursed': loan_app_queryset.filter(status='Disbursed').count() or 0,
    }
    
    # Loan Status Breakdown for Pie Chart
    loan_status_breakdown = {
        'Approved': loan_app_queryset.filter(status='Approved').count() or 0,
        'Waiting for Processing': loan_app_queryset.filter(status='Waiting for Processing').count() or 0,
        'Rejected': loan_app_queryset.filter(status='Rejected').count() or 0,
        'Disbursed': loan_app_queryset.filter(status='Disbursed').count() or 0,
        'New Entry': loan_app_queryset.filter(status='New Entry').count() or 0,
        'Required Follow-up': loan_app_queryset.filter(status='Required Follow-up').count() or 0,
    }
    
    # Daily Loan Trend for Line Chart (Last 30 days)
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)
    
    daily_trend = loan_app_queryset.filter(
        created_at__gte=start_date
    ).annotate(
        day=TruncDay('created_at')
    ).values('day').annotate(
        count=Count('id')
    ).order_by('day')
    
    daily_loan_trend = []
    for item in daily_trend:
        daily_loan_trend.append({
            'day': item['day'].strftime('%Y-%m-%d'),
            'date': item['day'].strftime('%b %d'),
            'count': item['count']
        })
    
    # Complaints Overview
    complaints_stats = {
        'total_complaints': complaint_queryset.count() or 0,
        'open_complaints': complaint_queryset.filter(status='open').count() or 0,
        'resolved_complaints': complaint_queryset.filter(status='resolved').count() or 0,
    }
    
    # Recent Activities
    recent_activities = ActivityLog.objects.all().order_by('-created_at')[:10]
    
    data = {
        **stats,
        'loan_status_breakdown': loan_status_breakdown,
        'daily_loan_trend': daily_loan_trend,
        **complaints_stats,
        'recent_activities': ActivityLogSerializer(recent_activities, many=True).data,
    }
    
    return Response(data)


# Dashboard API Endpoint
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    """API endpoint for dashboard statistics"""
    try:
        user = request.user
        
        # Base queryset based on user role - Use LoanApplication model
        if user.role == 'admin':
            loan_app_queryset = LoanApplication.objects.all()
            complaint_queryset = Complaint.objects.all()
        elif user.role == 'dsa':
            loan_app_queryset = LoanApplication.objects.filter(assigned_agent__created_by=user)
            complaint_queryset = Complaint.objects.filter(created_by=user)
        else:
            loan_app_queryset = LoanApplication.objects.filter(created_by=user)
            complaint_queryset = Complaint.objects.filter(created_by=user)
        
        # Stat cards data with default 0 values - Using LoanApplication statuses
        stats = {
            'total_new_entry': loan_app_queryset.filter(status='New Entry').count() or 0,
            'waiting_for_processing': loan_app_queryset.filter(status='Waiting for Processing').count() or 0,
            'required_follow_up': loan_app_queryset.filter(status='Required Follow-up').count() or 0,
            'approved': loan_app_queryset.filter(status='Approved').count() or 0,
            'rejected': loan_app_queryset.filter(status='Rejected').count() or 0,
            'disbursed': loan_app_queryset.filter(status='Disbursed').count() or 0,
        }
        
        # Loan Status Breakdown for Pie Chart
        loan_status_breakdown = {
            'Approved': loan_app_queryset.filter(status='Approved').count() or 0,
            'Waiting for Processing': loan_app_queryset.filter(status='Waiting for Processing').count() or 0,
            'Rejected': loan_app_queryset.filter(status='Rejected').count() or 0,
            'Disbursed': loan_app_queryset.filter(status='Disbursed').count() or 0,
            'New Entry': loan_app_queryset.filter(status='New Entry').count() or 0,
            'Required Follow-up': loan_app_queryset.filter(status='Required Follow-up').count() or 0,
        }
        
        # Monthly Loan Trend for Line Graph
        monthly_trend = loan_app_queryset.annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(
            count=Count('id'),
            total_amount=Sum('loan_amount')
        ).order_by('month')
        
        monthly_loan_trend = []
        for item in monthly_trend:
            if item['month']:
                monthly_loan_trend.append({
                    'month': item['month'].strftime('%b %Y'),
                    'count': item['count'] or 0,
                    'amount': float(item['total_amount'] or 0)
                })
        
        # Complaints Overview
        complaints_stats = {
            'total_complaints': complaint_queryset.count() or 0,
            'open_complaints': complaint_queryset.filter(status='open').count() or 0,
            'resolved_complaints': complaint_queryset.filter(status='resolved').count() or 0,
        }
        
        # Recent Activities
        recent_activities = ActivityLog.objects.all().order_by('-created_at')[:10]
        
        data = {
            **stats,
            'loan_status_breakdown': loan_status_breakdown,
            'monthly_loan_trend': monthly_loan_trend,
            **complaints_stats,
            'recent_activities': ActivityLogSerializer(recent_activities, many=True).data,
            'success': True,
        }
        
        # Return data directly since serializer is just for documentation
        return Response(data, status=status.HTTP_200_OK)
    
    except Exception as e:
        # Return safe error response with default 0 values
        return Response({
            'success': False,
            'error': 'Failed to load dashboard data. Please refresh the page.',
            'total_new_entry': 0,
            'waiting_for_processing': 0,
            'required_follow_up': 0,
            'approved': 0,
            'rejected': 0,
            'disbursed': 0,
            'loan_status_breakdown': {
                'approved': 0,
                'waiting': 0,
                'rejected': 0,
                'disbursed': 0,
                'new_entry': 0,
                'follow_up': 0,
            },
            'monthly_loan_trend': [],
            'total_complaints': 0,
            'open_complaints': 0,
            'resolved_complaints': 0,
            'recent_activities': [],
        }, status=status.HTTP_200_OK)


# ==================== REGISTRATION WIZARD VIEWS ====================

def registration_wizard(request, step=1, role=None):
    """Multi-step registration wizard for Employee/Channel Partner."""
    valid_roles = {"employee", "agent"}
    role_labels = {"employee": "Employee", "agent": "Channel Partner"}
    bank_type_labels = {"current": "Current", "saving": "Saving", "cc": "CC", "od": "OD"}
    success_message_text = "Application submitted successfully! Your application has been added to the New Entries list."

    normalized_role = (role or "").strip().lower()
    if normalized_role not in valid_roles:
        normalized_role = "employee"

    is_employee = normalized_role == "employee"
    total_steps = 3 if is_employee else 4
    step = max(1, min(int(step or 1), total_steps))
    progress = int((step / total_steps) * 100)

    if request.method == "GET" and request.GET.get("submitted") == "1":
        return render(
            request,
            "core/registration_wizard.html",
            {
                "show_success_message": True,
                "success_message_text": success_message_text,
                "success_redirect_url": "/admin-login/",
                "step": step,
                "role": normalized_role,
                "role_display": role_labels.get(normalized_role, normalized_role.title()),
                "progress": progress,
                "is_employee_registration": is_employee,
                "step_labels": ["Details", "Resume", "Review"] if is_employee else ["Details", "Bank", "Documents", "Review"],
            },
        )

    session_key = f"applicant_{normalized_role}"
    applicant_data = request.session.get(session_key, {})
    required_document_types = {"photo", "pan_front", "aadhaar_front"}
    excluded_extra_types = required_document_types | {"resume"}
    extra_document_choices = [
        (value, label)
        for value, label in ApplicantDocument.DOCUMENT_TYPE_CHOICES
        if value not in excluded_extra_types
    ]
    allowed_extra_document_types = {value for value, _label in extra_document_choices}

    def _build_unique_applicant_username(base_value):
        raw = str(base_value or "").strip().lower()
        sanitized = re.sub(r"[^a-z0-9_]", "", raw)
        base = sanitized or "applicant"
        candidate = base[:80]
        counter = 1
        while Applicant.objects.filter(username=candidate).exists():
            suffix = str(counter)
            candidate = f"{base[: max(1, 80 - len(suffix))]}{suffix}"
            counter += 1
        return candidate

    if request.method == "POST":
        if is_employee:
            if step == 1:
                form = EmployeeRegistrationStep1Form(request.POST)
                if form.is_valid():
                    total_experience_years = form.cleaned_data.get("total_experience_years")
                    current_salary = form.cleaned_data.get("current_salary")
                    expected_salary = form.cleaned_data.get("expected_salary")
                    applicant_data = {
                        "role": normalized_role,
                        "full_name": form.cleaned_data.get("full_name"),
                        "mobile": form.cleaned_data.get("mobile"),
                        "email": form.cleaned_data.get("email"),
                        "city": form.cleaned_data.get("city"),
                        "state": form.cleaned_data.get("state"),
                        "pin_code": form.cleaned_data.get("pin_code"),
                        "gender": form.cleaned_data.get("gender"),
                        "current_job_title": form.cleaned_data.get("current_job_title"),
                        "total_experience_years": str(total_experience_years) if total_experience_years is not None else None,
                        "current_salary": str(current_salary) if current_salary is not None else None,
                        "expected_salary": str(expected_salary) if expected_salary is not None else None,
                        "notice_period": form.cleaned_data.get("notice_period"),
                    }
                    applicant_data["username"] = _build_unique_applicant_username(
                        applicant_data.get("mobile")
                        or applicant_data.get("email")
                        or applicant_data.get("full_name")
                    )
                    request.session[session_key] = applicant_data
                    request.session.modified = True
                    return redirect(f"/register/{normalized_role}/step/2/")

            elif step == 2:
                if not applicant_data:
                    return redirect(f"/register/{normalized_role}/step/1/")
                form = EmployeeResumeUploadForm(request.POST, request.FILES)
                if form.is_valid():
                    try:
                        applicant_payload = {
                            "role": applicant_data.get("role", normalized_role),
                            "full_name": applicant_data.get("full_name"),
                            "username": applicant_data.get("username")
                            or _build_unique_applicant_username(
                                applicant_data.get("mobile") or applicant_data.get("full_name")
                            ),
                            "mobile": applicant_data.get("mobile"),
                            "email": applicant_data.get("email"),
                            "city": applicant_data.get("city"),
                            "state": applicant_data.get("state"),
                            "pin_code": applicant_data.get("pin_code"),
                            "gender": applicant_data.get("gender"),
                            "current_job_title": applicant_data.get("current_job_title"),
                            "total_experience_years": applicant_data.get("total_experience_years"),
                            "current_salary": applicant_data.get("current_salary"),
                            "expected_salary": applicant_data.get("expected_salary"),
                            "notice_period": applicant_data.get("notice_period"),
                        }
                        applicant = Applicant.objects.create(**applicant_payload)
                        loan_app = LoanApplication.objects.create(applicant=applicant)
                        ApplicantDocument.objects.create(
                            loan_application=loan_app,
                            document_type="resume",
                            file=form.cleaned_data["resume"],
                            is_required=True,
                        )
                        return redirect(f"/register/{normalized_role}/step/3/?applicant_id={applicant.id}")
                    except Exception as e:
                        if "username" in str(e).lower():
                            messages.error(request, "Username already exists. Please try again.")
                        else:
                            messages.error(request, f"Error during registration: {str(e)}")
                        return redirect(f"/register/{normalized_role}/step/1/")

            elif step == 3:
                applicant_id = request.GET.get("applicant_id") or request.POST.get("applicant_id")
                if not applicant_id:
                    return redirect(f"/register/{normalized_role}/step/1/")

                try:
                    applicant = Applicant.objects.get(id=applicant_id, role=normalized_role)
                except Applicant.DoesNotExist:
                    return redirect(f"/register/{normalized_role}/step/1/")

                loan_app = applicant.loan_application
                loan_app.status = "New Entry"
                loan_app.save()

                ActivityLog.objects.create(
                    action="loan_added",
                    description=f"New {role_labels.get(applicant.role, applicant.role.title())} application from {applicant.full_name}",
                )

                if session_key in request.session:
                    del request.session[session_key]
                    request.session.modified = True

                return redirect(f"/register/{normalized_role}/step/3/?submitted=1")

        else:
            if step == 1:
                form = ApplicantStep1Form(request.POST)
                if form.is_valid():
                    applicant_data = {
                        "role": normalized_role,
                        "full_name": form.cleaned_data.get("full_name"),
                        "username": form.cleaned_data.get("username"),
                        "mobile": form.cleaned_data.get("mobile"),
                        "email": form.cleaned_data.get("email"),
                        "city": form.cleaned_data.get("city"),
                        "state": form.cleaned_data.get("state"),
                        "pin_code": form.cleaned_data.get("pin_code"),
                        "gender": form.cleaned_data.get("gender"),
                    }
                    request.session[session_key] = applicant_data
                    request.session.modified = True
                    return redirect(f"/register/{normalized_role}/step/2/")

            elif step == 2:
                if not applicant_data:
                    return redirect(f"/register/{normalized_role}/step/1/")
                form = ApplicantStep2Form(request.POST)
                if form.is_valid():
                    applicant_data.update(
                        {
                            "bank_name": form.cleaned_data.get("bank_name"),
                            "account_number": form.cleaned_data.get("bank_account_number"),
                            "ifsc_code": form.cleaned_data.get("ifsc_code"),
                            "bank_type": form.cleaned_data.get("bank_type"),
                        }
                    )
                    request.session[session_key] = applicant_data
                    request.session.modified = True
                    return redirect(f"/register/{normalized_role}/step/3/")

            elif step == 3:
                if not applicant_data:
                    return redirect(f"/register/{normalized_role}/step/1/")
                form = DocumentUploadForm(request.POST, request.FILES)
                if form.is_valid():
                    optional_doc_types = request.POST.getlist("extra_document_type[]")
                    optional_doc_files = request.FILES.getlist("extra_document_file[]")
                    selected_types = set(required_document_types)
                    optional_documents = []
                    optional_rows = max(len(optional_doc_types), len(optional_doc_files))

                    for idx in range(optional_rows):
                        doc_type = (optional_doc_types[idx] if idx < len(optional_doc_types) else "").strip()
                        doc_file = optional_doc_files[idx] if idx < len(optional_doc_files) else None
                        if not doc_type and not doc_file:
                            continue
                        if doc_type and not doc_file:
                            form.add_error(None, f"Please upload a file for additional document row {idx + 1}.")
                            continue
                        if doc_file and not doc_type:
                            form.add_error(None, f"Please select document type for additional document row {idx + 1}.")
                            continue
                        if doc_type not in allowed_extra_document_types:
                            form.add_error(None, f"Invalid document type selected in row {idx + 1}.")
                            continue
                        if doc_type in selected_types:
                            form.add_error(None, f"Duplicate document type selected in row {idx + 1}.")
                            continue
                        selected_types.add(doc_type)
                        optional_documents.append((doc_type, doc_file))

                    if not form.errors:
                        try:
                            applicant_payload = {
                                "role": applicant_data.get("role", normalized_role),
                                "full_name": applicant_data.get("full_name"),
                                "username": applicant_data.get("username"),
                                "mobile": applicant_data.get("mobile"),
                                "email": applicant_data.get("email"),
                                "city": applicant_data.get("city"),
                                "state": applicant_data.get("state"),
                                "pin_code": applicant_data.get("pin_code"),
                                "gender": applicant_data.get("gender"),
                                "bank_name": applicant_data.get("bank_name"),
                                "account_number": applicant_data.get("account_number"),
                                "ifsc_code": applicant_data.get("ifsc_code"),
                                "bank_type": applicant_data.get("bank_type"),
                            }
                            applicant = Applicant.objects.create(**applicant_payload)
                            loan_app = LoanApplication.objects.create(applicant=applicant)

                            ApplicantDocument.objects.create(
                                loan_application=loan_app,
                                document_type="photo",
                                file=form.cleaned_data["photo"],
                                is_required=True,
                            )
                            ApplicantDocument.objects.create(
                                loan_application=loan_app,
                                document_type="pan_front",
                                file=form.cleaned_data["pan_card"],
                                is_required=True,
                            )
                            ApplicantDocument.objects.create(
                                loan_application=loan_app,
                                document_type="aadhaar_front",
                                file=form.cleaned_data["aadhaar_card"],
                                is_required=True,
                            )

                            for doc_type, doc_file in optional_documents:
                                ApplicantDocument.objects.create(
                                    loan_application=loan_app,
                                    document_type=doc_type,
                                    file=doc_file,
                                    is_required=False,
                                )

                            return redirect(f"/register/{normalized_role}/step/4/?applicant_id={applicant.id}")
                        except Exception as e:
                            if "username" in str(e).lower():
                                messages.error(request, "Username already exists. Please choose a different username.")
                            else:
                                messages.error(request, f"Error during registration: {str(e)}")
                            return redirect(f"/register/{normalized_role}/step/1/")

            elif step == 4:
                applicant_id = request.GET.get("applicant_id") or request.POST.get("applicant_id")
                if not applicant_id:
                    return redirect(f"/register/{normalized_role}/step/1/")

                try:
                    applicant = Applicant.objects.get(id=applicant_id, role=normalized_role)
                except Applicant.DoesNotExist:
                    return redirect(f"/register/{normalized_role}/step/1/")

                loan_app = applicant.loan_application
                loan_app.status = "New Entry"
                loan_app.save()

                ActivityLog.objects.create(
                    action="loan_added",
                    description=f"New {role_labels.get(applicant.role, applicant.role.title())} application from {applicant.full_name}",
                )

                if session_key in request.session:
                    del request.session[session_key]
                    request.session.modified = True

                return redirect(f"/register/{normalized_role}/step/4/?submitted=1")

    else:
        if is_employee:
            if step == 1:
                form = EmployeeRegistrationStep1Form(initial=applicant_data or None)
            elif step == 2:
                if not applicant_data:
                    return redirect(f"/register/{normalized_role}/step/1/")
                form = EmployeeResumeUploadForm()
            elif step == 3:
                applicant_id = request.GET.get("applicant_id")
                if not applicant_id:
                    return redirect(f"/register/{normalized_role}/step/1/")
                try:
                    applicant = Applicant.objects.get(id=applicant_id, role=normalized_role)
                except Applicant.DoesNotExist:
                    return redirect(f"/register/{normalized_role}/step/1/")
                docs = applicant.loan_application.documents.all().order_by("uploaded_at")
                applicant_data = {
                    "id": applicant.id,
                    "full_name": applicant.full_name,
                    "mobile": applicant.mobile,
                    "email": applicant.email,
                    "city": applicant.city,
                    "state": applicant.state,
                    "pin_code": applicant.pin_code,
                    "gender": applicant.get_gender_display(),
                    "current_job_title": applicant.current_job_title,
                    "total_experience_years": applicant.total_experience_years,
                    "current_salary": applicant.current_salary,
                    "expected_salary": applicant.expected_salary,
                    "notice_period": applicant.notice_period,
                    "documents": [
                        {
                            "document_type": doc.document_type,
                            "document_type_display": doc.get_document_type_display(),
                        }
                        for doc in docs
                    ],
                }
                form = None
            else:
                form = None
        else:
            if step == 1:
                form = ApplicantStep1Form(initial=applicant_data or None)
            elif step == 2:
                if not applicant_data:
                    return redirect(f"/register/{normalized_role}/step/1/")
                form = ApplicantStep2Form(
                    initial={
                        "bank_name": applicant_data.get("bank_name", ""),
                        "bank_account_number": applicant_data.get("account_number", ""),
                        "ifsc_code": applicant_data.get("ifsc_code", ""),
                        "bank_type": applicant_data.get("bank_type", ""),
                    }
                )
            elif step == 3:
                if not applicant_data:
                    return redirect(f"/register/{normalized_role}/step/1/")
                form = DocumentUploadForm()
            elif step == 4:
                applicant_id = request.GET.get("applicant_id")
                if not applicant_id:
                    return redirect(f"/register/{normalized_role}/step/1/")
                try:
                    applicant = Applicant.objects.get(id=applicant_id, role=normalized_role)
                except Applicant.DoesNotExist:
                    return redirect(f"/register/{normalized_role}/step/1/")
                docs = applicant.loan_application.documents.all().order_by("uploaded_at")
                applicant_data = {
                    "id": applicant.id,
                    "full_name": applicant.full_name,
                    "role": applicant.role,
                    "role_display": role_labels.get(applicant.role, applicant.role.title()),
                    "username": applicant.username,
                    "mobile": applicant.mobile,
                    "email": applicant.email,
                    "city": applicant.city,
                    "state": applicant.state,
                    "pin_code": applicant.pin_code,
                    "gender": applicant.get_gender_display(),
                    "bank_name": applicant.bank_name,
                    "account_number": applicant.account_number,
                    "ifsc_code": applicant.ifsc_code,
                    "bank_type": applicant.bank_type,
                    "bank_type_display": bank_type_labels.get(applicant.bank_type, applicant.bank_type or "-"),
                    "documents": [
                        {
                            "document_type": doc.document_type,
                            "document_type_display": doc.get_document_type_display(),
                        }
                        for doc in docs
                    ],
                }
                form = None
            else:
                form = None

    context = {
        "form": form,
        "step": step,
        "role": normalized_role,
        "role_display": role_labels.get(normalized_role, normalized_role.title()),
        "progress": progress,
        "applicant_data": applicant_data,
        "extra_document_choices": extra_document_choices,
        "is_employee_registration": is_employee,
        "is_review_step": (is_employee and step == 3) or ((not is_employee) and step == 4),
        "step_labels": ["Details", "Resume", "Review"] if is_employee else ["Details", "Bank", "Documents", "Review"],
        "show_success_message": False,
        "success_message_text": success_message_text,
        "success_redirect_url": "/admin-login/",
    }

    return render(request, "core/registration_wizard.html", context)


def new_entries(request):
    """Admin view for New Entry applications"""
    from django.contrib.auth.decorators import login_required
    
    if not request.user.is_authenticated or request.user.role != 'admin':
        return redirect('admin_login')
    
    # Get applications from LoanApplication model (old entries)
    old_applications = LoanApplication.objects.filter(status='New Entry').select_related('applicant')
    
    # Get new applications from Loan model (created by agents)
    new_loan_applications = Loan.objects.filter(
        status='new_entry',
        applicant_type='agent'
    ).select_related('assigned_agent', 'created_by').order_by('-created_at')
    
    context = {
        'applications': old_applications,
        'new_loan_applications': new_loan_applications,
        'new_entries_count': old_applications.count(),
        'agent_entries_count': new_loan_applications.count(),
    }
    
    return render(request, 'core/new_entries.html', context)


def new_entry_detail(request, applicant_id):
    """View details of a specific new entry application"""
    from django.contrib.auth.decorators import login_required
    
    if not request.user.is_authenticated or request.user.role != 'admin':
        return redirect('admin_login')
    
    applicant = Applicant.objects.get(id=applicant_id)
    loan_app = applicant.loan_application
    documents = loan_app.documents.all()
    photo_document = loan_app.documents.filter(document_type='photo').first()
    agents = Agent.objects.filter(status='active')
    employees = User.objects.filter(role='employee', is_active=True)
    
    context = {
        'applicant': applicant,
        'loan_app': loan_app,
        'documents': documents,
        'photo_document': photo_document,
        'agents': agents,
        'employees': employees,
    }
    
    return render(request, 'core/new_entry_detail.html', context)


def application_detail(request, applicant_id):
    """Comprehensive view for loan application details"""
    if not request.user.is_authenticated or request.user.role != 'admin':
        return redirect('admin_login')
    
    try:
        # Try to get from Loan model first (new entries)
        entry = Loan.objects.get(id=applicant_id)
        # Convert to applicant-like object for template
        entry.applicant = type('obj', (object,), {
            'full_name': entry.full_name,
            'email': entry.email,
            'mobile': entry.mobile_number,
            'photo': None
        })()
        entry.date_of_birth = getattr(entry, 'date_of_birth', 'N/A')
        entry.gender = getattr(entry, 'gender', 'N/A')
        entry.alternate_phone = getattr(entry, 'alternate_phone', 'N/A')
        entry.annual_income = getattr(entry, 'annual_income', 'N/A')
        entry.employment_type = getattr(entry, 'employment_type', 'N/A')
        entry.employer_name = getattr(entry, 'employer_name', 'N/A')
        entry.loan_tenure = entry.tenure_months
        entry.bank_name = entry.bank_name
        entry.account_type = getattr(entry, 'account_type', 'N/A')
        entry.collateral_details = getattr(entry, 'collateral_details', 'N/A')
        entry.collateral_value = getattr(entry, 'collateral_value', 'N/A')
        entry.existing_loans = getattr(entry, 'existing_loans', 'N/A')
        entry.credit_score = getattr(entry, 'credit_score', 'N/A')
        entry.extra_income = getattr(entry, 'extra_income', 'N/A')
        entry.internal_remarks = getattr(entry, 'internal_remarks', 'N/A')
        entry.created_at = entry.created_at
        entry.assigned_to = entry.assigned_employee or entry.assigned_agent
    except Loan.DoesNotExist:
        try:
            # Try to get from LoanApplication model
            from .models import LoanApplication
            loan_app = LoanApplication.objects.get(applicant=applicant_id)
            applicant = loan_app.applicant
            entry = loan_app
            entry.applicant = applicant
            entry.loan_tenure = getattr(entry, 'loan_tenure', 'N/A')
            entry.assigned_to = getattr(entry, 'assigned_to', None)
        except:
            return redirect('new_entries')
    except Exception as e:
        print(f"Error in application_detail: {str(e)}")
        return redirect('new_entries')
    
    context = {
        'entry': entry,
    }
    
    return render(request, 'core/application_detail.html', context)


def assign_application(request, applicant_id):
    """Assign application to agent or employee - Show assignment page"""
    if not request.user.is_authenticated or request.user.role != 'admin':
        return redirect('admin_login')
    
    # GET: Show assignment page
    if request.method == 'GET':
        return render(request, 'core/assign_application.html', {'applicant_id': applicant_id})
    
    # POST: Handle assignment via form (for backward compatibility)
    if request.method == 'POST':
        try:
            # Try to find Loan record first
            loan = Loan.objects.get(id=applicant_id)
            
            assign_to = request.POST.get('assign_to')
            assign_type = request.POST.get('assign_type', 'employee')
            
            if assign_type == 'agent':
                agent = Agent.objects.get(id=assign_to)
                # Update loan assigned_to field if it exists
                if hasattr(loan, 'assigned_agent'):
                    loan.assigned_agent = agent
            else:
                employee = User.objects.get(id=assign_to)
                # Update loan assigned_to field if it exists
                if hasattr(loan, 'assigned_to'):
                    loan.assigned_to = employee
            
            loan.status = 'waiting'  # Change status to waiting
            loan.save()
            
            # Log activity
            ActivityLog.objects.create(
                action='status_updated',
                description=f"Loan #{applicant_id} assigned to {assign_type}",
            )
            
            messages.success(request, 'Application assigned successfully! Status changed to Waiting.')
            return redirect('new_entries')
        except Exception as e:
            messages.error(request, f'Error assigning application: {str(e)}')
            return redirect('new_entries')
    
    return redirect('admin_login')


# Employee/Agent Workflow Views
@login_required
def my_applications(request):
    """Show applications waiting for processing assigned to current user"""
    if request.user.role not in ['employee', 'agent']:
        return redirect('admin_dashboard')
    
    if request.user.role == 'employee':
        applications = LoanApplication.objects.filter(
            assigned_employee=request.user,
            status='Waiting for Processing'
        ).select_related('applicant').prefetch_related('documents')
    else:
        # For agents
        agent = request.user.agent_profile
        applications = LoanApplication.objects.filter(
            assigned_agent=agent,
            status='Waiting for Processing'
        ).select_related('applicant').prefetch_related('documents')
    
    context = {
        'applications': applications,
        'app_count': applications.count(),
    }
    return render(request, 'core/my_applications.html', context)


@login_required
def view_application(request, applicant_id):
    """
    Smart router view that displays application detail based on status and user role.
    Routes to appropriate template based on application status.
    """
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        documents = loan_app.documents.all()
        
        # ADMIN VIEWS - Can see all statuses
        if request.user.role == 'admin':
            if loan_app.status == 'New Entry':
                return view_new_entry_detail(request, applicant_id)
            elif loan_app.status == 'Required Follow-up':
                return view_followup_detail(request, applicant_id)
            elif loan_app.status == 'Waiting for Processing':
                return view_waiting_detail(request, applicant_id)
            else:
                # Approved/Rejected - read-only
                context = {
                    'applicant': applicant,
                    'loan_app': loan_app,
                    'documents': documents,
                }
                return render(request, 'core/view_application.html', context)
        
        # EMPLOYEE/AGENT VIEWS - Can only see assigned applications in Waiting state
        elif request.user.role == 'employee':
            if loan_app.assigned_employee != request.user:
                messages.error(request, 'You do not have access to this application.')
                return redirect('my_applications')
            
            if loan_app.status == 'Waiting for Processing':
                return view_waiting_detail(request, applicant_id)
            else:
                messages.error(request, 'You can only view applications assigned to you in Waiting state.')
                return redirect('my_applications')
        
        elif request.user.role == 'agent':
            agent = request.user.agent_profile
            if loan_app.assigned_agent != agent:
                messages.error(request, 'You do not have access to this application.')
                return redirect('my_applications')
            
            if loan_app.status == 'Waiting for Processing':
                return view_waiting_detail(request, applicant_id)
            else:
                messages.error(request, 'You can only view applications assigned to you in Waiting state.')
                return redirect('my_applications')
        
        else:
            return redirect('admin_login')
    
    except Applicant.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('admin_dashboard')
    except Exception as e:
        messages.error(request, f'Error loading application: {str(e)}')
        return redirect('admin_dashboard')


@login_required
@login_required
def view_new_entry_detail(request, applicant_id):
    """
    Admin-only view for NEW ENTRY applications.
    Shows full editable details and assignment UI.
    
    Rules:
    - ADMIN ONLY
    - Editable applicant form
    - Assign UI (employee/agent selection)
    - Approve/Reject buttons
    """
    # STRICT PERMISSION CHECK: Admin only
    if request.user.role != 'admin':
        messages.error(request, 'Only admins can manage new entries.')
        return redirect('admin_dashboard')
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        documents = loan_app.documents.all()
        photo_document = documents.filter(document_type='photo').first()
        
        # Only allow viewing NEW ENTRY status applications
        if loan_app.status != 'New Entry':
            messages.warning(request, f'This application status has changed to: {loan_app.status}. Redirecting...')
            return redirect('admin_dashboard')
        
        # Get available agents and employees for assignment
        agents = Agent.objects.filter(status='active')
        employees = User.objects.filter(role='employee', is_active=True)
        
        context = {
            'applicant': applicant,
            'loan_app': loan_app,
            'documents': documents,
            'photo_document': photo_document,
            'agents': agents,
            'employees': employees,
            'is_new_entry': True,  # Signal to template: show editable form + assign UI
            'can_edit': True,  # Admin can edit in new entry
            'can_assign': True,  # Admin can assign in new entry
        }
        return render(request, 'admin/new_entry_detail.html', context)
    
    except Applicant.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('admin_dashboard')
    except Exception as e:
        messages.error(request, f'Error: {str(e)}')
        return redirect('admin_dashboard')


@login_required
def view_waiting_detail(request, applicant_id):
    """
    Waiting for Processing view - READ-ONLY for employees/agents.
    
    Rules:
    - VISIBLE TO: Assigned employee/agent OR admin
    - READ-ONLY applicant, loan, bank details
    - Shows all documents
    - Approve/Reject buttons ONLY
    - NO assign UI, NO role selection, NO editable form
    """
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        documents = loan_app.documents.all()
        photo_document = documents.filter(document_type='photo').first()
        
        # STRICT PERMISSION CHECK: Only assigned user or admin
        if request.user.role == 'employee':
            if loan_app.assigned_employee != request.user:
                messages.error(request, 'You do not have access to this application.')
                return redirect('my_applications')
        elif request.user.role == 'agent':
            agent = request.user.agent_profile
            if loan_app.assigned_agent != agent:
                messages.error(request, 'You do not have access to this application.')
                return redirect('my_applications')
        elif request.user.role != 'admin':
            messages.error(request, 'Access denied.')
            return redirect('admin_login')
        
        # Only allow viewing WAITING FOR PROCESSING status
        if loan_app.status != 'Waiting for Processing':
            messages.warning(request, f'This application is in {loan_app.status} status, not Waiting for Processing.')
            return redirect('my_applications' if request.user.role != 'admin' else 'admin_dashboard')
        
        # Calculate waiting time
        waiting_age_hours = loan_app.hours_since_assignment
        
        context = {
            'applicant': applicant,
            'loan_app': loan_app,
            'documents': documents,
            'photo_document': photo_document,
            'waiting_age_hours': waiting_age_hours,
            'is_waiting': True,  # Signal to template: read-only + approve/reject only
            'can_edit': False,  # No editing in waiting state
            'can_assign': False,  # No assignment in waiting state
            'can_approve_reject': True,  # Approve/reject buttons visible
            'assigned_to_current_user': (
                (request.user.role == 'employee' and loan_app.assigned_employee == request.user) or
                (request.user.role == 'agent' and loan_app.assigned_agent == request.user.agent_profile)
            ),
        }
        return render(request, 'dashboard/waiting_detail.html', context)
    
    except Applicant.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('my_applications' if request.user.role != 'admin' else 'admin_dashboard')
    except Exception as e:
        messages.error(request, f'Error: {str(e)}')
        return redirect('my_applications' if request.user.role != 'admin' else 'admin_dashboard')


@login_required
def view_followup_detail(request, applicant_id):
    """
    Follow-up Required view - ADMIN-ONLY, READ-ONLY.
    
    Rules:
    - ADMIN ONLY
    - READ-ONLY summary of applicant/loan/bank details
    - Shows documents
    - Reassign/reminder options visible
    - NO editing of applicant data
    """
    # STRICT PERMISSION CHECK: Admin only
    if request.user.role != 'admin':
        messages.error(request, 'Only admins can view follow-up applications.')
        return redirect('admin_dashboard')
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        documents = loan_app.documents.all()
        photo_document = documents.filter(document_type='photo').first()
        
        # Only allow viewing REQUIRED FOLLOW-UP status
        if loan_app.status != 'Required Follow-up':
            messages.warning(request, f'This application is in {loan_app.status} status, not Required Follow-up.')
            return redirect('workflow_dashboard')
        
        # Calculate ages
        waiting_age_hours = loan_app.hours_since_assignment
        follow_up_age_hours = (timezone.now() - loan_app.follow_up_scheduled_at).total_seconds() / 3600 if loan_app.follow_up_scheduled_at else 0
        
        # Get available agents and employees for reassignment
        agents = Agent.objects.filter(status='active')
        employees = User.objects.filter(role='employee', is_active=True)
        
        context = {
            'applicant': applicant,
            'loan_app': loan_app,
            'documents': documents,
            'photo_document': photo_document,
            'waiting_age_hours': waiting_age_hours,
            'follow_up_age_hours': follow_up_age_hours,
            'is_followup': True,  # Signal to template: read-only + reassign/reminder
            'can_edit': False,  # No editing in follow-up state
            'can_reassign': True,  # Admin can reassign
            'agents': agents,
            'employees': employees,
            'follow_up_count': loan_app.follow_up_count,
        }
        return render(request, 'admin/followup_detail.html', context)
    
    except Applicant.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('workflow_dashboard')
    except Exception as e:
        messages.error(request, f'Error: {str(e)}')
        return redirect('workflow_dashboard')



@api_view(['GET'])
@login_required
def get_employees_list(request):
    """Get list of employees for assignment"""
    if request.user.role not in ['admin', 'subadmin']:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    employees = User.objects.filter(role='employee', is_active=True).values('id', 'username', 'first_name', 'last_name', 'email')
    return Response(list(employees))


@api_view(['GET'])
@login_required
def get_agents_list(request):
    """Get list of agents for assignment"""
    if request.user.role not in ['admin', 'subadmin']:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    agents = Agent.objects.filter(status='active').values('id', 'name', 'phone', 'email')
    return Response(list(agents))


@api_view(['POST'])
@login_required
def assign_to_employee(request, applicant_id):
    """Assign application to employee"""
    if request.user.role not in ['admin', 'subadmin']:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        employee_id = request.data.get('employee_id')
        
        employee = User.objects.get(id=employee_id, role='employee', is_active=True)
        loan_app.assigned_employee = employee
        previous_status = loan_app.status
        loan_app.status = 'Waiting for Processing'
        loan_app.assigned_at = timezone.now()
        loan_app.assigned_by = request.user
        loan_app.save()

        LoanStatusHistory.objects.create(
            loan_application=loan_app,
            from_status='new_entry' if previous_status == 'New Entry' else None,
            to_status='waiting',
            changed_by=request.user,
            reason=f'Assigned to employee {employee.get_full_name()}',
            is_auto_triggered=False,
        )
        
        # Log activity
        ActivityLog.objects.create(
            action='application_assigned',
            description=f"Application {applicant.full_name} assigned to {employee.first_name} {employee.last_name}",
        )
        
        return Response({
            'success': True,
            'message': f'Assigned to {employee.first_name} {employee.last_name}',
            'status': loan_app.status
        })
    
    except Applicant.DoesNotExist:
        return Response({'error': 'Applicant not found'}, status=status.HTTP_404_NOT_FOUND)
    except User.DoesNotExist:
        return Response({'error': 'Employee not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@login_required
def assign_to_agent(request, applicant_id):
    """Assign application to agent"""
    if request.user.role not in ['admin', 'subadmin']:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        agent_id = request.data.get('agent_id')
        
        agent = Agent.objects.get(id=agent_id, status='active')
        loan_app.assigned_agent = agent
        previous_status = loan_app.status
        loan_app.status = 'Waiting for Processing'
        loan_app.assigned_at = timezone.now()
        loan_app.assigned_by = request.user
        loan_app.save()

        LoanStatusHistory.objects.create(
            loan_application=loan_app,
            from_status='new_entry' if previous_status == 'New Entry' else None,
            to_status='waiting',
            changed_by=request.user,
            reason=f'Assigned to agent {agent.name}',
            is_auto_triggered=False,
        )
        
        # Log activity
        ActivityLog.objects.create(
            action='application_assigned',
            description=f"Application {applicant.full_name} assigned to Agent {agent.name}",
        )
        
        return Response({
            'success': True,
            'message': f'Assigned to {agent.name}',
            'status': loan_app.status
        })
    
    except Applicant.DoesNotExist:
        return Response({'error': 'Applicant not found'}, status=status.HTTP_404_NOT_FOUND)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@login_required
def approve_application(request, applicant_id):
    """Approve an application"""
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        
        # Only assigned employee or admin can approve
        if request.user.role == 'employee' and loan_app.assigned_employee != request.user:
            return Response({'error': 'Unauthorized - Not assigned to you'}, status=status.HTTP_403_FORBIDDEN)
        
        approval_notes = request.data.get('approval_notes', '')
        
        loan_app.status = 'Approved'
        loan_app.approved_by = request.user
        loan_app.approval_notes = approval_notes
        loan_app.approved_at = timezone.now()
        loan_app.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='application_approved',
            description=f"Application {applicant.full_name} approved by {request.user.first_name}",
        )
        
        return Response({
            'success': True,
            'message': 'Application approved successfully',
            'status': loan_app.status
        })
    
    except Applicant.DoesNotExist:
        return Response({'error': 'Applicant not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# Enhanced Workflow Dashboard Views
# ============================================================================

@login_required
def workflow_dashboard(request):
    """Admin workflow dashboard with sectioned view"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    # Fetch applications by status
    new_entries = LoanApplication.objects.filter(
        status='New Entry'
    ).select_related('applicant').prefetch_related('documents').order_by('-created_at')
    
    waiting = LoanApplication.objects.filter(
        status='Waiting for Processing'
    ).select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-assigned_at')
    
    follow_ups = LoanApplication.objects.filter(
        status='Required Follow-up'
    ).select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-follow_up_scheduled_at')
    
    approved = LoanApplication.objects.filter(
        status='Approved'
    ).select_related('applicant', 'approved_by').order_by('-approved_at')
    
    rejected = LoanApplication.objects.filter(
        status='Rejected'
    ).select_related('applicant', 'rejected_by').order_by('-rejected_at')
    
    # Calculate workflow stats
    stats = {
        'new_entry_count': new_entries.count(),
        'waiting_count': waiting.count(),
        'follow_up_count': follow_ups.count(),
        'approved_count': approved.count(),
        'rejected_count': rejected.count(),
        'total_applications': LoanApplication.objects.count(),
    }
    
    # Add aging info for waiting and follow-up
    waiting_with_age = []
    for app in waiting:
        hours_waiting = app.hours_since_assignment
        requires_fu = app.requires_follow_up
        waiting_with_age.append({
            'app': app,
            'hours_since_assignment': hours_waiting,
            'requires_follow_up': requires_fu,
        })
    
    follow_ups_with_info = []
    for app in follow_ups:
        follow_ups_with_info.append({
            'app': app,
            'follow_up_count': app.follow_up_count,
            'follow_up_age': (timezone.now() - app.follow_up_scheduled_at).total_seconds() / 3600 if app.follow_up_scheduled_at else 0,
        })
    
    context = {
        'stats': stats,
        'new_entries': new_entries,
        'waiting': waiting_with_age,
        'follow_ups': follow_ups_with_info,
        'approved': approved,
        'rejected': rejected,
        'page_title': 'Workflow Dashboard',
    }
    
    return render(request, 'core/workflow_dashboard.html', context)


@api_view(['POST'])
@login_required
def batch_assign_applications(request):
    """Batch assign multiple applications"""
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        application_ids = request.data.get('application_ids', [])
        assign_to_id = request.data.get('assign_to_id')
        assign_type = request.data.get('assign_type')  # 'employee' or 'agent'
        
        applications = LoanApplication.objects.filter(id__in=application_ids, status='New Entry')
        updated_count = 0
        
        for app in applications:
            if assign_type == 'employee':
                employee = User.objects.get(id=assign_to_id, role='employee', is_active=True)
                app.assigned_employee = employee
            elif assign_type == 'agent':
                agent = Agent.objects.get(id=assign_to_id, status='active')
                app.assigned_agent = agent
            
            app.status = 'Waiting for Processing'
            app.assigned_at = timezone.now()
            app.assigned_by = request.user
            app.save()
            
            # Log activity
            ActivityLog.objects.create(
                action='application_assigned',
                description=f"Application {app.applicant.full_name} batch assigned to {assign_type}",
            )
            
            updated_count += 1
        
        return Response({
            'success': True,
            'message': f'{updated_count} applications assigned successfully',
            'count': updated_count
        })
    
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@login_required
def get_application_detail(request, applicant_id):
    """Get detailed info for an application"""
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        
        # Check permission
        if request.user.role == 'employee' and loan_app.assigned_employee != request.user:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
        documents = loan_app.documents.all().values('id', 'document_type', 'uploaded_at')
        
        data = {
            'id': loan_app.id,
            'applicant_name': applicant.full_name,
            'loan_type': applicant.get_loan_type_display() if hasattr(applicant, 'get_loan_type_display') else str(applicant.loan_type),
            'loan_amount': applicant.loan_amount,
            'status': loan_app.status,
            'assigned_employee': loan_app.assigned_employee.get_full_name() if loan_app.assigned_employee else None,
            'assigned_agent': loan_app.assigned_agent.name if loan_app.assigned_agent else None,
            'assigned_at': loan_app.assigned_at.isoformat() if loan_app.assigned_at else None,
            'hours_since_assignment': loan_app.hours_since_assignment,
            'requires_follow_up': loan_app.requires_follow_up,
            'is_follow_up': loan_app.is_follow_up,
            'follow_up_count': loan_app.follow_up_count,
            'follow_up_scheduled_at': loan_app.follow_up_scheduled_at.isoformat() if loan_app.follow_up_scheduled_at else None,
            'documents': list(documents),
            'applicant_phone': applicant.phone_number,
            'applicant_email': applicant.email,
        }
        
        return Response(data)
    
    except Applicant.DoesNotExist:
        return Response({'error': 'Applicant not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@login_required
def workflow_stats(request):
    """Get workflow statistics"""
    if request.user.role == 'admin':
        # Admin sees all stats
        stats = {
            'new_entry': LoanApplication.objects.filter(status='New Entry').count(),
            'waiting': LoanApplication.objects.filter(status='Waiting for Processing').count(),
            'follow_up': LoanApplication.objects.filter(status='Required Follow-up').count(),
            'approved': LoanApplication.objects.filter(status='Approved').count(),
            'rejected': LoanApplication.objects.filter(status='Rejected').count(),
            'total': LoanApplication.objects.count(),
            'requires_follow_up': LoanApplication.objects.filter(
                status='Waiting for Processing'
            ).count(),  # Will be calculated based on 4-hour rule
        }
    else:
        # Employees/Agents see only their assigned applications
        if request.user.role == 'employee':
            my_apps = LoanApplication.objects.filter(assigned_employee=request.user)
        else:
            agent = request.user.agent_profile
            my_apps = LoanApplication.objects.filter(assigned_agent=agent)
        
        stats = {
            'waiting': my_apps.filter(status='Waiting for Processing').count(),
            'follow_up': my_apps.filter(status='Required Follow-up').count(),
            'approved': my_apps.filter(status='Approved').count(),
            'rejected': my_apps.filter(status='Rejected').count(),
            'total': my_apps.count(),
        }
    
    return Response(stats)


@api_view(['POST'])
@login_required
def manual_trigger_follow_up(request, applicant_id):
    """Manually move to Banking Processing (admin/subadmin only)"""
    if request.user.role not in ['admin', 'subadmin']:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        
        if loan_app.status != 'Waiting for Processing':
            return Response({
                'error': f'Can only move Waiting applications to Banking Processing. Current status: {loan_app.status}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Trigger follow-up
        loan_app.trigger_follow_up()
        
        # Log activity
        ActivityLog.objects.create(
            action='follow_up_triggered_manual',
            description=f"Follow-up manually triggered for {applicant.full_name}",
            user=request.user,
        )
        
        return Response({
            'success': True,
            'message': 'Moved to Banking Processing successfully',
            'status': loan_app.status,
            'follow_up_count': loan_app.follow_up_count,
        })
    
    except Applicant.DoesNotExist:
        return Response({'error': 'Applicant not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@login_required
def change_application_status(request, applicant_id):
    """Change application status (admin only)"""
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        new_status = request.data.get('status')
        reason = request.data.get('reason', '')
        
        old_status = loan_app.status
        loan_app.status = new_status
        loan_app.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='status_changed',
            description=f"Status changed {old_status} â†’ {new_status} for {applicant.full_name}. Reason: {reason}",
            user=request.user,
        )
        
        return Response({
            'success': True,
            'message': f'Status changed from {old_status} to {new_status}',
            'status': loan_app.status,
        })
    
    except Applicant.DoesNotExist:
        return Response({'error': 'Applicant not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@login_required
def follow_up_details(request, applicant_id):
    """View details of a follow-up application (admin only)"""
    if request.user.role != 'admin':
        return redirect('admin_login')
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        documents = loan_app.documents.all()
        
        context = {
            'applicant': applicant,
            'loan_app': loan_app,
            'documents': documents,
            'follow_up_age_hours': (timezone.now() - loan_app.follow_up_scheduled_at).total_seconds() / 3600 if loan_app.follow_up_scheduled_at else 0,
            'waiting_age_hours': loan_app.hours_since_assignment,
        }
        
        return render(request, 'core/follow_up_details.html', context)
    
    except Applicant.DoesNotExist:
        messages.error(request, 'Application not found')
        return redirect('workflow_dashboard')
    except Exception as e:
        messages.error(request, str(e))
        return redirect('workflow_dashboard')


@login_required
def waiting_applications(request):
    """Admin view for all applications waiting for processing"""
    if request.user.role != 'admin':
        return redirect('admin_dashboard')
    
    applications = LoanApplication.objects.filter(
        status='Waiting for Processing'
    ).select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-assigned_at')
    
    # Add aging info
    waiting_with_age = []
    for app in applications:
        hours_waiting = app.hours_since_assignment
        requires_fu = app.requires_follow_up
        waiting_with_age.append({
            'app': app,
            'hours_since_assignment': hours_waiting,
            'requires_follow_up': requires_fu,
        })
    
    context = {
        'applications': waiting_with_age,
        'count': applications.count(),
    }
    
    return render(request, 'core/waiting_applications.html', context)


@login_required
def follow_up_applications(request):
    """Admin view for all applications requiring follow-up"""
    if request.user.role != 'admin':
        return redirect('admin_dashboard')
    
    applications = LoanApplication.objects.filter(
        status='Required Follow-up'
    ).select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-follow_up_scheduled_at')
    
    # Add follow-up info
    follow_ups_with_info = []
    for app in applications:
        follow_ups_with_info.append({
            'app': app,
            'follow_up_count': app.follow_up_count,
            'follow_up_age': (timezone.now() - app.follow_up_scheduled_at).total_seconds() / 3600 if app.follow_up_scheduled_at else 0,
        })
    
    context = {
        'applications': follow_ups_with_info,
        'count': applications.count(),
    }
    
    return render(request, 'core/follow_up_applications.html', context)


@api_view(['POST'])
@login_required
def reject_application(request, applicant_id):
    """Reject an application"""
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        
        # Only assigned employee or admin can reject
        if request.user.role == 'employee' and loan_app.assigned_employee != request.user:
            return Response({'error': 'Unauthorized - Not assigned to you'}, status=status.HTTP_403_FORBIDDEN)
        
        rejection_reason = request.data.get('rejection_reason', '')
        
        loan_app.status = 'Rejected'
        loan_app.rejected_by = request.user
        loan_app.rejection_reason = rejection_reason
        loan_app.rejected_at = timezone.now()
        loan_app.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='application_rejected',
            description=f"Application {applicant.full_name} rejected by {request.user.first_name}",
        )
        
        return Response({
            'success': True,
            'message': 'Application rejected successfully',
            'status': loan_app.status
        })
    
    except Applicant.DoesNotExist:
        return Response({'error': 'Applicant not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# Follow-up Management Views (Admin Only)
# ============================================================================

@login_required
def reassign_application(request, applicant_id):
    """
    Admin view to reassign an application to a different employee/agent.
    Redirects to a reassignment form.
    """
    if request.user.role != 'admin':
        messages.error(request, 'Only admins can reassign applications.')
        return redirect('admin_dashboard')
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        
        # GET: Show reassignment form
        if request.method == 'GET':
            employees = User.objects.filter(role='employee', is_active=True)
            agents = Agent.objects.filter(status='active')
            
            context = {
                'applicant': applicant,
                'loan_app': loan_app,
                'employees': employees,
                'agents': agents,
            }
            return render(request, 'admin/reassign_application.html', context)
        
        # POST: Process reassignment
        elif request.method == 'POST':
            assign_type = request.POST.get('assign_type')
            
            if assign_type == 'employee':
                employee_id = request.POST.get('employee_id')
                try:
                    employee = User.objects.get(id=employee_id, role='employee')
                    loan_app.assigned_employee = employee
                    loan_app.assigned_agent = None
                    loan_app.assigned_at = timezone.now()
                    loan_app.assigned_by = request.user
                    loan_app.save()
                    
                    messages.success(request, f'Application reassigned to {employee.first_name} {employee.last_name}.')
                    
                    # Log activity
                    ActivityLog.objects.create(
                        action='application_reassigned',
                        description=f"Application {applicant.full_name} reassigned to {employee.first_name} {employee.last_name}",
                    )
                except User.DoesNotExist:
                    messages.error(request, 'Selected employee not found.')
                    return redirect('reassign_application', applicant_id=applicant_id)
            
            elif assign_type == 'agent':
                agent_id = request.POST.get('agent_id')
                try:
                    agent = Agent.objects.get(id=agent_id, status='active')
                    loan_app.assigned_agent = agent
                    loan_app.assigned_employee = None
                    loan_app.assigned_at = timezone.now()
                    loan_app.assigned_by = request.user
                    loan_app.save()
                    
                    messages.success(request, f'Application reassigned to {agent.name}.')
                    
                    # Log activity
                    ActivityLog.objects.create(
                        action='application_reassigned',
                        description=f"Application {applicant.full_name} reassigned to {agent.name}",
                    )
                except Agent.DoesNotExist:
                    messages.error(request, 'Selected agent not found.')
                    return redirect('reassign_application', applicant_id=applicant_id)
            
            return redirect('view_followup_detail', applicant_id=applicant_id)
        
    except Applicant.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('workflow_dashboard')
    except Exception as e:
        messages.error(request, f'Error: {str(e)}')
        return redirect('workflow_dashboard')


@login_required
def send_follow_up_reminder(request, applicant_id):
    """
    Admin action to send follow-up reminder to assigned user.
    Can be used to manually trigger notifications.
    """
    if request.user.role != 'admin':
        return Response({'error': 'Only admins can send reminders'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        
        # Increment follow-up count
        loan_app.follow_up_count += 1
        loan_app.follow_up_notified_at = timezone.now()
        loan_app.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='follow_up_reminder_sent',
            description=f"Follow-up reminder sent for application {applicant.full_name} (Count: {loan_app.follow_up_count})",
            user=request.user
        )
        
        messages.success(request, 'Follow-up reminder sent successfully.')
        return redirect('view_followup_detail', applicant_id=applicant_id)
    
    except Applicant.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('workflow_dashboard')
    except Exception as e:
        messages.error(request, f'Error sending reminder: {str(e)}')
        return redirect('workflow_dashboard')

# ============ NEW API ENDPOINTS FOR REAL-TIME & DOCUMENT MANAGEMENT ============

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_loan_documents(request, loan_id):
    """
    API endpoint to get all documents for a specific loan with proper access control.
    - Admin: Can view all loan documents
    - Employee: Can only view documents for loans assigned to them
    - Agent: Can only view documents for loans assigned to their agent
    """
    user = request.user
    
    try:
        loan = Loan.objects.get(id=loan_id)
    except Loan.DoesNotExist:
        return Response({'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Check access permission
    if user.role == 'admin':
        pass  # Admin can access all
    elif user.role == 'employee':
        if loan.assigned_employee != user:
            return Response({'error': 'You do not have permission to access this loan'}, 
                          status=status.HTTP_403_FORBIDDEN)
    elif user.role == 'agent':
        try:
            agent = Agent.objects.get(user=user)
            if loan.assigned_agent != agent:
                return Response({'error': 'You do not have permission to access this loan'}, 
                              status=status.HTTP_403_FORBIDDEN)
        except Agent.DoesNotExist:
            return Response({'error': 'Agent profile not found'}, status=status.HTTP_403_FORBIDDEN)
    else:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    # Return documents with download URLs
    documents = loan.documents.all()
    documents_data = []
    for doc in documents:
        documents_data.append({
            'id': doc.id,
            'document_type': doc.document_type,
            'document_type_display': doc.get_document_type_display(),
            'file_name': doc.file.name.split('/')[-1] if doc.file else 'N/A',
            'uploaded_at': doc.uploaded_at.isoformat(),
            'is_required': doc.is_required,
            'download_url': request.build_absolute_uri(f'/api/loan-documents/{doc.id}/download/'),
        })
    
    return Response({
        'loan_id': loan_id,
        'loan_name': loan.full_name,
        'total_documents': len(documents_data),
        'documents': documents_data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_applicant_documents(request, applicant_id):
    """
    API endpoint to get all documents for a specific applicant/loan application.
    - Admin: Can view all applicant documents
    - Employee: Can only view documents for applications assigned to them
    - Agent: Can only view documents for applications assigned to their agent
    """
    user = request.user
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
    except Applicant.DoesNotExist:
        return Response({'error': 'Applicant not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Check access permission
    if user.role == 'admin':
        pass  # Admin can access all
    elif user.role == 'employee':
        if loan_app.assigned_employee != user:
            return Response({'error': 'You do not have permission to access this applicant'}, 
                          status=status.HTTP_403_FORBIDDEN)
    elif user.role == 'agent':
        try:
            agent = Agent.objects.get(user=user)
            if loan_app.assigned_agent != agent:
                return Response({'error': 'You do not have permission to access this applicant'}, 
                              status=status.HTTP_403_FORBIDDEN)
        except Agent.DoesNotExist:
            return Response({'error': 'Agent profile not found'}, status=status.HTTP_403_FORBIDDEN)
    else:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    # Return documents with download URLs
    documents = loan_app.documents.all()
    documents_data = []
    for doc in documents:
        documents_data.append({
            'id': doc.id,
            'document_type': doc.document_type,
            'document_type_display': doc.get_document_type_display(),
            'file_name': doc.file.name.split('/')[-1] if doc.file else 'N/A',
            'uploaded_at': doc.uploaded_at.isoformat(),
            'is_required': doc.is_required,
            'download_url': request.build_absolute_uri(f'/api/applicant-documents/{doc.id}/download/'),
        })
    
    return Response({
        'applicant_id': applicant_id,
        'applicant_name': applicant.full_name,
        'total_documents': len(documents_data),
        'documents': documents_data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_upload_case_document(request, loan_id):
    """
    Upload one or more documents for a case (LoanApplication or legacy Loan).

    Accepts multipart form-data:
    - document_name: string (required)
    - document_file: file (repeat field or use multiple)
    - source: optional ('application' | 'legacy')
    """
    raw_source = str(request.data.get('source') or request.data.get('entity_type') or '').strip().lower()
    requested_source = 'legacy' if raw_source in ['legacy', 'loan'] else ('application' if raw_source in ['application', 'app'] else '')

    raw_name = str(request.data.get('document_name') or request.data.get('document_type') or '').strip()
    if not raw_name:
        return Response({'success': False, 'error': 'Document name is required.'}, status=status.HTTP_400_BAD_REQUEST)

    files = request.FILES.getlist('document_file')
    if not files:
        files = request.FILES.getlist('document_file[]')
    if not files:
        files = request.FILES.getlist('files')
    if not files:
        files = request.FILES.getlist('file')
    if not files:
        single = request.FILES.get('document_file') or request.FILES.get('file')
        files = [single] if single else []
    files = [f for f in files if f]

    if not files:
        return Response({'success': False, 'error': 'Please choose a document file.'}, status=status.HTTP_400_BAD_REQUEST)

    base_type = ' '.join(raw_name.split())
    base_type = base_type[:50]

    def _is_docs_editable_application(app_obj):
        return str(getattr(app_obj, 'status', '')).strip() in ['New Entry', 'Waiting for Processing', 'Required Follow-up']

    def _is_docs_editable_legacy(loan_obj):
        return str(getattr(loan_obj, 'status', '')).strip() in ['draft', 'new_entry', 'waiting', 'follow_up']

    def _unique_type(cleaned, existing_qs):
        cleaned = str(cleaned or '').strip()[:50]
        candidate = cleaned
        suffix_index = 2
        while existing_qs.filter(document_type=candidate).exists():
            suffix = f" ({suffix_index})"
            candidate = f"{cleaned[:max(1, 50 - len(suffix))]}{suffix}"
            suffix_index += 1
        return candidate

    def _serialize(doc_obj, source_label):
        return {
            'id': doc_obj.id,
            'source': source_label,
            'document_type': doc_obj.document_type,
            'document_type_display': doc_obj.get_document_type_display(),
            'file_name': doc_obj.file.name.split('/')[-1] if getattr(doc_obj, 'file', None) else '',
            'file_url': doc_obj.file.url if getattr(doc_obj, 'file', None) else '',
            'download_url': doc_obj.file.url if getattr(doc_obj, 'file', None) else '',
            'uploaded_at': doc_obj.uploaded_at.strftime('%Y-%m-%d %H:%M') if getattr(doc_obj, 'uploaded_at', None) else '',
            'is_required': bool(getattr(doc_obj, 'is_required', False)),
        }

    # Prefer LoanApplication when present (unless explicitly requested legacy)
    loan_app = None
    legacy = None
    related_legacy = None
    related_app = None

    if requested_source != 'legacy':
        loan_app = LoanApplication.objects.filter(id=loan_id).select_related('assigned_employee', 'assigned_agent').first()

    if loan_app and requested_source == 'legacy':
        related_legacy = find_related_loan(loan_app)
        legacy = related_legacy

    if not loan_app and requested_source != 'application':
        legacy = Loan.objects.filter(id=loan_id).select_related('assigned_employee', 'assigned_agent').first()

    if loan_app and not legacy:
        related_legacy = find_related_loan(loan_app)
        if not _is_authorized_follow_up_editor(request.user, loan_app=loan_app, legacy_loan=related_legacy):
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        if not _is_docs_editable_application(loan_app):
            return Response({'success': False, 'error': 'Documents can be uploaded only in New/Document Pending/Banking Processing.'}, status=status.HTTP_400_BAD_REQUEST)

        existing_qs = ApplicantDocument.objects.filter(loan_application=loan_app)
        created_docs = []
        for idx, uploaded_file in enumerate(files):
            if idx == 0 and existing_qs.filter(document_type=base_type).exists():
                doc_obj = existing_qs.filter(document_type=base_type).first()
                doc_obj.file = uploaded_file
                doc_obj.is_required = False
                doc_obj.save(update_fields=['file', 'is_required'])
            else:
                doc_type = _unique_type(base_type, existing_qs)
                doc_obj = ApplicantDocument.objects.create(
                    loan_application=loan_app,
                    document_type=doc_type,
                    file=uploaded_file,
                    is_required=False,
                )
            created_docs.append(_serialize(doc_obj, 'application'))
        return Response({'success': True, 'documents': created_docs}, status=status.HTTP_200_OK)

    if legacy:
        related_app = find_related_loan_application(legacy)
        if not _is_authorized_follow_up_editor(request.user, loan_app=related_app, legacy_loan=legacy):
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        if not _is_docs_editable_legacy(legacy):
            return Response({'success': False, 'error': 'Documents can be uploaded only in New/Document Pending/Banking Processing.'}, status=status.HTTP_400_BAD_REQUEST)

        existing_qs = LoanDocument.objects.filter(loan=legacy)
        created_docs = []
        for idx, uploaded_file in enumerate(files):
            if idx == 0 and existing_qs.filter(document_type=base_type).exists():
                doc_obj = existing_qs.filter(document_type=base_type).first()
                doc_obj.file = uploaded_file
                doc_obj.is_required = False
                doc_obj.save(update_fields=['file', 'is_required', 'updated_at'])
            else:
                doc_type = _unique_type(base_type, existing_qs)
                doc_obj = LoanDocument.objects.create(
                    loan=legacy,
                    document_type=doc_type,
                    file=uploaded_file,
                    is_required=False,
                )
            created_docs.append(_serialize(doc_obj, 'legacy'))
        return Response({'success': True, 'documents': created_docs}, status=status.HTTP_200_OK)

    return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_delete_case_document(request, loan_id, document_id):
    """
    Delete a document from a case (LoanApplication or legacy Loan).

    Accepts:
    - source: optional ('application' | 'legacy') to disambiguate document tables.
    """
    raw_source = str(request.data.get('source') or request.data.get('entity_type') or '').strip().lower()
    requested_source = 'legacy' if raw_source in ['legacy', 'loan'] else ('application' if raw_source in ['application', 'app'] else '')

    def _is_docs_editable_application(app_obj):
        return str(getattr(app_obj, 'status', '')).strip() in ['New Entry', 'Waiting for Processing', 'Required Follow-up']

    def _is_docs_editable_legacy(loan_obj):
        return str(getattr(loan_obj, 'status', '')).strip() in ['draft', 'new_entry', 'waiting', 'follow_up']

    loan_app = LoanApplication.objects.filter(id=loan_id).select_related('assigned_employee', 'assigned_agent').first()
    if loan_app:
        related_legacy = find_related_loan(loan_app)
        if not _is_authorized_follow_up_editor(request.user, loan_app=loan_app, legacy_loan=related_legacy):
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        if not _is_docs_editable_application(loan_app):
            return Response({'success': False, 'error': 'Documents can be deleted only in New/Document Pending/Banking Processing.'}, status=status.HTTP_400_BAD_REQUEST)

        deleted = 0
        if requested_source in ['', 'application']:
            deleted, _ = ApplicantDocument.objects.filter(id=document_id, loan_application=loan_app).delete()
            if deleted:
                return Response({'success': True}, status=status.HTTP_200_OK)

        if requested_source in ['', 'legacy'] and related_legacy:
            deleted, _ = LoanDocument.objects.filter(id=document_id, loan=related_legacy).delete()
            if deleted:
                return Response({'success': True}, status=status.HTTP_200_OK)

        return Response({'success': False, 'error': 'Document not found'}, status=status.HTTP_404_NOT_FOUND)

    legacy = Loan.objects.filter(id=loan_id).select_related('assigned_employee', 'assigned_agent').first()
    if legacy:
        related_app = find_related_loan_application(legacy)
        if not _is_authorized_follow_up_editor(request.user, loan_app=related_app, legacy_loan=legacy):
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        if not _is_docs_editable_legacy(legacy):
            return Response({'success': False, 'error': 'Documents can be deleted only in New/Document Pending/Banking Processing.'}, status=status.HTTP_400_BAD_REQUEST)

        deleted = 0
        if requested_source in ['', 'legacy']:
            deleted, _ = LoanDocument.objects.filter(id=document_id, loan=legacy).delete()
            if deleted:
                return Response({'success': True}, status=status.HTTP_200_OK)

        if requested_source in ['', 'application'] and related_app:
            deleted, _ = ApplicantDocument.objects.filter(id=document_id, loan_application=related_app).delete()
            if deleted:
                return Response({'success': True}, status=status.HTTP_200_OK)

        return Response({'success': False, 'error': 'Document not found'}, status=status.HTTP_404_NOT_FOUND)

    return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_my_assignments(request):
    """
    Get all applications assigned to current user (Employee/Agent).
    Real-time API endpoint for monitoring assignments.
    Returns:
    - For Employee: All applications assigned to them
    - For Agent: All applications assigned to their agent profile
    - For Admin: All applications with status breakdown
    """
    user = request.user
    
    if user.role == 'employee':
        assignments = LoanApplication.objects.filter(
            assigned_employee=user
        ).select_related('applicant').order_by('-assigned_at')
    
    elif user.role == 'agent':
        try:
            agent = Agent.objects.get(user=user)
            assignments = LoanApplication.objects.filter(
                assigned_agent=agent
            ).select_related('applicant').order_by('-assigned_at')
        except Agent.DoesNotExist:
            return Response({'error': 'Agent profile not found'}, status=status.HTTP_403_FORBIDDEN)
    
    elif user.role == 'admin':
        # Admin gets all assignments
        assignments = LoanApplication.objects.all().select_related('applicant').order_by('-assigned_at')
    
    else:
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    # Build response data
    assignments_data = []
    for app in assignments:
        assignments_data.append({
            'id': app.id,
            'applicant_id': app.applicant.id,
            'applicant_name': app.applicant.full_name,
            'applicant_phone': app.applicant.mobile,
            'loan_type': app.applicant.loan_type,
            'loan_amount': float(app.applicant.loan_amount) if app.applicant.loan_amount else 0,
            'status': app.status,
            'assigned_to': app.assigned_employee.get_full_name() if app.assigned_employee else (app.assigned_agent.name if app.assigned_agent else 'Unassigned'),
            'assigned_at': app.assigned_at.isoformat() if app.assigned_at else None,
            'hours_since_assignment': app.hours_since_assignment if app.hours_since_assignment else 0,
            'requires_follow_up': app.requires_follow_up,
            'is_overdue': app.hours_since_assignment > 4 if app.hours_since_assignment else False,
            'documents_count': app.documents.count(),
            'follow_up_count': app.follow_up_count,
        })
    
    # Status breakdown
    status_breakdown = {}
    for status_choice in LoanApplication.STATUS_CHOICES:
        status_key = status_choice[0]
        status_breakdown[status_key] = assignments.filter(status=status_key).count()
    
    return Response({
        'total_assignments': len(assignments_data),
        'waiting_count': assignments.filter(status='Waiting for Processing').count(),
        'follow_up_count': assignments.filter(status='Required Follow-up').count(),
        'overdue_count': sum(1 for a in assignments_data if a['is_overdue']),
        'status_breakdown': status_breakdown,
        'assignments': assignments_data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_update_application_status(request):
    """
    Update application status (for Processing screen).
    Real-time update endpoint.
    
    Expected POST data:
    {
        'applicant_id': int,
        'status': 'Approved' | 'Rejected' | 'Waiting for Processing',
        'notes': 'optional notes'
    }
    """
    user = request.user
    
    # Only employees and agents can update status
    if user.role not in ['employee', 'agent']:
        return Response({'error': 'Only employees and agents can update status'}, 
                      status=status.HTTP_403_FORBIDDEN)
    
    applicant_id = request.data.get('applicant_id')
    new_status = request.data.get('status')
    notes = request.data.get('notes', '')
    
    if not applicant_id or not new_status:
        return Response({'error': 'applicant_id and status are required'}, 
                      status=status.HTTP_400_BAD_REQUEST)
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
    except Applicant.DoesNotExist:
        return Response({'error': 'Applicant not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Check permission
    if user.role == 'employee':
        if loan_app.assigned_employee != user:
            return Response({'error': 'You do not have permission to update this application'}, 
                          status=status.HTTP_403_FORBIDDEN)
    elif user.role == 'agent':
        try:
            agent = Agent.objects.get(user=user)
            if loan_app.assigned_agent != agent:
                return Response({'error': 'You do not have permission to update this application'}, 
                              status=status.HTTP_403_FORBIDDEN)
        except Agent.DoesNotExist:
            return Response({'error': 'Agent profile not found'}, status=status.HTTP_403_FORBIDDEN)
    
    # Update status
    old_status = loan_app.status
    loan_app.status = new_status
    
    if new_status == 'Approved':
        loan_app.approved_by = user
        loan_app.approved_at = timezone.now()
        loan_app.approval_notes = notes
    elif new_status == 'Rejected':
        loan_app.rejected_by = user
        loan_app.rejected_at = timezone.now()
        loan_app.rejection_reason = notes
    
    loan_app.save()
    
    # Log activity
    ActivityLog.objects.create(
        action='status_updated',
        description=f"Application {applicant.full_name} status changed from {old_status} to {new_status}",
        user=user
    )
    
    return Response({
        'success': True,
        'message': f'Application status updated to {new_status}',
        'applicant_id': applicant_id,
        'new_status': new_status,
        'old_status': old_status,
        'updated_at': timezone.now().isoformat(),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_assign_application(request):
    """
    Admin endpoint to assign an application to Employee or Agent.
    Real-time assignment update.
    
    Expected POST data:
    {
        'applicant_id': int,
        'assign_type': 'employee' | 'agent',
        'assign_to_id': int (user_id for employee, agent_id for agent)
    }
    """
    user = request.user
    
    # Only admin can assign
    if user.role != 'admin':
        return Response({'error': 'Only admins can assign applications'}, 
                      status=status.HTTP_403_FORBIDDEN)
    
    applicant_id = request.data.get('applicant_id')
    assign_type = request.data.get('assign_type')
    assign_to_id = request.data.get('assign_to_id')
    
    if not all([applicant_id, assign_type, assign_to_id]):
        return Response({'error': 'applicant_id, assign_type, and assign_to_id are required'}, 
                      status=status.HTTP_400_BAD_REQUEST)
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
    except Applicant.DoesNotExist:
        return Response({'error': 'Applicant not found'}, status=status.HTTP_404_NOT_FOUND)
    
    try:
        if assign_type == 'employee':
            employee = User.objects.get(id=assign_to_id, role='employee')
            loan_app.assigned_employee = employee
            loan_app.assigned_agent = None
            assigned_to_name = employee.get_full_name()
        elif assign_type == 'agent':
            agent = Agent.objects.get(id=assign_to_id)
            loan_app.assigned_agent = agent
            loan_app.assigned_employee = None
            assigned_to_name = agent.name
        else:
            return Response({'error': 'Invalid assign_type'}, status=status.HTTP_400_BAD_REQUEST)
        
        loan_app.assigned_at = timezone.now()
        loan_app.assigned_by = user
        loan_app.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='application_assigned',
            description=f"Application {applicant.full_name} assigned to {assigned_to_name}",
            user=user
        )
        
        return Response({
            'success': True,
            'message': f'Application assigned to {assigned_to_name}',
            'applicant_id': applicant_id,
            'assigned_to': assigned_to_name,
            'assigned_at': loan_app.assigned_at.isoformat(),
        })
    
    except (User.DoesNotExist, Agent.DoesNotExist):
        return Response({'error': f'{assign_type.capitalize()} not found'}, 
                      status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============ AGENT DASHBOARD APIS ============

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_agent_profile(request):
    """Get agent profile information"""
    if request.user.role != 'agent':
        return Response({'error': 'Not authorized'}, status=403)
    
    try:
        agent = Agent.objects.get(user=request.user)
        data = {
            'user': {
                'username': request.user.username,
                'first_name': request.user.first_name,
                'last_name': request.user.last_name,
                'email': request.user.email,
                'phone': request.user.phone,
            },
            'status': agent.status,
            'loans_count': LoanApplication.objects.filter(assigned_agent=agent).count()
        }
        return Response(data)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=404)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_agent_dashboard_stats(request):
    """Get agent dashboard statistics"""
    if request.user.role != 'agent':
        return Response({'error': 'Not authorized'}, status=403)
    
    try:
        agent = Agent.objects.get(user=request.user)
        loans = LoanApplication.objects.filter(assigned_agent=agent)
        
        stats = {
            'total_assigned': loans.count(),
            'processing': loans.filter(status='waiting_for_processing').count(),
            'approved': loans.filter(status='approved').count(),
            'rejected': loans.filter(status='rejected').count(),
            'disbursed': loans.filter(status='disbursed').count(),
        }
        return Response(stats)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=404)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_agent_status_chart(request):
    """Get agent status distribution chart data"""
    if request.user.role != 'agent':
        return Response({'error': 'Not authorized'}, status=403)
    
    try:
        agent = Agent.objects.get(user=request.user)
        loans = LoanApplication.objects.filter(assigned_agent=agent)
        
        data = {
            'labels': ['Processing', 'Approved', 'Rejected', 'Disbursed'],
            'values': [
                loans.filter(status='waiting_for_processing').count(),
                loans.filter(status='approved').count(),
                loans.filter(status='rejected').count(),
                loans.filter(status='disbursed').count(),
            ]
        }
        return Response(data)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=404)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_agent_trend_chart(request):
    """Get agent 30-day trend chart data"""
    if request.user.role != 'agent':
        return Response({'error': 'Not authorized'}, status=403)
    
    from datetime import timedelta, datetime
    
    try:
        agent = Agent.objects.get(user=request.user)
        loans = LoanApplication.objects.filter(assigned_agent=agent)
        
        # Generate last 30 days data
        labels = []
        values = []
        
        for i in range(29, -1, -1):
            date = datetime.now() - timedelta(days=i)
            date_str = date.strftime('%m-%d')
            count = loans.filter(created_at__date=date.date()).count()
            labels.append(date_str)
            values.append(count)
        
        data = {
            'labels': labels,
            'values': values
        }
        return Response(data)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=404)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_assigned_loans(request):
    """Get agent's assigned loans (paginated)"""
    if request.user.role not in ['agent', 'employee']:
        return Response({'error': 'Not authorized'}, status=403)
    
    from django.core.paginator import Paginator
    
    try:
        if request.user.role == 'agent':
            agent = Agent.objects.get(user=request.user)
            loans = LoanApplication.objects.filter(assigned_agent=agent).order_by('-created_at')
        else:
            # Employee
            loans = LoanApplication.objects.filter(assigned_employee=request.user).order_by('-created_at')
        
        # Pagination
        paginator = Paginator(loans, 10)
        page = request.GET.get('page', 1)
        loans_page = paginator.get_page(page)
        
        data = {
            'count': paginator.count,
            'results': [
                {
                    'id': loan.id,
                    'applicant_name': f"{loan.applicant.first_name} {loan.applicant.last_name}" if loan.applicant else 'N/A',
                    'loan_amount': str(loan.loan_amount),
                    'status': loan.status,
                    'created_at': loan.created_at.isoformat() if loan.created_at else None,
                }
                for loan in loans_page
            ]
        }
        return Response(data)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=404)


# ============ EMPLOYEE DASHBOARD APIS ============

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_dashboard(request):
    """Employee dashboard - only for employees"""
    if request.user.role != 'employee':
        messages.error(request, 'Only employees can access this page.')
        return redirect('dashboard')
    return render(request, 'core/employee/dashboard.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_dashboard_stats(request):
    """
    Get employee dashboard statistics - Real-time data
    Only accessible by employee users
    Returns count of loans assigned to current employee by status
    """
    try:
        if request.user.role != 'employee':
            return Response({
                'success': False,
                'role_mismatch': True,
                'message': 'Employee context not active',
                'total_assigned': 0,
                'total_loans': 0,
                'new_entry': 0,
                'waiting': 0,
                'processing': 0,
                'in_processing': 0,
                'approved': 0,
                'rejected': 0,
                'follow_up': 0,
                'follow_up_pending': 0,
                'banking_process': 0,
                'disbursed': 0,
            }, status=status.HTTP_200_OK)

        auto_move_overdue_to_follow_up()

        follow_up_pending_marker = 'revert remark '

        def _app_is_follow_up_pending(app_obj):
            if not app_obj or app_obj.status not in ['New Entry', 'Waiting for Processing']:
                return False
            return follow_up_pending_marker in str(app_obj.approval_notes or '').lower()

        def _legacy_is_follow_up_pending(loan_obj):
            if not loan_obj or loan_obj.status not in ['new_entry', 'waiting']:
                return False
            if follow_up_pending_marker in str(loan_obj.remarks or '').lower():
                return True
            return _app_is_follow_up_pending(find_related_loan_application(loan_obj))

        # Primary source: legacy Loan table (used across employee panel APIs/templates).
        legacy_assignments = list(Loan.objects.filter(assigned_employee=request.user))

        if legacy_assignments:
            related_app_ids = set()
            for legacy in legacy_assignments:
                related_app = find_related_loan_application(legacy)
                if related_app:
                    related_app_ids.add(related_app.id)

            # Add workflow-only records not mapped to a legacy loan yet.
            workflow_only_assignments = list(
                LoanApplication.objects.filter(assigned_employee=request.user).exclude(id__in=related_app_ids)
            )

            legacy_new_entry = sum(
                1 for loan in legacy_assignments
                if loan.status == 'new_entry' and not _legacy_is_follow_up_pending(loan)
            )
            legacy_waiting = sum(
                1 for loan in legacy_assignments
                if loan.status == 'waiting' and not _legacy_is_follow_up_pending(loan)
            )
            legacy_banking = sum(1 for loan in legacy_assignments if loan.status == 'follow_up')
            legacy_follow_up_pending = sum(1 for loan in legacy_assignments if _legacy_is_follow_up_pending(loan))
            legacy_approved = sum(1 for loan in legacy_assignments if loan.status == 'approved')
            legacy_rejected = sum(1 for loan in legacy_assignments if loan.status == 'rejected')
            legacy_disbursed = sum(1 for loan in legacy_assignments if loan.status == 'disbursed')

            workflow_new_entry = sum(
                1 for app in workflow_only_assignments
                if app.status == 'New Entry' and not _app_is_follow_up_pending(app)
            )
            workflow_waiting = sum(
                1 for app in workflow_only_assignments
                if app.status == 'Waiting for Processing' and not _app_is_follow_up_pending(app)
            )
            workflow_banking = sum(1 for app in workflow_only_assignments if app.status == BANKING_PROCESS_STATUS)
            workflow_follow_up_pending = sum(1 for app in workflow_only_assignments if _app_is_follow_up_pending(app))
            workflow_approved = sum(1 for app in workflow_only_assignments if app.status == 'Approved')
            workflow_rejected = sum(1 for app in workflow_only_assignments if app.status == 'Rejected')
            workflow_disbursed = sum(1 for app in workflow_only_assignments if app.status == 'Disbursed')

            new_entry_count = legacy_new_entry + workflow_new_entry
            waiting_count = legacy_waiting + workflow_waiting
            banking_count = legacy_banking + workflow_banking
            follow_up_pending_count = legacy_follow_up_pending + workflow_follow_up_pending
            approved_count = legacy_approved + workflow_approved
            rejected_count = legacy_rejected + workflow_rejected
            disbursed_count = legacy_disbursed + workflow_disbursed
            total_assigned = len(legacy_assignments) + len(workflow_only_assignments)

            stats = {
                'success': True,
                'total_assigned': total_assigned,
                'total_loans': total_assigned,
                'new_entry': new_entry_count,
                'waiting': waiting_count,
                'processing': waiting_count,
                'in_processing': waiting_count + banking_count,
                'approved': approved_count,
                'rejected': rejected_count,
                'follow_up': banking_count,
                'follow_up_pending': follow_up_pending_count,
                'banking_process': banking_count,
                'disbursed': disbursed_count,
            }
        else:
            assignments = LoanApplication.objects.filter(assigned_employee=request.user)
            follow_up_pending_count = sum(1 for app in assignments if _app_is_follow_up_pending(app))
            new_entry_count = sum(
                1 for app in assignments
                if app.status == 'New Entry' and not _app_is_follow_up_pending(app)
            )
            waiting_count = sum(
                1 for app in assignments
                if app.status == 'Waiting for Processing' and not _app_is_follow_up_pending(app)
            )
            banking_count = assignments.filter(status=BANKING_PROCESS_STATUS).count()
            stats = {
                'success': True,
                'total_assigned': assignments.count(),
                'total_loans': assignments.count(),
                'new_entry': new_entry_count,
                'waiting': waiting_count,
                'processing': waiting_count,
                'in_processing': waiting_count + banking_count,
                'approved': assignments.filter(status='Approved').count(),
                'rejected': assignments.filter(status='Rejected').count(),
                'follow_up': banking_count,
                'follow_up_pending': follow_up_pending_count,
                'banking_process': banking_count,
                'disbursed': assignments.filter(status='Disbursed').count(),
            }
        return Response(stats, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e), 'success': False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsEmployeeUser])
def employee_assigned_loans(request):
    """
    Get all loans assigned to employee - Real-time table data
    Only accessible by employee users
    Returns only loans assigned to the current employee
    """
    try:
        # Get all applications assigned to this employee
        loans = LoanApplication.objects.filter(
            assigned_employee=request.user
        ).select_related('applicant').order_by('-assigned_at')
        
        loans_data = []
        for loan in loans:
            applicant = loan.applicant
            loans_data.append({
                'applicant_id': applicant.id,
                'applicant_name': applicant.full_name,
                'mobile': applicant.mobile,
                'loan_type': applicant.loan_type or 'N/A',
                'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                'status': loan.status,
                'assigned_date': loan.assigned_at.strftime('%Y-%m-%d') if loan.assigned_at else 'N/A',
                'applicant_photo': applicant.photo_url if hasattr(applicant, 'photo_url') else '/static/images/default-avatar.png',
                'hours_since_assignment': loan.hours_since_assignment if loan.hours_since_assignment else 0,
            })
        
        return Response({
            'success': True,
            'total': len(loans_data),
            'loans': loans_data
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e), 'success': False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@login_required
def employee_profile(request):
    """Employee profile page"""
    if request.user.role != 'employee':
        return redirect('dashboard')
    return render(request, 'core/employee/profile.html')


@login_required
def employee_settings(request):
    """Employee settings page"""
    if request.user.role != 'employee':
        return redirect('dashboard')
    return render(request, 'core/employee/settings.html')


@api_view(['GET'])
@login_required
def api_admin_new_entries(request):
    """API endpoint to get new loan entries for admin dashboard
    Uses the Loan model (not LoanApplication)
    """
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=403)
    
    try:
        # Get new loan entries from the Loan table
        # Filter by status 'new_entry' and created in last 7 days
        from datetime import timedelta
        from django.utils import timezone
        
        seven_days_ago = timezone.now() - timedelta(days=7)
        new_entries = Loan.objects.filter(
            status='new_entry',
            created_at__gte=seven_days_ago
        ).select_related('assigned_employee', 'assigned_agent').order_by('-created_at')[:50]
        
        data = []
        for loan in new_entries:
            assigned_to = None
            if loan.assigned_employee:
                assigned_to = {
                    'id': loan.assigned_employee.id,
                    'first_name': loan.assigned_employee.first_name,
                    'last_name': loan.assigned_employee.last_name,
                    'email': loan.assigned_employee.email,
                }
            elif loan.assigned_agent:
                assigned_to = {
                    'id': loan.assigned_agent.id,
                    'first_name': loan.assigned_agent.agent_name if hasattr(loan.assigned_agent, 'agent_name') else loan.assigned_agent.first_name,
                    'last_name': loan.assigned_agent.last_name if hasattr(loan.assigned_agent, 'last_name') else '',
                    'email': loan.assigned_agent.email if hasattr(loan.assigned_agent, 'email') else '',
                }
            
            data.append({
                'id': loan.id,
                'applicant': {
                    'full_name': loan.full_name,
                    'mobile': loan.mobile_number,
                    'email': loan.email,
                    'photo': None
                },
                'loan_type': loan.loan_type,
                'loan_amount': float(loan.loan_amount) if loan.loan_amount else 0,
                'status': loan.status,
                'created_at': loan.created_at.isoformat(),
                'assigned_to': assigned_to,
            })
        
        return Response({
            'count': len(data),
            'new_entries': data,
            'results': data
        })
    except Exception as e:
        import traceback
        return Response({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


@login_required
def comprehensive_loan_form(request):
    """Comprehensive Loan Application Form - Banking Grade
    Accessible to Admin, Agent, and Employee roles
    Professional step-wise form with all 6 sections
    """
    # Check authentication
    if not request.user.is_authenticated:
        return redirect('login')
    
    # Allow only authorized users
    if request.user.role not in ['admin', 'agent', 'employee']:
        messages.error(request, 'âŒ You do not have permission to access this form.')
        return redirect('dashboard')
    
    # GET request - show form
    if request.method == 'GET':
        return render(request, 'core/loan_form_complete.html')
    
    # POST request - this should be handled by API endpoint
    # The JavaScript form submits to /api/loans/ endpoint
    return render(request, 'core/loan_form_complete.html')


def loan_detail(request, loan_id):
    """Display detailed view of a loan application with all information"""
    # Check authentication
    if not request.user.is_authenticated:
        return redirect('login')
    
    try:
        # Try to get LoanApplication first
        try:
            from core.models import LoanApplication, Applicant
            loan = LoanApplication.objects.select_related('applicant').get(id=loan_id)
        except:
            # Try to get from Applicant model
            from core.models import Applicant
            loan = Applicant.objects.get(id=loan_id)
        
        # Check permissions - admin can view all, agent/employee can only view their own
        if request.user.role not in ['admin']:
            if request.user.role == 'agent' and loan.created_by != request.user:
                messages.error(request, 'âŒ You do not have permission to view this loan.')
                return redirect('dashboard')
            elif request.user.role == 'employee' and loan.assigned_to != request.user:
                messages.error(request, 'âŒ You do not have permission to view this loan.')
                return redirect('dashboard')
        
        return render(request, 'core/loan_detail.html', {'loan': loan})
    
    except Exception as e:
        messages.error(request, f'âŒ Loan not found: {str(e)}')
        return redirect('dashboard')


# ============ ADMIN PROFILE & SETTINGS API ENDPOINTS ============

@login_required
def admin_profile(request):
    """Admin profile page"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    return render(request, 'core/admin/profile.html')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_update_admin_profile(request):
    """API endpoint to update admin profile"""
    if request.user.role != 'admin':
        return Response({'error': 'Not authorized'}, status=403)
    
    try:
        user = request.user
        
        # Update profile fields
        user.first_name = request.data.get('first_name', user.first_name)
        user.last_name = request.data.get('last_name', user.last_name)
        user.phone = request.data.get('phone', user.phone)
        user.address = request.data.get('address', user.address)
        
        user.save()
        
        return Response({
            'success': True,
            'message': 'Profile updated successfully',
            'user': {
                'id': user.id,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'phone': user.phone,
                'address': user.address,
            }
        })
    except Exception as e:
        return Response({'error': str(e)}, status=400)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_change_password(request):
    """API endpoint to change admin password"""
    if request.user.role != 'admin':
        return Response({'error': 'Not authorized'}, status=403)
    
    try:
        user = request.user
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')
        confirm_password = request.data.get('confirm_password')
        
        # Validate current password
        if not user.check_password(current_password):
            return Response({'error': 'Current password is incorrect'}, status=400)
        
        # Check password match
        if new_password != confirm_password:
            return Response({'error': 'New passwords do not match'}, status=400)
        
        # Check password strength
        if len(new_password) < 8:
            return Response({'error': 'Password must be at least 8 characters long'}, status=400)
        
        # Set new password
        user.set_password(new_password)
        user.save()
        
        return Response({
            'success': True,
            'message': 'Password changed successfully'
        })
    except Exception as e:
        return Response({'error': str(e)}, status=400)


@login_required
def admin_processing_requests(request):
    """Admin view for processing requests"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    return render(request, 'core/admin/processing_requests.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_admin_processing_requests(request):
    """API endpoint to get processing requests for admin"""
    if request.user.role != 'admin':
        return Response({'error': 'Not authorized'}, status=403)
    
    try:
        # Get all loan applications
        requests_list = LoanApplication.objects.select_related(
            'applicant', 'assigned_employee', 'assigned_agent'
        ).order_by('-assigned_at')
        
        # Apply filters
        status_filter = request.GET.get('status')
        employee_filter = request.GET.get('employee')
        search_filter = request.GET.get('search')
        
        if status_filter:
            requests_list = requests_list.filter(status=status_filter)
        if employee_filter:
            requests_list = requests_list.filter(assigned_employee_id=employee_filter)
        if search_filter:
            requests_list = requests_list.filter(
                applicant__full_name__icontains=search_filter
            )
        
        # Build response data
        requests_data = []
        for req in requests_list:
            applicant = req.applicant
            requests_data.append({
                'id': req.id,
                'applicant_name': applicant.full_name,
                'applicant_mobile': applicant.mobile,
                'applicant_photo': '/static/images/default-avatar.png',
                'loan_type': applicant.loan_type,
                'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                'assigned_employee_name': req.assigned_employee.get_full_name() if req.assigned_employee else (req.assigned_agent.name if req.assigned_agent else 'Unassigned'),
                'status': req.status,
                'assigned_date': req.assigned_at.isoformat() if req.assigned_at else None,
            })
        
        # Get all employees for filter dropdown
        employees = User.objects.filter(role='employee', is_active=True).values('id', 'first_name', 'last_name')
        employees_list = [
            {'id': emp['id'], 'full_name': f"{emp['first_name']} {emp['last_name']}"} 
            for emp in employees
        ]
        
        # Calculate stats
        stats = {
            'total': requests_list.count(),
            'processing': requests_list.filter(status='Processing').count(),
            'approved': requests_list.filter(status='Approved').count(),
            'rejected': requests_list.filter(status='Rejected').count(),
        }
        
        return Response({
            'success': True,
            'requests': requests_data,
            'employees': employees_list,
            'stats': stats,
        })
    except Exception as e:
        return Response({'error': str(e)}, status=500)


# ============================================================
# NEW LOAN MANAGEMENT SYSTEM VIEWS
# ============================================================

# Admin Views

@admin_required
def loan_entries_view(request):
    """Unified New Entries Page - for both dashboard and sidebar"""
    return render(request, 'core/admin/loan_entries.html', {
        'page_title': 'New Loan Entries'
    })


@admin_required
def loan_waiting_view(request):
    """Waiting for Processing - Assigned loans"""
    return render(request, 'core/admin/loan_waiting.html', {
        'page_title': 'Document Pending'
    })


@admin_required
def loan_followup_view(request):
    """Required Follow-up - Loans with 4h+ no action"""
    return render(request, 'core/admin/loan_followup.html', {
        'page_title': 'Required Follow-up'
    })


@admin_required
def loan_approved_view(request):
    """Approved Loans"""
    return render(request, 'core/admin/loan_approved.html', {
        'page_title': 'Approved Loans'
    })


@admin_required
def loan_rejected_view(request):
    """Rejected Loans"""
    return render(request, 'core/admin/loan_rejected.html', {
        'page_title': 'Rejected Loans'
    })


@admin_required
def loan_disbursed_view(request):
    """Disbursed Loans"""
    return render(request, 'core/admin/loan_disbursed.html', {
        'page_title': 'Disbursed Loans'
    })


@admin_required
def loan_details_view(request):
    """Central loan database - All loans"""
    return render(request, 'core/admin/loan_details.html', {
        'page_title': 'Loan Details - Database'
    })


@admin_required
def loan_application_detail(request, loan_id):
    """Dedicated Loan Application Details Page"""
    try:
        loan = LoanApplication.objects.select_related(
            'applicant', 'assigned_employee', 'assigned_agent'
        ).get(id=loan_id)
        
        # Get all employees for assignment dropdown
        employees = User.objects.filter(role='employee', is_active=True).order_by('first_name')
        
        # Get status history
        status_history = LoanStatusHistory.objects.filter(
            loan_application=loan
        ).select_related('changed_by').order_by('-changed_at')
        
        # Get documents
        documents = ApplicantDocument.objects.filter(loan_application=loan)
        
        context = {
            'loan': loan,
            'applicant': loan.applicant,
            'employees': employees,
            'status_history': status_history,
            'documents': documents,
            'page_title': f'Loan Details - {loan.applicant.full_name}',
        }
        return render(request, 'core/admin/loan_application_detail.html', context)
    except LoanApplication.DoesNotExist:
        messages.error(request, 'Loan not found!')
        return redirect('loan_entries')


# ============================================================
# REST API ENDPOINTS FOR LOAN MANAGEMENT
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_loan_entries(request):
    """Get new entries for admin dashboard"""
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=403)
    
    loans = LoanApplication.objects.filter(
        status='New Entry'
    ).select_related('applicant', 'assigned_agent').order_by('-created_at')
    
    # Pagination
    page = int(request.GET.get('page', 1))
    limit = int(request.GET.get('limit', 10))
    start = (page - 1) * limit
    end = start + limit
    
    loans_data = [{
        'id': loan.id,
        'applicant_name': loan.applicant.full_name,
        'loan_type': loan.applicant.loan_type,
        'loan_amount': str(loan.applicant.loan_amount),
        'submitted_by': loan.assigned_agent.name if loan.assigned_agent else 'Unknown',
        'submission_date': loan.created_at.isoformat(),
        'status': loan.status,
        'assigned_employee': loan.assigned_employee.get_full_name() if loan.assigned_employee else None,
    } for loan in loans[start:end]]
    
    return Response({
        'count': loans.count(),
        'page': page,
        'limit': limit,
        'results': loans_data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_loan_status_list(request, status):
    """Get loans by status"""
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=403)
    
    # Map URL status to model status
    status_mapping = {
        'new': 'New Entry',
        'waiting': 'Waiting for Processing',
        'followup': 'Required Follow-up',
        'approved': 'Approved',
        'rejected': 'Rejected',
        'disbursed': 'Disbursed',
    }
    
    model_status = status_mapping.get(status)
    if not model_status:
        return Response({'error': 'Invalid status'}, status=400)
    
    loans = LoanApplication.objects.filter(
        status=model_status
    ).select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    # Pagination
    page = int(request.GET.get('page', 1))
    limit = int(request.GET.get('limit', 10))
    start = (page - 1) * limit
    end = start + limit
    
    loans_data = [{
        'id': loan.id,
        'applicant_name': loan.applicant.full_name,
        'applicant_phone': loan.applicant.mobile,
        'loan_type': loan.applicant.loan_type,
        'loan_amount': str(loan.applicant.loan_amount),
        'assigned_employee': loan.assigned_employee.get_full_name() if loan.assigned_employee else 'Unassigned',
        'submission_date': loan.created_at.isoformat(),
        'hours_pending': int((timezone.now() - loan.assigned_at).total_seconds() / 3600) if loan.assigned_at else 0,
        'status': loan.status,
    } for loan in loans[start:end]]
    
    return Response({
        'count': loans.count(),
        'page': page,
        'limit': limit,
        'results': loans_data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_assign_loan(request, loan_id):
    """Assign a loan to an employee"""
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=403)
    
    try:
        loan = LoanApplication.objects.get(id=loan_id)
        employee_id = request.data.get('employee_id')
        
        if not employee_id:
            return Response({'error': 'Employee ID required'}, status=400)
        
        employee = User.objects.get(id=employee_id, role='employee')
        
        # Update loan
        loan.assigned_employee = employee
        loan.assigned_at = timezone.now()
        loan.assigned_by = request.user
        loan.status = 'Waiting for Processing'
        loan.save()
        
        # Create assignment record
        LoanAssignment.objects.create(
            loan_application=loan,
            assigned_to=employee,
            assigned_by=request.user,
            assignment_notes=f'Assigned via admin panel'
        )
        
        # Create status history
        LoanStatusHistory.objects.create(
            loan_application=loan,
            from_status='New Entry',
            to_status='Waiting for Processing',
            changed_by=request.user,
            reason=f'Assigned to {employee.get_full_name()}',
            is_auto_triggered=False
        )
        
        # Log activity
        ActivityLog.objects.create(
            action='status_updated',
            description=f'Loan {loan.id} assigned to {employee.get_full_name()}',
            user=request.user,
            related_loan=loan
        )
        
        return Response({
            'success': True,
            'message': f'Loan assigned to {employee.get_full_name()}',
            'loan': {
                'id': loan.id,
                'status': loan.status,
                'assigned_employee': employee.get_full_name(),
                'assigned_at': loan.assigned_at.isoformat(),
            }
        })
    except LoanApplication.DoesNotExist:
        return Response({'error': 'Loan not found'}, status=404)
    except User.DoesNotExist:
        return Response({'error': 'Employee not found'}, status=404)
    except Exception as e:
        return Response({'error': str(e)}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_reassign_loan(request, loan_id):
    """Reassign a loan to a different employee"""
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=403)
    
    try:
        loan = LoanApplication.objects.get(id=loan_id)
        old_employee = loan.assigned_employee
        new_employee_id = request.data.get('employee_id')
        reason = request.data.get('reason', 'Reassigned by admin')
        
        if not new_employee_id:
            return Response({'error': 'Employee ID required'}, status=400)
        
        new_employee = User.objects.get(id=new_employee_id, role='employee')
        
        # Mark old assignment as reassigned
        old_assignment = LoanAssignment.objects.filter(
            loan_application=loan, status='active'
        ).first()
        if old_assignment:
            old_assignment.reassign()
        
        # Update loan - RESET 24H TIMER
        loan.assigned_employee = new_employee
        loan.assigned_at = timezone.now()  # Reset timer
        loan.assigned_by = request.user
        loan.status = 'Waiting for Processing'
        loan.save()
        
        # Create new assignment
        LoanAssignment.objects.create(
            loan_application=loan,
            assigned_to=new_employee,
            assigned_by=request.user,
            assignment_notes=f'Reassigned from {old_employee.get_full_name() if old_employee else "Unassigned"}. Reason: {reason}'
        )
        
        # Create status history
        LoanStatusHistory.objects.create(
            loan_application=loan,
            from_status=loan.status,
            to_status='Waiting for Processing',
            changed_by=request.user,
            reason=f'Reassigned from {old_employee.get_full_name() if old_employee else "Unassigned"} to {new_employee.get_full_name()}. Reason: {reason}',
            is_auto_triggered=False
        )
        
        return Response({
            'success': True,
            'message': f'Loan reassigned to {new_employee.get_full_name()}',
            'loan': {
                'id': loan.id,
                'status': loan.status,
                'assigned_employee': new_employee.get_full_name(),
                'assigned_at': loan.assigned_at.isoformat(),
            }
        })
    except Exception as e:
        return Response({'error': str(e)}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_dashboard_stats(request):
    """Get real-time dashboard statistics"""
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=403)
    
    from datetime import timedelta
    now = timezone.now()
    
    try:
        auto_move_overdue_to_follow_up()

        new_entry_count = LoanApplication.objects.filter(status='New Entry').count()
        waiting_count = LoanApplication.objects.filter(status='Waiting for Processing').count()
        
        # Follow-up: loans assigned > 4h ago with no action
        followup_cutoff = now - timedelta(hours=4)
        followup_count = LoanApplication.objects.filter(
            status='Waiting for Processing',
            assigned_at__lt=followup_cutoff,
            assigned_at__isnull=False
        ).count()
        
        approved_count = LoanApplication.objects.filter(status='Approved').count()
        rejected_count = LoanApplication.objects.filter(status='Rejected').count()
        disbursed_count = LoanApplication.objects.filter(status='Disbursed').count()
        
        return Response({
            'new_entry': new_entry_count,
            'waiting': waiting_count,
            'follow_up': followup_count,
            'approved': approved_count,
            'rejected': rejected_count,
            'disbursed': disbursed_count,
            'timestamp': now.isoformat(),
        })
    except Exception as e:
        return Response({'error': str(e)}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_employees_list(request):
    """Get list of employees for assignment"""
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=403)
    
    employees = User.objects.filter(
        role='employee', is_active=True
    ).values('id', 'first_name', 'last_name', 'email').order_by('first_name')
    
    employees_data = [{
        'id': emp['id'],
        'full_name': f"{emp['first_name']} {emp['last_name']}",
        'email': emp['email'],
    } for emp in employees]
    
    return Response({'results': employees_data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_loan_detail(request, loan_id):
    """Get complete loan application details"""
    try:
        loan = LoanApplication.objects.select_related(
            'applicant', 'assigned_employee', 'assigned_agent'
        ).get(id=loan_id)
        
        # Check permissions
        if request.user.role == 'employee':
            if loan.assigned_employee != request.user:
                return Response({'error': 'You can only view assigned loans'}, status=403)
        elif request.user.role == 'agent':
            if loan.assigned_agent != request.user.agent_profile:
                return Response({'error': 'You can only view your own loans'}, status=403)
        elif request.user.role != 'admin':
            return Response({'error': 'Unauthorized'}, status=403)
        
        applicant = loan.applicant
        documents = ApplicantDocument.objects.filter(loan_application=loan).values(
            'id', 'document_type', 'file'
        )
        
        history = LoanStatusHistory.objects.filter(
            loan_application=loan
        ).select_related('changed_by').values(
            'from_status', 'to_status', 'reason', 'changed_at', 'is_auto_triggered'
        ).order_by('-changed_at')
        
        return Response({
            'id': loan.id,
            'applicant': {
                'full_name': applicant.full_name,
                'mobile': applicant.mobile,
                'email': applicant.email,
                'city': applicant.city,
                'state': applicant.state,
                'pin_code': applicant.pin_code,
                'gender': applicant.gender,
            },
            'loan': {
                'type': applicant.loan_type,
                'amount': str(applicant.loan_amount),
                'tenure_months': applicant.tenure_months,
                'interest_rate': str(applicant.interest_rate),
                'emi': str(applicant.emi),
                'purpose': applicant.loan_purpose,
            },
            'bank': {
                'name': applicant.bank_name,
                'type': applicant.bank_type,
                'account_number': applicant.account_number,
                'ifsc_code': applicant.ifsc_code,
            },
            'assignment': {
                'status': loan.status,
                'assigned_employee': loan.assigned_employee.get_full_name() if loan.assigned_employee else None,
                'assigned_at': loan.assigned_at.isoformat() if loan.assigned_at else None,
                'hours_pending': int((timezone.now() - loan.assigned_at).total_seconds() / 3600) if loan.assigned_at else 0,
            },
            'documents': list(documents),
            'status_history': list(history),
            'created_at': loan.created_at.isoformat(),
            'updated_at': loan.updated_at.isoformat(),
        })
    except LoanApplication.DoesNotExist:
        return Response({'error': 'Loan not found'}, status=404)
    except Exception as e:
        return Response({'error': str(e)}, status=500)


# ============================================================
# NEW ADMIN VIEWS FOR READ-ONLY LOAN DISPLAY
# ============================================================

@admin_required
def admin_new_entries_list(request):
    """Admin view for New Entry applications list (READ-ONLY)
    
    RULES:
    - Admin ONLY access
    - Shows list of unassigned NEW ENTRY applications (status='New Entry', assigned_employee IS NULL)
    - Table with columns: ID, Name, Email, Phone, Loan Type, Amount, Created Date, Action (View)
    - No form fields - READ-ONLY table only
    - Click "View" to see full read-only form with assignment panel
    """
    # Fetch new entry applications - unassigned only
    new_applications = LoanApplication.objects.filter(
        status='New Entry',
        assigned_employee__isnull=True,
        assigned_agent__isnull=True
    ).select_related('applicant').prefetch_related('documents').order_by('-created_at')
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(new_applications, 10)
    page = request.GET.get('page', 1)
    applications_page = paginator.get_page(page)
    
    context = {
        'applications': applications_page,
        'total_count': paginator.count,
        'page_title': 'New Loan Applications',
        'can_assign': True,
        'readonly': True,
    }
    return render(request, 'core/admin/new_entries_list.html', context)


@admin_required
def admin_loan_detail_readonly(request, applicant_id):
    """Admin view for READ-ONLY loan application detail with assignment panel
    
    RULES:
    - Admin ONLY access
    - Display FULL READ-ONLY loan application form (7 sections)
    - Sections: Applicant Info, Occupation, Existing Loans, Loan Request, References, Financial, Documents
    - All fields as read-only (spans, not inputs)
    - NO form submission capability
    - Assignment section: Employee dropdown + Assign button
    - Assignment logic: On assign â†’ status changes to 'Waiting for Processing', assigned_employee set, assigned_at recorded
    """
    try:
        # Fetch applicant and loan application
        applicant = Applicant.objects.select_related('loan_application').get(id=applicant_id)
        loan_app = applicant.loan_application
        
        # Verify status is 'New Entry'
        if loan_app.status != 'New Entry':
            messages.warning(request, f'This application is now in "{loan_app.status}" status.')
            return redirect('admin_new_entries_list')
        
        # Get documents
        documents = loan_app.documents.all().order_by('document_type')
        photo_document = documents.filter(document_type='photo').first()
        
        # Get active employees for assignment dropdown
        employees = User.objects.filter(role='employee', is_active=True).order_by('first_name')
        
        context = {
            'applicant': applicant,
            'loan_app': loan_app,
            'documents': documents,
            'photo_document': photo_document,
            'employees': employees,
            'can_assign': True,
            'readonly': True,
            'page_title': f'Loan Application - {applicant.full_name}',
        }
        return render(request, 'core/admin/loan_detail_readonly.html', context)
    
    except Applicant.DoesNotExist:
        messages.error(request, 'Application not found.')
        return redirect('admin_new_entries_list')
    except Exception as e:
        messages.error(request, f'Error: {str(e)}')
        return redirect('admin_new_entries_list')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_admin_assign_new_entry(request, applicant_id):
    """API endpoint to assign new entry to employee
    
    POST data:
    {
        'employee_id': int
    }
    
    LOGIC:
    - Assign application to selected employee
    - Change status to 'Waiting for Processing'
    - Set assigned_at timestamp
    - Set assigned_by to current admin user
    """
    if request.user.role != 'admin':
        return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        employee_id = request.data.get('employee_id')
        
        # Validate status
        if loan_app.status != 'New Entry':
            return Response(
                {'error': f'Cannot assign application in "{loan_app.status}" status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get employee
        try:
            employee = User.objects.get(id=employee_id, role='employee', is_active=True)
        except User.DoesNotExist:
            return Response({'error': 'Employee not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Update loan application
        loan_app.assigned_employee = employee
        loan_app.status = 'Waiting for Processing'
        loan_app.assigned_at = timezone.now()
        loan_app.assigned_by = request.user
        loan_app.save()
        
        # Create status history
        from .models import LoanStatusHistory
        LoanStatusHistory.objects.create(
            loan_application=loan_app,
            from_status='New Entry',
            to_status='Waiting for Processing',
            changed_by=request.user,
            reason=f'Assigned to {employee.get_full_name()}',
            is_auto_triggered=False
        )
        
        # Log activity
        ActivityLog.objects.create(
            action='application_assigned',
            description=f'Application "{applicant.full_name}" assigned to {employee.get_full_name()}',
            user=request.user
        )
        
        return Response({
            'success': True,
            'message': f'Application assigned to {employee.get_full_name()}',
            'applicant_name': applicant.full_name,
            'assigned_employee': employee.get_full_name(),
            'assigned_at': loan_app.assigned_at.isoformat(),
            'new_status': loan_app.status,
        })
    
    except Applicant.DoesNotExist:
        return Response({'error': 'Applicant not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_admin_new_entries_list(request):
    """API endpoint to get new entries for admin (JSON)
    
    Returns:
    {
        'count': int,
        'results': [
            {
                'id': int,
                'applicant_name': str,
                'mobile': str,
                'email': str,
                'loan_type': str,
                'loan_amount': float,
                'created_at': ISO datetime,
                'submitted_by': str (agent name or system)
            },
            ...
        ]
    }
    """
    if request.user.role != 'admin':
        return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Fetch new unassigned applications
        applications = LoanApplication.objects.filter(
            status='New Entry',
            assigned_employee__isnull=True,
            assigned_agent__isnull=True
        ).select_related('applicant').order_by('-created_at')
        
        # Pagination
        page = int(request.GET.get('page', 1))
        limit = int(request.GET.get('limit', 10))
        start = (page - 1) * limit
        end = start + limit
        
        # Build response
        results = []
        for app in applications[start:end]:
            applicant = app.applicant
            results.append({
                'id': app.id,
                'applicant_id': applicant.id,
                'applicant_name': applicant.full_name,
                'mobile': applicant.mobile,
                'email': applicant.email,
                'loan_type': applicant.loan_type or 'Not Specified',
                'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                'created_at': app.created_at.isoformat(),
                'created_date': app.created_at.strftime('%d/%m/%Y'),
                'status': app.status,
            })
        
        return Response({
            'count': applications.count(),
            'page': page,
            'limit': limit,
            'total_pages': (applications.count() + limit - 1) // limit,
            'results': results,
        })
    
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# EMPLOYEE REQUEST NEW ENTRY LOAN PAGE & APIS
# ============================================================================

@login_required
@employee_required
def employee_request_new_entry_loan(request):
    """
    Employee page to view and manage assigned loans
    Shows all loans assigned to this employee for processing
    """
    return render(request, 'core/employee/request_new_entry_loan.html', {
        'page_mode': 'new_entry',
        'page_title_text': 'Request New Application Loans',
        'page_subtitle_text': 'Assigned fresh requests waiting for initial review.',
        'default_status_filter': 'Waiting for Processing',
    })


@login_required
@employee_required
def employee_bank_processing_queue(request):
    """
    Employee page dedicated to banking process queue.
    """
    return render(request, 'core/employee/request_new_entry_loan.html', {
        'page_mode': 'bank_processing',
        'page_title_text': 'Bank Processing Queue',
        'page_subtitle_text': 'Loans currently in banking processing and post-processing states.',
        'default_status_filter': 'Required Follow-up',
    })


BANKING_PROCESS_STATUS = 'Required Follow-up'
FOLLOW_UP_PENDING_LABEL = 'Follow Up'


def _has_revert_marker(raw_text):
    return 'revert remark ' in str(raw_text or '').lower()


def _is_follow_up_pending_application(loan_app):
    if not loan_app:
        return False
    if loan_app.status not in ['New Entry', 'Waiting for Processing']:
        return False
    return _has_revert_marker(loan_app.approval_notes)


def _is_follow_up_pending_legacy(loan_obj):
    if not loan_obj:
        return False
    if loan_obj.status not in ['new_entry', 'waiting']:
        return False
    if _has_revert_marker(loan_obj.remarks):
        return True
    related_app = find_related_loan_application(loan_obj)
    return _has_revert_marker(getattr(related_app, 'approval_notes', '')) if related_app else False


def _is_case_edit_allowed_application(loan_app):
    if not loan_app:
        return False
    normalized_status = str(loan_app.status or '').strip().lower()
    allowed_statuses = {'approved', 'required follow-up', 'required_follow_up'}
    return _is_follow_up_pending_application(loan_app) or normalized_status in allowed_statuses


def _is_case_edit_allowed_legacy(loan_obj):
    if not loan_obj:
        return False
    normalized_status = str(loan_obj.status or '').strip().lower()
    allowed_statuses = {'approved', 'follow_up', 'required follow-up', 'required_follow_up'}
    return _is_follow_up_pending_legacy(loan_obj) or normalized_status in allowed_statuses


def _ui_status_label(status_text, follow_up_pending=False):
    if follow_up_pending:
        return FOLLOW_UP_PENDING_LABEL
    normalized = str(status_text or '').strip().lower()
    if normalized in ['new entry', 'new_entry', 'draft']:
        return 'New Application'
    if normalized in ['waiting for processing', 'in processing', 'waiting', 'processing']:
        return 'Document Pending'
    if status_text == BANKING_PROCESS_STATUS or normalized == 'required follow-up':
        return 'Banking Processing'
    return status_text


def _append_bank_remark(existing_text, new_remark):
    new_remark = (new_remark or '').strip()
    if not new_remark:
        return existing_text or ''

    existing_text = existing_text or ''
    remark_line = f"Bank Remark: {new_remark}"
    return f"{existing_text}\n{remark_line}".strip() if existing_text else remark_line


def _append_note_line(existing_text, new_line):
    line = str(new_line or '').strip()
    if not line:
        return existing_text or ''
    existing = str(existing_text or '').strip()
    return f"{existing}\n{line}".strip() if existing else line


def _strip_revert_markers(raw_text):
    lines = []
    for line in str(raw_text or '').splitlines():
        clean_line = str(line or '').strip()
        if clean_line.lower().startswith('revert remark '):
            continue
        lines.append(clean_line)
    return '\n'.join([line for line in lines if line]).strip()


def _build_banking_processing_note(payload):
    payload = payload or {}
    bank_remark = str(payload.get('bank_remark', '')).strip()
    banker_name = str(payload.get('banker_name', '')).strip()
    banker_phone = str(payload.get('banker_phone', '')).strip()
    banker_email = str(payload.get('banker_email', '')).strip()
    banker_description = str(payload.get('banker_description', '')).strip()

    lines = []
    if banker_name:
        lines.append(f"Banker Name: {banker_name}")
    if banker_phone:
        lines.append(f"Banker Phone: {banker_phone}")
    if banker_email:
        lines.append(f"Banker Email: {banker_email}")
    if banker_description:
        lines.append(f"Description: {banker_description}")
    if bank_remark:
        lines.append(f"Bank Remark: {bank_remark}")

    if not lines:
        return 'Moved to Banking Processing'
    return '\n'.join(lines)


def _build_document_pending_note(remark, changed_by):
    safe_remark = str(remark or '').strip()
    actor = changed_by.get_full_name() or changed_by.username or 'System'
    if not safe_remark:
        return f'Document Pending by {actor}'
    return f'Document Pending by {actor}: {safe_remark}'


def _normalize_history_status(status_key):
    normalized = str(status_key or '').strip().lower()
    allowed = {'new_entry', 'waiting', 'follow_up', 'approved', 'rejected', 'disbursed'}
    return normalized if normalized in allowed else 'new_entry'


def _next_revert_index_from_history(loan_app):
    if not loan_app:
        return 1
    count = 0
    for reason in loan_app.status_history.exclude(reason__isnull=True).exclude(reason__exact='').values_list('reason', flat=True):
        text = str(reason or '').strip().lower()
        if text.startswith('revert remark '):
            count += 1
    return count + 1


def _append_related_loan_remark(loan_app, line, status_override=None):
    related_loan = find_related_loan(loan_app)
    if not related_loan:
        return None

    related_loan.remarks = _append_note_line(related_loan.remarks, line)
    if status_override:
        related_loan.status = status_override
    related_loan.sm_name = loan_app.sm_name
    related_loan.sm_phone_number = loan_app.sm_phone_number
    related_loan.sm_email = loan_app.sm_email
    related_loan.is_sm_signed = bool(loan_app.is_sm_signed)
    related_loan.sm_signed_at = loan_app.sm_signed_at
    related_loan.save()
    return related_loan


def _validate_sm_details(sm_name, sm_phone_number, sm_email):
    errors = []
    if not sm_name:
        errors.append('SM name is required.')
    if not sm_phone_number:
        errors.append('SM phone number is required.')
    else:
        phone_digits = ''.join(ch for ch in sm_phone_number if ch.isdigit())
        if len(phone_digits) < 10 or len(phone_digits) > 15:
            errors.append('SM phone number must be 10 to 15 digits.')
    if not sm_email:
        errors.append('SM email is required.')
    elif '@' not in sm_email:
        errors.append('SM email is invalid.')
    return errors


def _is_authorized_processor(user, loan):
    if user.role in ['admin', 'subadmin']:
        return True
    if user.role == 'employee' and loan.assigned_employee_id == user.id:
        return True
    return False


def _get_agent_for_user(user):
    if not user or getattr(user, 'role', '') != 'agent':
        return None
    try:
        return Agent.objects.get(user=user)
    except Agent.DoesNotExist:
        return None


def _is_authorized_follow_up_editor(user, loan_app=None, legacy_loan=None):
    if not user or not getattr(user, 'is_authenticated', False):
        return False

    if user.role in ['admin', 'subadmin']:
        return True

    if user.role == 'employee':
        if loan_app and loan_app.assigned_employee_id == user.id:
            return True
        if legacy_loan and legacy_loan.assigned_employee_id == user.id:
            return True
        return False

    if user.role == 'agent':
        agent_profile = _get_agent_for_user(user)
        if not agent_profile:
            return False
        if loan_app and loan_app.assigned_agent_id == agent_profile.id:
            return True
        if legacy_loan and legacy_loan.assigned_agent_id == agent_profile.id:
            return True
        return False

    return False


def _safe_int(value):
    try:
        if value in [None, '']:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value):
    try:
        if value in [None, '']:
            return None
        return float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def _normalize_entity_source(payload):
    raw = str((payload or {}).get('entity_type') or (payload or {}).get('source') or '').strip().lower()
    source_map = {
        'application': 'application',
        'loan_application': 'application',
        'app': 'application',
        'legacy': 'legacy',
        'loan': 'legacy',
    }
    return source_map.get(raw, '')


def _loan_status_to_workflow(status_key):
    mapping = {
        'follow_up_pending': FOLLOW_UP_PENDING_LABEL,
        'new_entry': 'New Entry',
        'draft': 'New Entry',
        'waiting': 'Waiting for Processing',
        'follow_up': BANKING_PROCESS_STATUS,
        'approved': 'Approved',
        'rejected': 'Rejected',
        'disbursed': 'Disbursed',
    }
    return mapping.get(status_key, status_key)


def _normalize_detail_key(value):
    text = str(value or '').strip().lower()
    text = text.replace('_', ' ').replace('-', ' ').replace('/', ' ')
    return ' '.join(text.split())


def _parse_colon_details(raw_text):
    details = {}
    for line in str(raw_text or '').splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        clean_key = _normalize_detail_key(key)
        clean_value = str(value).strip()
        if clean_key and clean_value:
            details[clean_key] = clean_value
    return details


def _extract_manual_remark(raw_text, parsed_details=None):
    details = parsed_details or _parse_colon_details(raw_text)
    for key in ['remarks suggestions', 'remark', 'remarks', 'bank remark', 'approval notes', 'rejection reason']:
        value = details.get(key)
        if value:
            return value

    plain = str(raw_text or '').strip()
    if plain and ':' not in plain:
        return plain
    return ''


def _looks_like_application_dump(text):
    payload = str(text or '').strip().lower()
    if not payload:
        return False
    markers = [
        'father name', 'mother name', 'date of birth', 'occupation', 'aadhar number',
        'pan number', 'reference 1 name', 'reference 2 name', 'document 1'
    ]
    marker_hits = sum(1 for marker in markers if marker in payload)
    return marker_hits >= 3 or payload.count('\n') >= 8


def _sanitize_timeline_reason(reason):
    text = str(reason or '').strip()
    if not text:
        return ''
    if not _looks_like_application_dump(text):
        return text

    parsed = _parse_colon_details(text)
    manual = _extract_manual_remark(text, parsed)
    if manual:
        return f"Remark: {manual}"

    for key in ['bank remark', 'approval notes', 'rejection reason']:
        value = parsed.get(key)
        if value:
            return f"{key.title()}: {value}"
    return ''


def _build_full_application_details(loan_data, parsed_details):
    rows = []
    seen_labels = set()

    def add(label, value):
        text = str(value or '').strip()
        if text in ['', '-']:
            return
        key = _normalize_detail_key(label)
        if key in seen_labels:
            return
        seen_labels.add(key)
        rows.append({'label': label, 'value': text})

    add('Applicant Name', loan_data.get('applicant_name'))
    add('Mobile Number', loan_data.get('mobile'))
    add('Email', loan_data.get('email'))
    add('Gender', loan_data.get('gender'))
    add('City', loan_data.get('city'))
    add('State', loan_data.get('state'))
    add('PIN Code', loan_data.get('pin_code'))
    add('Permanent Address', loan_data.get('permanent_address'))
    add('Current Address', loan_data.get('current_address'))
    add('Loan Type', loan_data.get('loan_type'))
    add('Loan Amount', loan_data.get('loan_amount'))
    add('Tenure (Months)', loan_data.get('tenure_months'))
    add('Interest Rate', loan_data.get('interest_rate'))
    add('EMI', loan_data.get('emi'))
    add('Loan Purpose', loan_data.get('loan_purpose'))
    add('Bank Name', loan_data.get('bank_name'))
    add('Bank Type', loan_data.get('bank_type'))
    add('Account Number', loan_data.get('account_number'))
    add('IFSC Code', loan_data.get('ifsc_code'))
    add('Co-Applicant Name', loan_data.get('co_applicant_name'))
    add('Co-Applicant Phone', loan_data.get('co_applicant_phone'))
    add('Co-Applicant Email', loan_data.get('co_applicant_email'))
    add('Guarantor Name', loan_data.get('guarantor_name'))
    add('Guarantor Phone', loan_data.get('guarantor_phone'))
    add('Guarantor Email', loan_data.get('guarantor_email'))

    for key, value in (parsed_details or {}).items():
        if key in seen_labels:
            continue
        if key.startswith('assigned by '):
            continue
        label = ' '.join(word.capitalize() for word in key.split())
        add(label, value)

    return rows


def _merge_document_payloads(*document_lists):
    merged = []
    seen_urls = set()

    for doc_list in document_lists:
        for doc in doc_list or []:
            url = (doc or {}).get('file_url') or (doc or {}).get('download_url')
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(doc)
    return merged


def _hours_since(dt_value):
    if not dt_value:
        return 0
    try:
        return (timezone.now() - dt_value).total_seconds() / 3600
    except Exception:
        return 0


def _get_parsed_value(parsed_details, *keys, default=''):
    for key in keys:
        value = (parsed_details or {}).get(_normalize_detail_key(key))
        if value not in [None, '']:
            return value
    return default


def _extract_references_from_parsed(parsed_details):
    refs = []
    for idx in [1, 2]:
        name = _get_parsed_value(parsed_details, f'reference {idx} name', f'ref{idx} name', f'ref{idx}_name')
        mobile = _get_parsed_value(parsed_details, f'reference {idx} mobile', f'reference {idx} mobile no', f'ref{idx} mobile', f'ref{idx}_mobile')
        address = _get_parsed_value(parsed_details, f'reference {idx} address', f'ref{idx} address', f'ref{idx}_address')
        if name or mobile or address:
            refs.append({
                'name': name or '-',
                'mobile_number': mobile or '-',
                'address': address or '-',
            })
    return refs


def _parse_float_safe(value, default=0):
    try:
        text = str(value or '').replace(',', '').replace('Rs', '').replace('Rs.', '').replace('₹', '').strip()
        if text == '':
            return default
        return float(text)
    except Exception:
        return default


def _extract_existing_loans_from_parsed(parsed_details):
    rows = []
    details_map = parsed_details or {}
    loan_index_pattern = re.compile(r'^(?:existing\s+)?loan\s+(\d+)\s+')
    dynamic_indexes = sorted({
        int(match.group(1))
        for key in details_map.keys()
        for match in [loan_index_pattern.match(str(key or ''))]
        if match
    })
    indexes = dynamic_indexes if dynamic_indexes else [1, 2, 3]

    for idx in indexes:
        bank_name = _get_parsed_value(
            details_map,
            f'existing loan {idx} bank finance name',
            f'existing loan {idx} bank name',
            f'existing loan {idx} bank',
            f'loan {idx} bank finance name',
            f'loan {idx} bank name',
            f'loan {idx} bank',
        )
        amount_taken = _get_parsed_value(details_map, f'existing loan {idx} amount taken', f'loan {idx} amount taken')
        emi_left = _get_parsed_value(details_map, f'existing loan {idx} emi left', f'loan {idx} emi left')
        amount_left = _get_parsed_value(details_map, f'existing loan {idx} amount left', f'loan {idx} amount left')
        years_months = _get_parsed_value(
            details_map,
            f'existing loan {idx} years months',
            f'existing loan {idx} years/months',
            f'existing loan {idx} duration',
            f'existing loan {idx} tenure',
            f'loan {idx} years months',
            f'loan {idx} years/months',
            f'loan {idx} duration',
            f'loan {idx} tenure',
        )
        emi_amount = _get_parsed_value(details_map, f'existing loan {idx} emi amount', f'loan {idx} emi amount')
        any_bounce = _get_parsed_value(
            details_map,
            f'existing loan {idx} any bounce',
            f'existing loan {idx} bounce',
            f'existing loan {idx} emi cross',
            f'loan {idx} any bounce',
            f'loan {idx} bounce',
        )
        cleared = _get_parsed_value(details_map, f'existing loan {idx} cleared', f'loan {idx} cleared')
        if any([bank_name, amount_taken, emi_left, amount_left, years_months, emi_amount, any_bounce, cleared]):
            rows.append({
                'bank_name': bank_name or '-',
                'amount_taken': _parse_float_safe(amount_taken, 0),
                'emi_left': emi_left or '-',
                'amount_left': _parse_float_safe(amount_left, 0),
                'tenure': years_months or '-',
                'emi_amount': _parse_float_safe(emi_amount, 0),
                'any_bounce': any_bounce or '-',
                'cleared': str(cleared or '').strip().lower() in ['yes', 'true', '1'],
            })
    return rows


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_assigned_loans_list(request):
    """
    Get list of all loans assigned to employee with filters
    Returns table data for Request New Entry Loan page
    """
    if request.user.role != 'employee':
        return Response({
            'success': False,
            'role_mismatch': True,
            'message': 'Employee context not active',
            'loans': [],
            'total': 0,
            'page': 1,
            'total_pages': 0,
            'per_page': 0,
        }, status=status.HTTP_200_OK)

    try:
        auto_move_overdue_to_follow_up()

        status_filter = request.GET.get('status', '').strip()
        from_date = request.GET.get('from_date', '').strip()
        to_date = request.GET.get('to_date', '').strip()
        page = max(int(request.GET.get('page', 1) or 1), 1)
        limit = max(int(request.GET.get('limit', 20) or 20), 1)

        from_date_obj = None
        to_date_obj = None
        if from_date:
            try:
                from_date_obj = datetime.strptime(from_date, '%Y-%m-%d').date()
            except Exception:
                from_date_obj = None
        if to_date:
            try:
                to_date_obj = datetime.strptime(to_date, '%Y-%m-%d').date()
            except Exception:
                to_date_obj = None

        legacy_status_map = {
            'New Entry': 'new_entry',
            'Waiting for Processing': 'waiting',
            'Required Follow-up': 'follow_up',
            'Banking Processing': 'follow_up',
            FOLLOW_UP_PENDING_LABEL: 'new_entry',
            'Approved': 'approved',
            'Rejected': 'rejected',
            'Disbursed': 'disbursed',
        }
        follow_up_pending_app_q = Q(status__in=['New Entry', 'Waiting for Processing']) & Q(approval_notes__icontains='Revert Remark ')
        follow_up_pending_legacy_q = Q(status__in=['new_entry', 'waiting']) & Q(remarks__icontains='Revert Remark ')

        combined_rows = []
        seen_rows = set()

        app_qs = LoanApplication.objects.filter(
            assigned_employee=request.user
        ).select_related('applicant', 'assigned_by').order_by('-assigned_at', '-created_at')

        if status_filter == FOLLOW_UP_PENDING_LABEL:
            app_qs = app_qs.filter(follow_up_pending_app_q)
        elif status_filter:
            app_qs = app_qs.filter(status=status_filter)
            if status_filter in ['New Entry', 'Waiting for Processing']:
                app_qs = app_qs.exclude(approval_notes__icontains='Revert Remark ')
        if from_date_obj:
            app_qs = app_qs.filter(assigned_at__date__gte=from_date_obj)
        if to_date_obj:
            app_qs = app_qs.filter(assigned_at__date__lte=to_date_obj)

        for loan_app in app_qs:
            applicant = loan_app.applicant
            assigned_at = loan_app.assigned_at or loan_app.created_at
            follow_up_pending = _is_follow_up_pending_application(loan_app)
            row_status = FOLLOW_UP_PENDING_LABEL if follow_up_pending else loan_app.status
            row_signature = (
                _normalize_detail_key(applicant.full_name),
                applicant.mobile or '',
                float(applicant.loan_amount or 0),
                row_status,
                assigned_at.strftime('%Y-%m-%d') if assigned_at else '',
            )
            seen_rows.add(row_signature)

            combined_rows.append({
                'id': loan_app.id,
                'applicant_id': applicant.id,
                'applicant_name': applicant.full_name,
                'mobile': applicant.mobile,
                'email': applicant.email,
                'city': applicant.city,
                'loan_type': applicant.loan_type or 'N/A',
                'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                'loan_purpose': applicant.loan_purpose or 'N/A',
                'status': row_status,
                'status_display': _ui_status_label(row_status, follow_up_pending=follow_up_pending),
                'follow_up_pending': follow_up_pending,
                'assigned_date': assigned_at.strftime('%Y-%m-%d') if assigned_at else '',
                'assigned_by_name': loan_app.assigned_by.get_full_name() if loan_app.assigned_by else 'System',
                'hours_since_assignment': round(_hours_since(assigned_at), 1),
                'approval_notes': _sanitize_timeline_reason(loan_app.approval_notes),
                'rejection_reason': _sanitize_timeline_reason(loan_app.rejection_reason),
                '_sort_ts': assigned_at or loan_app.created_at,
            })

        legacy_qs = Loan.objects.filter(
            assigned_employee=request.user
        ).select_related('created_by').order_by('-assigned_at', '-created_at')

        if status_filter == FOLLOW_UP_PENDING_LABEL:
            legacy_qs = legacy_qs.filter(follow_up_pending_legacy_q)
        elif status_filter:
            mapped_legacy_status = legacy_status_map.get(status_filter)
            if mapped_legacy_status:
                legacy_qs = legacy_qs.filter(status=mapped_legacy_status)
                if mapped_legacy_status in ['new_entry', 'waiting']:
                    legacy_qs = legacy_qs.exclude(remarks__icontains='Revert Remark ')

        for legacy_loan in legacy_qs:
            assigned_at = legacy_loan.assigned_at or legacy_loan.created_at
            assigned_date = assigned_at.date() if assigned_at else None
            if from_date_obj and assigned_date and assigned_date < from_date_obj:
                continue
            if to_date_obj and assigned_date and assigned_date > to_date_obj:
                continue

            follow_up_pending = _is_follow_up_pending_legacy(legacy_loan)
            workflow_status = FOLLOW_UP_PENDING_LABEL if follow_up_pending else _loan_status_to_workflow(legacy_loan.status)
            assignment_context = extract_assignment_context(legacy_loan)
            parsed_remarks = _parse_colon_details(legacy_loan.remarks)

            row_signature = (
                _normalize_detail_key(legacy_loan.full_name),
                legacy_loan.mobile_number or '',
                float(legacy_loan.loan_amount or 0),
                workflow_status,
                assigned_at.strftime('%Y-%m-%d') if assigned_at else '',
            )
            if row_signature in seen_rows:
                continue
            seen_rows.add(row_signature)

            combined_rows.append({
                'id': legacy_loan.id,
                'applicant_id': legacy_loan.id,
                'applicant_name': legacy_loan.full_name,
                'mobile': legacy_loan.mobile_number,
                'email': legacy_loan.email,
                'city': legacy_loan.city,
                'loan_type': legacy_loan.loan_type or 'N/A',
                'loan_amount': float(legacy_loan.loan_amount) if legacy_loan.loan_amount else 0,
                'loan_purpose': legacy_loan.loan_purpose or parsed_remarks.get('loan purpose') or 'N/A',
                'status': workflow_status,
                'status_display': _ui_status_label(workflow_status, follow_up_pending=follow_up_pending),
                'follow_up_pending': follow_up_pending,
                'assigned_date': assigned_at.strftime('%Y-%m-%d') if assigned_at else '',
                'assigned_by_name': assignment_context.get('assigned_by_name') or (
                    legacy_loan.created_by.get_full_name() if legacy_loan.created_by else 'System'
                ),
                'hours_since_assignment': round(_hours_since(assigned_at), 1),
                'approval_notes': _sanitize_timeline_reason(parsed_remarks.get('approval notes')),
                'rejection_reason': _sanitize_timeline_reason(parsed_remarks.get('rejection reason')),
                '_sort_ts': assigned_at or legacy_loan.created_at,
            })

        combined_rows.sort(key=lambda row: row.get('_sort_ts') or timezone.now(), reverse=True)

        paginator = Paginator(combined_rows, limit)
        page_obj = paginator.get_page(page)

        loans_data = []
        for row in page_obj.object_list:
            payload = dict(row)
            payload.pop('_sort_ts', None)
            loans_data.append(payload)

        return Response({
            'success': True,
            'loans': loans_data,
            'total': len(combined_rows),
            'page': page,
            'total_pages': paginator.num_pages,
            'per_page': limit,
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_assigned_loan_detail(request, loan_id):
    """
    Get full details of a loan assigned to employee (read-only)
    """
    if request.user.role != 'employee':
        return Response({
            'success': False,
            'role_mismatch': True,
            'message': 'Employee context not active',
        }, status=status.HTTP_200_OK)

    def _history_status_label(raw_status):
        if not raw_status:
            return '-'
        mapping = {
            'new_entry': 'New Application',
            'waiting': 'Document Pending',
            'follow_up': 'Banking Processing',
            'follow_up_pending': FOLLOW_UP_PENDING_LABEL,
            'approved': 'Approved',
            'rejected': 'Rejected',
            'disbursed': 'Disbursed',
            'Required Follow-up': 'Banking Processing',
        }
        return mapping.get(raw_status, _ui_status_label(raw_status))

    def _serialize_status_history(history_qs):
        history_items = []
        for row in history_qs.select_related('changed_by').order_by('-changed_at')[:80]:
            actor_name = row.changed_by.get_full_name() if row.changed_by else 'System'
            actor_role = row.changed_by.get_role_display() if row.changed_by else 'System'
            clean_reason = _sanitize_timeline_reason(row.reason)
            history_items.append({
                'id': row.id,
                'from_status': row.from_status or '',
                'from_status_display': _history_status_label(row.from_status),
                'to_status': row.to_status or '',
                'to_status_display': _history_status_label(row.to_status),
                'changed_by_name': actor_name or 'System',
                'changed_by_role': actor_role,
                'changed_at': row.changed_at.strftime('%Y-%m-%d %H:%M') if row.changed_at else '',
                'reason': clean_reason or 'Status updated',
                'is_auto_triggered': bool(row.is_auto_triggered),
            })
        return history_items

    def _serialize_documents(docs_qs):
        docs = []
        for doc in docs_qs.order_by('-uploaded_at'):
            if not getattr(doc, 'file', None):
                continue
            source = 'application' if hasattr(doc, 'loan_application_id') else 'legacy'
            file_url = doc.file.url
            file_name = doc.file.name.split('/')[-1]
            docs.append({
                'id': doc.id,
                'source': source,
                'document_type': getattr(doc, 'document_type', ''),
                'document_type_display': doc.get_document_type_display(),
                'file_name': file_name,
                'file_url': file_url,
                'download_url': file_url,
                'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else '',
                'is_required': bool(getattr(doc, 'is_required', False)),
            })
        return docs

    def _legacy_reason_items(legacy_obj, assigned_by_name, assigned_by_role):
        parsed = _parse_colon_details(legacy_obj.remarks)
        items = []
        for key, label in [
            ('approval notes', 'Approval Notes'),
            ('rejection reason', 'Rejection Reason'),
            ('bank remark', 'Bank Remark'),
        ]:
            raw = parsed.get(key)
            clean = _sanitize_timeline_reason(raw)
            if not clean:
                continue
            items.append({
                'id': f'legacy-{legacy_obj.id}-{key.replace(" ", "-")}',
                'from_status': '',
                'from_status_display': '-',
                'to_status': legacy_obj.status,
                'to_status_display': label,
                'changed_by_name': assigned_by_name or 'System',
                'changed_by_role': assigned_by_role or 'System',
                'changed_at': legacy_obj.updated_at.strftime('%Y-%m-%d %H:%M') if legacy_obj.updated_at else '',
                'reason': clean,
                'is_auto_triggered': False,
            })

        if not items:
            manual = _extract_manual_remark(legacy_obj.remarks, parsed)
            if manual:
                items.append({
                    'id': f'legacy-{legacy_obj.id}-remark',
                    'from_status': '',
                    'from_status_display': '-',
                    'to_status': legacy_obj.status,
                    'to_status_display': 'Remark',
                    'changed_by_name': assigned_by_name or 'System',
                    'changed_by_role': assigned_by_role or 'System',
                    'changed_at': legacy_obj.updated_at.strftime('%Y-%m-%d %H:%M') if legacy_obj.updated_at else '',
                    'reason': manual,
                    'is_auto_triggered': False,
                })
        return items

    def _dedupe_history(items):
        deduped = []
        seen = set()
        for item in items:
            key = (
                item.get('to_status_display', ''),
                item.get('reason', ''),
                item.get('changed_at', ''),
                item.get('changed_by_name', ''),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        deduped.sort(key=lambda row: row.get('changed_at') or '', reverse=True)
        return deduped

    try:
        try:
            loan = LoanApplication.objects.select_related(
                'applicant', 'assigned_by', 'approved_by', 'rejected_by', 'disbursed_by'
            ).prefetch_related('documents', 'status_history').get(
                id=loan_id,
                assigned_employee=request.user,
            )
            applicant = loan.applicant
            related_legacy = find_related_loan(loan)
            legacy_details = _parse_colon_details(related_legacy.remarks) if related_legacy else {}
            assigned_by_name = loan.assigned_by.get_full_name() if loan.assigned_by else 'System'
            assigned_by_role = loan.assigned_by.get_role_display() if loan.assigned_by else 'System'
            assignment_visibility = (
                'Visible in both Partner and Admin panels'
                if loan.assigned_by and loan.assigned_by.role == 'subadmin'
                else 'Visible in Admin panel'
            )

            app_docs = _serialize_documents(loan.documents.all())
            legacy_docs = _serialize_documents(related_legacy.documents.all()) if related_legacy else []
            documents = _merge_document_payloads(app_docs, legacy_docs)

            status_history = _serialize_status_history(loan.status_history.all())
            if related_legacy:
                status_history.extend(_legacy_reason_items(related_legacy, assigned_by_name, assigned_by_role))
            status_history = _dedupe_history(status_history)

            approval_notes = _sanitize_timeline_reason(loan.approval_notes) or _sanitize_timeline_reason(legacy_details.get('approval notes'))
            rejection_reason = _sanitize_timeline_reason(loan.rejection_reason) or _sanitize_timeline_reason(legacy_details.get('rejection reason'))
            references = _extract_references_from_parsed(legacy_details)
            existing_loans = _extract_existing_loans_from_parsed(legacy_details)
            follow_up_pending = _is_follow_up_pending_application(loan)
            display_status = FOLLOW_UP_PENDING_LABEL if follow_up_pending else loan.status

            loan_data = {
                'id': loan.id,
                'applicant_id': applicant.id,
                'loan_reference': f'APP-{loan.id:06d}',
                'applicant_name': applicant.full_name,
                'username': applicant.username or '',
                'mobile': applicant.mobile,
                'email': applicant.email,
                'gender': applicant.gender or '',
                'city': applicant.city,
                'state': applicant.state,
                'pin_code': applicant.pin_code,
                'alternate_mobile': _get_parsed_value(legacy_details, 'alternate mobile'),
                'permanent_address': getattr(applicant, 'permanent_address', '') or legacy_details.get('permanent address', ''),
                'current_address': getattr(applicant, 'current_address', '') or legacy_details.get('present address', ''),
                'permanent_landmark': _get_parsed_value(legacy_details, 'permanent landmark'),
                'permanent_city': _get_parsed_value(legacy_details, 'permanent city') or applicant.city or '',
                'permanent_pin': _get_parsed_value(legacy_details, 'permanent pin') or applicant.pin_code or '',
                'present_landmark': _get_parsed_value(legacy_details, 'present landmark'),
                'present_city': _get_parsed_value(legacy_details, 'present city') or applicant.city or '',
                'present_pin': _get_parsed_value(legacy_details, 'present pin') or applicant.pin_code or '',
                'loan_type': applicant.loan_type,
                'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                'tenure_months': applicant.tenure_months or 0,
                'interest_rate': float(applicant.interest_rate) if applicant.interest_rate else 0,
                'emi': float(applicant.emi) if applicant.emi else 0,
                'loan_purpose': applicant.loan_purpose,
                'charges_applicable': _get_parsed_value(legacy_details, 'charges fee', 'charges or fee', 'any charges or fee', default='No charges'),
                'status': display_status,
                'status_display': _ui_status_label(display_status, follow_up_pending=follow_up_pending),
                'follow_up_pending': follow_up_pending,
                'follow_up_editable': follow_up_pending,
                'assigned_date': loan.assigned_at.strftime('%Y-%m-%d %H:%M') if loan.assigned_at else '',
                'assigned_by_name': assigned_by_name or 'System',
                'assigned_by_role': assigned_by_role,
                'assignment_visibility': assignment_visibility,
                'entity_type': 'application',
                'loan_application_id': loan.id,
                'legacy_loan_id': related_legacy.id if related_legacy else None,
                'approval_notes': approval_notes or '',
                'rejection_reason': rejection_reason or '',
                'disbursement_amount': float(loan.disbursement_amount) if loan.disbursement_amount else 0,
                'disbursed_at': loan.disbursed_at.strftime('%Y-%m-%d %H:%M') if loan.disbursed_at else '',
                'sm_name': loan.sm_name or (related_legacy.sm_name if related_legacy else ''),
                'sm_phone_number': loan.sm_phone_number or (related_legacy.sm_phone_number if related_legacy else ''),
                'sm_email': loan.sm_email or (related_legacy.sm_email if related_legacy else ''),
                'is_sm_signed': bool(loan.is_sm_signed) or bool(related_legacy.is_sm_signed if related_legacy else False),
                'sm_signed_at': (
                    (loan.sm_signed_at or (related_legacy.sm_signed_at if related_legacy else None)).strftime('%Y-%m-%d %H:%M')
                    if (loan.sm_signed_at or (related_legacy.sm_signed_at if related_legacy else None)) else ''
                ),
                'follow_up_count': loan.follow_up_count or 0,
                'bank_name': applicant.bank_name or '',
                'bank_type': applicant.bank_type or '',
                'account_number': applicant.account_number or '',
                'ifsc_code': applicant.ifsc_code or '',
                'father_name': legacy_details.get('father name', ''),
                'mother_name': legacy_details.get('mother name', ''),
                'date_of_birth': legacy_details.get('date of birth', ''),
                'marital_status': legacy_details.get('marital status', ''),
                'occupation': legacy_details.get('occupation', ''),
                'employment_date': _get_parsed_value(legacy_details, 'date of joining'),
                'experience_years': legacy_details.get('experience (years)', ''),
                'additional_income': _get_parsed_value(legacy_details, 'additional income', 'extra income'),
                'extra_income_details': _get_parsed_value(legacy_details, 'extra income details'),
                'cibil_score': legacy_details.get('cibil score', ''),
                'aadhar_number': legacy_details.get('aadhar number', ''),
                'pan_number': legacy_details.get('pan number', ''),
                'remarks': _extract_manual_remark(related_legacy.remarks, legacy_details) if related_legacy else '',
                'existing_loans': existing_loans,
                'references': references,
                'declaration': 'I hereby declare that the above information given by me is true and correct.',
                'documents': documents,
                'status_history': status_history,
                'document_type_choices': [
                    {'value': value, 'label': label}
                    for value, label in ApplicantDocument.DOCUMENT_TYPE_CHOICES
                ],
            }
            loan_data['full_application_details'] = _build_full_application_details(loan_data, legacy_details)
        except LoanApplication.DoesNotExist:
            legacy = Loan.objects.select_related('created_by').prefetch_related('documents').get(
                id=loan_id,
                assigned_employee=request.user,
            )
            related_app = find_related_loan_application(legacy)
            related_applicant = related_app.applicant if related_app else None
            parsed_legacy = _parse_colon_details(legacy.remarks)
            workflow_status = _loan_status_to_workflow(legacy.status)
            assignment_context = extract_assignment_context(legacy, related_app)
            assigned_by_name = assignment_context.get('assigned_by_name') or (
                legacy.created_by.get_full_name() if legacy.created_by else 'System'
            )
            role_key = assignment_context.get('role') or (legacy.created_by.role if legacy.created_by else '')
            role_map = dict(User.ROLE_CHOICES)
            assigned_by_role = role_map.get(role_key, legacy.created_by.get_role_display() if legacy.created_by else 'System')
            assignment_visibility = 'Visible in both Partner and Admin panels' if role_key == 'subadmin' else 'Visible in Admin panel'

            status_history = []
            if related_app:
                status_history.extend(_serialize_status_history(related_app.status_history.all()))
            status_history.extend(_legacy_reason_items(legacy, assigned_by_name, assigned_by_role))
            status_history = _dedupe_history(status_history)

            app_docs = _serialize_documents(related_app.documents.all()) if related_app else []
            legacy_docs = _serialize_documents(legacy.documents.all())
            documents = _merge_document_payloads(app_docs, legacy_docs)

            approval_notes = _sanitize_timeline_reason(parsed_legacy.get('approval notes'))
            rejection_reason = _sanitize_timeline_reason(parsed_legacy.get('rejection reason'))
            if related_app:
                approval_notes = approval_notes or _sanitize_timeline_reason(related_app.approval_notes)
                rejection_reason = rejection_reason or _sanitize_timeline_reason(related_app.rejection_reason)
            references = _extract_references_from_parsed(parsed_legacy)
            existing_loans = _extract_existing_loans_from_parsed(parsed_legacy)
            follow_up_pending = _is_follow_up_pending_legacy(legacy)
            display_status = FOLLOW_UP_PENDING_LABEL if follow_up_pending else workflow_status

            loan_data = {
                'id': legacy.id,
                'applicant_id': legacy.id,
                'loan_reference': f'LOAN-{legacy.id:06d}',
                'applicant_name': legacy.full_name,
                'username': legacy.username or '',
                'mobile': legacy.mobile_number,
                'email': related_applicant.email if related_applicant and related_applicant.email else legacy.email,
                'gender': related_applicant.gender if related_applicant else parsed_legacy.get('gender', ''),
                'city': related_applicant.city if related_applicant and related_applicant.city else legacy.city,
                'state': related_applicant.state if related_applicant and related_applicant.state else legacy.state,
                'pin_code': related_applicant.pin_code if related_applicant and related_applicant.pin_code else legacy.pin_code,
                'alternate_mobile': _get_parsed_value(parsed_legacy, 'alternate mobile'),
                'permanent_address': (
                    getattr(related_applicant, 'permanent_address', None)
                    if related_applicant and getattr(related_applicant, 'permanent_address', None)
                    else legacy.permanent_address
                ),
                'current_address': (
                    getattr(related_applicant, 'current_address', None)
                    if related_applicant and getattr(related_applicant, 'current_address', None)
                    else legacy.current_address
                ),
                'permanent_landmark': _get_parsed_value(parsed_legacy, 'permanent landmark'),
                'permanent_city': _get_parsed_value(parsed_legacy, 'permanent city') or legacy.city or '',
                'permanent_pin': _get_parsed_value(parsed_legacy, 'permanent pin') or legacy.pin_code or '',
                'present_landmark': _get_parsed_value(parsed_legacy, 'present landmark'),
                'present_city': _get_parsed_value(parsed_legacy, 'present city') or legacy.city or '',
                'present_pin': _get_parsed_value(parsed_legacy, 'present pin') or legacy.pin_code or '',
                'loan_type': related_applicant.loan_type if related_applicant and related_applicant.loan_type else legacy.loan_type,
                'loan_amount': float(legacy.loan_amount) if legacy.loan_amount else 0,
                'tenure_months': related_applicant.tenure_months if related_applicant and related_applicant.tenure_months else (legacy.tenure_months or 0),
                'interest_rate': float(related_applicant.interest_rate) if related_applicant and related_applicant.interest_rate else (float(legacy.interest_rate) if legacy.interest_rate else 0),
                'emi': float(legacy.emi) if legacy.emi else 0,
                'loan_purpose': (
                    related_applicant.loan_purpose if related_applicant and related_applicant.loan_purpose
                    else legacy.loan_purpose or parsed_legacy.get('loan purpose', '')
                ),
                'charges_applicable': _get_parsed_value(parsed_legacy, 'charges fee', 'charges or fee', 'any charges or fee', default='No charges'),
                'status': display_status,
                'status_display': _ui_status_label(display_status, follow_up_pending=follow_up_pending),
                'follow_up_pending': follow_up_pending,
                'follow_up_editable': follow_up_pending,
                'assigned_date': legacy.assigned_at.strftime('%Y-%m-%d %H:%M') if legacy.assigned_at else '',
                'assigned_by_name': assigned_by_name or 'System',
                'assigned_by_role': assigned_by_role,
                'assignment_visibility': assignment_visibility,
                'entity_type': 'legacy',
                'loan_application_id': related_app.id if related_app else None,
                'legacy_loan_id': legacy.id,
                'approval_notes': approval_notes or '',
                'rejection_reason': rejection_reason or '',
                'disbursement_amount': float(legacy.loan_amount) if legacy.status == 'disbursed' and legacy.loan_amount else 0,
                'disbursed_at': legacy.updated_at.strftime('%Y-%m-%d %H:%M') if legacy.status == 'disbursed' else '',
                'sm_name': (
                    legacy.sm_name
                    or (related_app.sm_name if related_app and related_app.sm_name else '')
                ),
                'sm_phone_number': (
                    legacy.sm_phone_number
                    or (related_app.sm_phone_number if related_app and related_app.sm_phone_number else '')
                ),
                'sm_email': (
                    legacy.sm_email
                    or (related_app.sm_email if related_app and related_app.sm_email else '')
                ),
                'is_sm_signed': bool(legacy.is_sm_signed) or bool(related_app.is_sm_signed if related_app else False),
                'sm_signed_at': (
                    (legacy.sm_signed_at or (related_app.sm_signed_at if related_app else None)).strftime('%Y-%m-%d %H:%M')
                    if (legacy.sm_signed_at or (related_app.sm_signed_at if related_app else None)) else ''
                ),
                'follow_up_count': 1 if legacy.status == 'follow_up' else 0,
                'bank_name': (
                    related_applicant.bank_name if related_applicant and related_applicant.bank_name
                    else legacy.bank_name or parsed_legacy.get('bank name', '')
                ),
                'bank_type': (
                    related_applicant.bank_type if related_applicant and related_applicant.bank_type
                    else legacy.bank_type or parsed_legacy.get('bank type', '')
                ),
                'account_number': (
                    related_applicant.account_number if related_applicant and related_applicant.account_number
                    else legacy.bank_account_number or parsed_legacy.get('account number', '')
                ),
                'ifsc_code': (
                    related_applicant.ifsc_code if related_applicant and related_applicant.ifsc_code
                    else legacy.bank_ifsc_code or parsed_legacy.get('ifsc code', '')
                ),
                'father_name': parsed_legacy.get('father name', ''),
                'mother_name': parsed_legacy.get('mother name', ''),
                'date_of_birth': parsed_legacy.get('date of birth', ''),
                'marital_status': parsed_legacy.get('marital status', ''),
                'occupation': parsed_legacy.get('occupation', ''),
                'employment_date': _get_parsed_value(parsed_legacy, 'date of joining'),
                'experience_years': parsed_legacy.get('experience (years)', ''),
                'additional_income': _get_parsed_value(parsed_legacy, 'additional income', 'extra income'),
                'extra_income_details': _get_parsed_value(parsed_legacy, 'extra income details'),
                'cibil_score': parsed_legacy.get('cibil score', ''),
                'aadhar_number': parsed_legacy.get('aadhar number', ''),
                'pan_number': parsed_legacy.get('pan number', ''),
                'remarks': _extract_manual_remark(legacy.remarks, parsed_legacy),
                'existing_loans': existing_loans,
                'references': references,
                'declaration': 'I hereby declare that the above information given by me is true and correct.',
                'has_co_applicant': bool(legacy.has_co_applicant),
                'co_applicant_name': legacy.co_applicant_name or '',
                'co_applicant_phone': legacy.co_applicant_phone or '',
                'co_applicant_email': legacy.co_applicant_email or '',
                'has_guarantor': bool(legacy.has_guarantor),
                'guarantor_name': legacy.guarantor_name or '',
                'guarantor_phone': legacy.guarantor_phone or '',
                'guarantor_email': legacy.guarantor_email or '',
                'documents': documents,
                'status_history': status_history,
                'document_type_choices': [
                    {'value': value, 'label': label}
                    for value, label in LoanDocument.DOCUMENT_TYPE_CHOICES
                ],
            }
            loan_data['full_application_details'] = _build_full_application_details(loan_data, parsed_legacy)

        return Response({
            'success': True,
            'loan': loan_data,
        }, status=status.HTTP_200_OK)

    except (LoanApplication.DoesNotExist, Loan.DoesNotExist):
        return Response({'success': False, 'error': 'Loan not found or not assigned to you'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_update_follow_up_details(request, loan_id):
    """
    Edit follow-up pending application details before moving it back to Banking Processing.
    Allowed roles: admin, subadmin, assigned employee, assigned agent.
    """
    payload = request.data
    edit_remark = str(payload.get('edit_remark', '')).strip()

    def _apply_applicant_updates(applicant_obj):
        changed = False
        text_fields = {
            'full_name': 'full_name',
            'mobile': 'mobile',
            'email': 'email',
            'city': 'city',
            'state': 'state',
            'pin_code': 'pin_code',
            'loan_purpose': 'loan_purpose',
            'bank_name': 'bank_name',
            'bank_type': 'bank_type',
            'account_number': 'account_number',
            'ifsc_code': 'ifsc_code',
            'gender': 'gender',
        }

        for req_key, model_key in text_fields.items():
            if req_key not in payload:
                continue
            new_value = str(payload.get(req_key, '')).strip()
            if getattr(applicant_obj, model_key) != new_value:
                setattr(applicant_obj, model_key, new_value)
                changed = True

        if 'loan_type' in payload:
            loan_type = str(payload.get('loan_type', '')).strip().lower()
            valid_loan_types = {value for value, _ in Applicant.LOAN_TYPE_CHOICES}
            if loan_type and loan_type in valid_loan_types and applicant_obj.loan_type != loan_type:
                applicant_obj.loan_type = loan_type
                changed = True

        if 'loan_amount' in payload:
            parsed_amount = _safe_float(payload.get('loan_amount'))
            if parsed_amount is not None and float(applicant_obj.loan_amount or 0) != float(parsed_amount):
                applicant_obj.loan_amount = parsed_amount
                changed = True

        if 'tenure_months' in payload:
            parsed_tenure = _safe_int(payload.get('tenure_months'))
            if parsed_tenure is not None and int(applicant_obj.tenure_months or 0) != int(parsed_tenure):
                applicant_obj.tenure_months = parsed_tenure
                changed = True

        if 'interest_rate' in payload:
            parsed_interest = _safe_float(payload.get('interest_rate'))
            current_interest = float(applicant_obj.interest_rate or 0)
            if parsed_interest is not None and float(parsed_interest) != current_interest:
                applicant_obj.interest_rate = parsed_interest
                changed = True

        if changed:
            applicant_obj.save()
        return changed

    def _apply_legacy_updates(legacy_obj):
        changed = False
        text_fields = {
            'full_name': 'full_name',
            'mobile': 'mobile_number',
            'email': 'email',
            'city': 'city',
            'state': 'state',
            'pin_code': 'pin_code',
            'loan_purpose': 'loan_purpose',
            'bank_name': 'bank_name',
            'bank_type': 'bank_type',
            'account_number': 'bank_account_number',
            'ifsc_code': 'bank_ifsc_code',
            'permanent_address': 'permanent_address',
            'current_address': 'current_address',
        }

        for req_key, model_key in text_fields.items():
            if req_key not in payload:
                continue
            new_value = str(payload.get(req_key, '')).strip()
            if getattr(legacy_obj, model_key) != new_value:
                setattr(legacy_obj, model_key, new_value)
                changed = True

        if 'loan_type' in payload:
            loan_type = str(payload.get('loan_type', '')).strip().lower()
            valid_loan_types = {value for value, _ in Loan.LOAN_TYPE_CHOICES}
            if loan_type and loan_type in valid_loan_types and legacy_obj.loan_type != loan_type:
                legacy_obj.loan_type = loan_type
                changed = True

        if 'loan_amount' in payload:
            parsed_amount = _safe_float(payload.get('loan_amount'))
            if parsed_amount is not None and float(legacy_obj.loan_amount or 0) != float(parsed_amount):
                legacy_obj.loan_amount = parsed_amount
                changed = True

        if 'tenure_months' in payload:
            parsed_tenure = _safe_int(payload.get('tenure_months'))
            if parsed_tenure is not None and int(legacy_obj.tenure_months or 0) != int(parsed_tenure):
                legacy_obj.tenure_months = parsed_tenure
                changed = True

        if 'interest_rate' in payload:
            parsed_interest = _safe_float(payload.get('interest_rate'))
            current_interest = float(legacy_obj.interest_rate or 0)
            if parsed_interest is not None and float(parsed_interest) != current_interest:
                legacy_obj.interest_rate = parsed_interest
                changed = True

        if changed:
            legacy_obj.save()
        return changed

    actor = request.user.get_full_name() or request.user.username or 'User'
    edit_line = f"Follow Up Edit by {actor}: {edit_remark}" if edit_remark else ''

    try:
        loan = LoanApplication.objects.select_related('applicant', 'assigned_employee', 'assigned_agent').get(id=loan_id)
        related_legacy = find_related_loan(loan)

        if not _is_authorized_follow_up_editor(request.user, loan_app=loan, legacy_loan=related_legacy):
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        if not _is_case_edit_allowed_application(loan):
            return Response({
                'success': False,
                'error': 'Editing is available only for Banking Processing, Follow Up, and Approved applications.',
            }, status=status.HTTP_400_BAD_REQUEST)

        applicant_changed = _apply_applicant_updates(loan.applicant)
        legacy_changed = _apply_legacy_updates(related_legacy) if related_legacy else False

        note_changed = False
        if edit_line:
            loan.approval_notes = _append_note_line(loan.approval_notes, edit_line)
            loan.save(update_fields=['approval_notes', 'updated_at'])
            note_changed = True
            if related_legacy:
                related_legacy.remarks = _append_note_line(related_legacy.remarks, edit_line)
                related_legacy.save(update_fields=['remarks', 'updated_at'])

        if not any([applicant_changed, legacy_changed, note_changed]):
            return Response({
                'success': False,
                'error': 'No changes detected. Please update details or add remark.',
            }, status=status.HTTP_400_BAD_REQUEST)

        history_reason = edit_line or f'Case details updated by {actor}'
        LoanStatusHistory.objects.create(
            loan_application=loan,
            from_status='new_entry' if loan.status == 'New Entry' else 'waiting',
            to_status='waiting',
            changed_by=request.user,
            reason=history_reason,
            is_auto_triggered=False,
        )

        return Response({
            'success': True,
            'message': 'Case details updated successfully.',
            'status_display': FOLLOW_UP_PENDING_LABEL,
            'follow_up_pending': True,
        }, status=status.HTTP_200_OK)

    except LoanApplication.DoesNotExist:
        try:
            legacy = Loan.objects.select_related('assigned_employee', 'assigned_agent').get(id=loan_id)
            related_app = find_related_loan_application(legacy)

            if not _is_authorized_follow_up_editor(request.user, loan_app=related_app, legacy_loan=legacy):
                return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

            if not _is_case_edit_allowed_legacy(legacy):
                return Response({
                    'success': False,
                    'error': 'Editing is available only for Banking Processing, Follow Up, and Approved applications.',
                }, status=status.HTTP_400_BAD_REQUEST)

            legacy_changed = _apply_legacy_updates(legacy)
            applicant_changed = False
            if related_app and related_app.applicant:
                applicant_changed = _apply_applicant_updates(related_app.applicant)

            note_changed = False
            if edit_line:
                legacy.remarks = _append_note_line(legacy.remarks, edit_line)
                legacy.save(update_fields=['remarks', 'updated_at'])
                note_changed = True
                if related_app:
                    related_app.approval_notes = _append_note_line(related_app.approval_notes, edit_line)
                    related_app.save(update_fields=['approval_notes', 'updated_at'])

            if not any([legacy_changed, applicant_changed, note_changed]):
                return Response({
                    'success': False,
                    'error': 'No changes detected. Please update details or add remark.',
                }, status=status.HTTP_400_BAD_REQUEST)

            if related_app:
                history_reason = edit_line or f'Case details updated by {actor}'
                LoanStatusHistory.objects.create(
                    loan_application=related_app,
                    from_status=_normalize_history_status(legacy.status),
                    to_status='waiting',
                    changed_by=request.user,
                    reason=history_reason,
                    is_auto_triggered=False,
                )

            return Response({
                'success': True,
                'message': 'Case details updated successfully.',
                'status_display': FOLLOW_UP_PENDING_LABEL,
                'follow_up_pending': True,
            }, status=status.HTTP_200_OK)
        except Loan.DoesNotExist:
            return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_upload_follow_up_document(request, loan_id):
    """
    Upload/replace a document while the case is in Follow Up pending stage.
    Allowed roles: admin, subadmin, assigned employee, assigned agent.
    """
    document_file = request.FILES.get('document_file') or request.FILES.get('file')
    document_type = str(request.data.get('document_type', '')).strip()
    document_name = str(request.data.get('document_name', '')).strip()
    requested_document_type = document_name or document_type

    if not document_file:
        return Response({'success': False, 'error': 'Please choose a document file.'}, status=status.HTTP_400_BAD_REQUEST)
    if not requested_document_type:
        return Response({'success': False, 'error': 'Document name is required.'}, status=status.HTTP_400_BAD_REQUEST)

    def _resolve_document_type(raw_type, valid_types, existing_qs):
        cleaned = str(raw_type or '').strip()
        if not cleaned:
            return None, None, False
        cleaned = cleaned[:50]
        if cleaned in valid_types:
            return cleaned, cleaned, True

        candidate = cleaned
        suffix_index = 2
        while existing_qs.filter(document_type=candidate).exists():
            suffix = f" ({suffix_index})"
            candidate = f"{cleaned[:max(1, 50 - len(suffix))]}{suffix}"
            suffix_index += 1
        return candidate, cleaned, False

    try:
        loan = LoanApplication.objects.select_related('assigned_employee', 'assigned_agent').get(id=loan_id)
        related_legacy = find_related_loan(loan)

        if not _is_authorized_follow_up_editor(request.user, loan_app=loan, legacy_loan=related_legacy):
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        if not _is_follow_up_pending_application(loan):
            return Response({
                'success': False,
                'error': 'Documents can be uploaded only in Follow Up stage.',
            }, status=status.HTTP_400_BAD_REQUEST)

        valid_types = {value for value, _ in ApplicantDocument.DOCUMENT_TYPE_CHOICES}
        resolved_type, display_name, is_standard_type = _resolve_document_type(
            requested_document_type,
            valid_types,
            ApplicantDocument.objects.filter(loan_application=loan),
        )
        if not resolved_type:
            return Response({
                'success': False,
                'error': 'Document name is invalid.',
            }, status=status.HTTP_400_BAD_REQUEST)

        if is_standard_type:
            doc, _ = ApplicantDocument.objects.update_or_create(
                loan_application=loan,
                document_type=resolved_type,
                defaults={
                    'file': document_file,
                    'is_required': False,
                }
            )
        else:
            doc = ApplicantDocument.objects.create(
                loan_application=loan,
                document_type=resolved_type,
                file=document_file,
                is_required=False,
            )

        return Response({
            'success': True,
            'message': 'Document uploaded successfully.',
            'document': {
                'id': doc.id,
                'document_type': doc.document_type,
                'document_type_display': display_name if not is_standard_type else doc.get_document_type_display(),
                'file_url': doc.file.url if doc.file else '',
                'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else '',
            },
        }, status=status.HTTP_200_OK)

    except LoanApplication.DoesNotExist:
        try:
            legacy = Loan.objects.select_related('assigned_employee', 'assigned_agent').get(id=loan_id)
            related_app = find_related_loan_application(legacy)

            if not _is_authorized_follow_up_editor(request.user, loan_app=related_app, legacy_loan=legacy):
                return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
            if not _is_follow_up_pending_legacy(legacy):
                return Response({
                    'success': False,
                    'error': 'Documents can be uploaded only in Follow Up stage.',
                }, status=status.HTTP_400_BAD_REQUEST)

            valid_types = {value for value, _ in LoanDocument.DOCUMENT_TYPE_CHOICES}
            resolved_type, display_name, is_standard_type = _resolve_document_type(
                requested_document_type,
                valid_types,
                LoanDocument.objects.filter(loan=legacy),
            )
            if not resolved_type:
                return Response({
                    'success': False,
                    'error': 'Document name is invalid.',
                }, status=status.HTTP_400_BAD_REQUEST)

            if is_standard_type:
                doc, _ = LoanDocument.objects.update_or_create(
                    loan=legacy,
                    document_type=resolved_type,
                    defaults={
                        'file': document_file,
                        'is_required': False,
                    }
                )
            else:
                doc = LoanDocument.objects.create(
                    loan=legacy,
                    document_type=resolved_type,
                    file=document_file,
                    is_required=False,
                )

            return Response({
                'success': True,
                'message': 'Document uploaded successfully.',
                'document': {
                    'id': doc.id,
                    'document_type': doc.document_type,
                    'document_type_display': display_name if not is_standard_type else doc.get_document_type_display(),
                    'file_url': doc.file.url if doc.file else '',
                    'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else '',
                },
            }, status=status.HTTP_200_OK)
        except Loan.DoesNotExist:
            return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_collect_for_banking(request, loan_id):
    """
    Move application from New Entry/Document Pending/Follow Up to Banking Processing.
    Allowed roles: employee (assigned), subadmin, admin.
    """
    try:
        payload = request.data or {}
        preferred_source = _normalize_entity_source(payload)
        loan_app = LoanApplication.objects.filter(id=loan_id).first()
        legacy = Loan.objects.filter(id=loan_id).first()
        banking_note = _build_banking_processing_note(payload)

        def _source_order():
            if preferred_source == 'legacy':
                return ['legacy', 'application']
            return ['application', 'legacy']

        def _can_process_application():
            return (
                loan_app
                and _is_authorized_processor(request.user, loan_app)
                and loan_app.status in ['New Entry', 'Waiting for Processing', BANKING_PROCESS_STATUS]
            )

        def _can_process_legacy():
            return (
                legacy
                and _is_authorized_processor(request.user, legacy)
                and legacy.status in ['new_entry', 'waiting', 'follow_up']
            )

        def _process_application():
            previous_status = loan_app.status
            loan_app.status = BANKING_PROCESS_STATUS
            if not loan_app.assigned_at:
                loan_app.assigned_at = timezone.now()
            loan_app.follow_up_scheduled_at = timezone.now()
            loan_app.follow_up_notified_at = timezone.now()
            loan_app.follow_up_count = (loan_app.follow_up_count or 0) + 1
            loan_app.is_sm_signed = False
            loan_app.sm_signed_at = None
            loan_app.approval_notes = _append_note_line(loan_app.approval_notes, banking_note)
            loan_app.save(update_fields=[
                'status',
                'assigned_at',
                'follow_up_scheduled_at',
                'follow_up_notified_at',
                'follow_up_count',
                'is_sm_signed',
                'sm_signed_at',
                'approval_notes',
                'updated_at',
            ])

            LoanStatusHistory.objects.create(
                loan_application=loan_app,
                from_status='new_entry' if previous_status == 'New Entry' else 'waiting',
                to_status='follow_up',
                changed_by=request.user,
                reason=banking_note,
                is_auto_triggered=False,
            )

            # Keep legacy loan status synchronized when available.
            _append_related_loan_remark(loan_app, banking_note, status_override='follow_up')

            return Response({
                'success': True,
                'message': 'Application moved to Banking Processing',
                'new_status': loan_app.status,
                'status_display': _ui_status_label(loan_app.status),
            }, status=status.HTTP_200_OK)

        def _process_legacy():
            legacy.status = 'follow_up'
            if not legacy.assigned_at:
                legacy.assigned_at = timezone.now()
            legacy.action_taken_at = timezone.now()
            legacy.is_sm_signed = False
            legacy.sm_signed_at = None
            legacy.remarks = _append_note_line(legacy.remarks, banking_note)
            legacy.save(update_fields=[
                'status',
                'assigned_at',
                'action_taken_at',
                'is_sm_signed',
                'sm_signed_at',
                'remarks',
                'updated_at',
            ])

            synced_application = sync_loan_to_application(
                legacy,
                assigned_by_user=request.user,
                create_if_missing=True,
            )
            if synced_application:
                app_previous_status = synced_application.status
                synced_application.status = BANKING_PROCESS_STATUS
                synced_application.is_sm_signed = False
                synced_application.sm_signed_at = None
                synced_application.follow_up_scheduled_at = timezone.now()
                synced_application.follow_up_notified_at = timezone.now()
                synced_application.follow_up_count = (synced_application.follow_up_count or 0) + 1
                if not synced_application.assigned_at:
                    synced_application.assigned_at = timezone.now()
                synced_application.approval_notes = _append_note_line(
                    synced_application.approval_notes,
                    banking_note,
                )
                synced_application.save(
                    update_fields=[
                        'status',
                        'assigned_at',
                        'is_sm_signed',
                        'sm_signed_at',
                        'follow_up_scheduled_at',
                        'follow_up_notified_at',
                        'follow_up_count',
                        'approval_notes',
                        'updated_at',
                    ]
                )
                LoanStatusHistory.objects.create(
                    loan_application=synced_application,
                    from_status='new_entry' if app_previous_status == 'New Entry' else 'waiting',
                    to_status='follow_up',
                    changed_by=request.user,
                    reason=banking_note,
                    is_auto_triggered=False,
                )

            return Response({
                'success': True,
                'message': 'Application moved to Banking Processing',
                'new_status': 'Required Follow-up',
                'status_display': 'Banking Processing',
            }, status=status.HTTP_200_OK)

        for source in _source_order():
            if source == 'application' and _can_process_application():
                return _process_application()
            if source == 'legacy' and _can_process_legacy():
                return _process_legacy()

        for source in _source_order():
            if source == 'application' and loan_app and _is_authorized_processor(request.user, loan_app):
                return Response({
                    'success': False,
                    'error': f'Collect is allowed only in New Entry or Waiting for Processing. Current status: {loan_app.status}.'
                }, status=status.HTTP_400_BAD_REQUEST)
            if source == 'legacy' and legacy and _is_authorized_processor(request.user, legacy):
                return Response({
                    'success': False,
                    'error': f'Collect is allowed only in new_entry or waiting status. Current status: {legacy.status}.'
                }, status=status.HTTP_400_BAD_REQUEST)

        if loan_app or legacy:
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_move_to_document_pending(request, loan_id):
    """
    Move loan to Document Pending with mandatory remark.
    Supports New Entry and Follow Up correction loops.
    """
    try:
        payload = request.data or {}
        preferred_source = _normalize_entity_source(payload)
        remark = str(payload.get('remark', '')).strip()
        if not remark:
            return Response({
                'success': False,
                'error': 'Remark is required to move into Document Pending.'
            }, status=status.HTTP_400_BAD_REQUEST)

        loan_app = LoanApplication.objects.filter(id=loan_id).first()
        legacy = Loan.objects.filter(id=loan_id).first()
        note_line = _build_document_pending_note(remark, request.user)

        def _source_order():
            if preferred_source == 'legacy':
                return ['legacy', 'application']
            return ['application', 'legacy']

        def _can_process_application():
            return (
                loan_app
                and _is_authorized_processor(request.user, loan_app)
                and loan_app.status in ['New Entry', 'Waiting for Processing', BANKING_PROCESS_STATUS]
            )

        def _can_process_legacy():
            return (
                legacy
                and _is_authorized_processor(request.user, legacy)
                and legacy.status in ['new_entry', 'waiting', 'follow_up']
            )

        def _process_application():
            previous_status = loan_app.status
            loan_app.status = 'Waiting for Processing'
            if not loan_app.assigned_at:
                loan_app.assigned_at = timezone.now()
            loan_app.is_sm_signed = False
            loan_app.sm_signed_at = None
            loan_app.approval_notes = _append_note_line(
                _strip_revert_markers(loan_app.approval_notes),
                note_line,
            )
            loan_app.save(update_fields=[
                'status',
                'assigned_at',
                'is_sm_signed',
                'sm_signed_at',
                'approval_notes',
                'updated_at',
            ])

            LoanStatusHistory.objects.create(
                loan_application=loan_app,
                from_status=(
                    'new_entry'
                    if previous_status == 'New Entry'
                    else ('follow_up' if previous_status == BANKING_PROCESS_STATUS else 'waiting')
                ),
                to_status='waiting',
                changed_by=request.user,
                reason=note_line,
                is_auto_triggered=False,
            )

            related_loan = find_related_loan(loan_app)
            if related_loan:
                related_loan.status = 'waiting'
                if not related_loan.assigned_at:
                    related_loan.assigned_at = timezone.now()
                related_loan.requires_follow_up = False
                related_loan.is_sm_signed = False
                related_loan.sm_signed_at = None
                related_loan.remarks = _append_note_line(
                    _strip_revert_markers(related_loan.remarks),
                    note_line,
                )
                related_loan.save(update_fields=[
                    'status',
                    'assigned_at',
                    'requires_follow_up',
                    'is_sm_signed',
                    'sm_signed_at',
                    'remarks',
                    'updated_at',
                ])

            return Response({
                'success': True,
                'message': 'Application moved to Document Pending.',
                'new_status': loan_app.status,
                'status_display': _ui_status_label(loan_app.status),
                'follow_up_pending': False,
            }, status=status.HTTP_200_OK)

        def _process_legacy():
            previous_status = legacy.status
            legacy.status = 'waiting'
            if not legacy.assigned_at:
                legacy.assigned_at = timezone.now()
            legacy.requires_follow_up = False
            legacy.is_sm_signed = False
            legacy.sm_signed_at = None
            legacy.remarks = _append_note_line(
                _strip_revert_markers(legacy.remarks),
                note_line,
            )
            legacy.save(update_fields=[
                'status',
                'assigned_at',
                'requires_follow_up',
                'is_sm_signed',
                'sm_signed_at',
                'remarks',
                'updated_at',
            ])

            synced_application = sync_loan_to_application(
                legacy,
                assigned_by_user=request.user,
                create_if_missing=True,
            )
            if synced_application:
                previous_app_status = synced_application.status
                synced_application.status = 'Waiting for Processing'
                if not synced_application.assigned_at:
                    synced_application.assigned_at = timezone.now()
                synced_application.is_sm_signed = False
                synced_application.sm_signed_at = None
                synced_application.approval_notes = _append_note_line(
                    _strip_revert_markers(synced_application.approval_notes),
                    note_line,
                )
                synced_application.save(update_fields=[
                    'status',
                    'assigned_at',
                    'is_sm_signed',
                    'sm_signed_at',
                    'approval_notes',
                    'updated_at',
                ])
                LoanStatusHistory.objects.create(
                    loan_application=synced_application,
                    from_status=(
                        'new_entry'
                        if previous_app_status == 'New Entry'
                        else ('follow_up' if previous_app_status == BANKING_PROCESS_STATUS else 'waiting')
                    ),
                    to_status='waiting',
                    changed_by=request.user,
                    reason=note_line,
                    is_auto_triggered=False,
                )
            else:
                synced_application = find_related_loan_application(legacy)

            return Response({
                'success': True,
                'message': 'Application moved to Document Pending.',
                'new_status': 'Waiting for Processing',
                'status_display': _ui_status_label('Waiting for Processing'),
                'follow_up_pending': False,
            }, status=status.HTTP_200_OK)

        for source in _source_order():
            if source == 'application' and _can_process_application():
                return _process_application()
            if source == 'legacy' and _can_process_legacy():
                return _process_legacy()

        for source in _source_order():
            if source == 'application' and loan_app and _is_authorized_processor(request.user, loan_app):
                return Response({
                    'success': False,
                    'error': f'Document Pending move is allowed only in New Entry/Document Pending/Banking Processing. Current status: {loan_app.status}.'
                }, status=status.HTTP_400_BAD_REQUEST)
            if source == 'legacy' and legacy and _is_authorized_processor(request.user, legacy):
                return Response({
                    'success': False,
                    'error': f'Document Pending move is allowed only in new_entry/waiting/follow_up. Current status: {legacy.status}.'
                }, status=status.HTTP_400_BAD_REQUEST)

        if loan_app or legacy:
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_revert_loan_to_agent(request, loan_id):
    """
    Revert application from Banking Processing back to Agent for correction.
    Creates numbered remark history entries (Revert Remark 1, 2, ...).
    """
    try:
        payload = request.data or {}
        preferred_source = _normalize_entity_source(payload)
        loan_app = LoanApplication.objects.filter(id=loan_id).first()
        legacy = Loan.objects.filter(id=loan_id).first()

        revert_remark = str(payload.get('revert_remark', '')).strip()
        if not revert_remark:
            return Response({
                'success': False,
                'error': 'Revert remark is required.'
            }, status=status.HTTP_400_BAD_REQUEST)

        def _source_order():
            if preferred_source == 'legacy':
                return ['legacy', 'application']
            return ['application', 'legacy']

        def _can_process_application():
            return (
                loan_app
                and _is_authorized_processor(request.user, loan_app)
                and loan_app.status == BANKING_PROCESS_STATUS
            )

        def _can_process_legacy():
            return (
                legacy
                and _is_authorized_processor(request.user, legacy)
                and legacy.status == 'follow_up'
            )

        def _process_application():
            revert_index = _next_revert_index_from_history(loan_app)
            revert_reason = f"Revert Remark {revert_index}: {revert_remark}"

            previous_status = loan_app.status
            loan_app.status = 'Waiting for Processing'
            loan_app.is_sm_signed = False
            loan_app.sm_signed_at = None
            loan_app.approval_notes = _append_note_line(loan_app.approval_notes, revert_reason)
            loan_app.save(update_fields=['status', 'is_sm_signed', 'sm_signed_at', 'approval_notes', 'updated_at'])

            LoanStatusHistory.objects.create(
                loan_application=loan_app,
                from_status='follow_up' if previous_status == BANKING_PROCESS_STATUS else 'waiting',
                to_status='waiting',
                changed_by=request.user,
                reason=revert_reason,
                is_auto_triggered=False,
            )

            _append_related_loan_remark(loan_app, revert_reason, status_override='waiting')

            return Response({
                'success': True,
                'message': 'Application moved to Follow Up for correction.',
                'new_status': loan_app.status,
                'status_display': _ui_status_label(loan_app.status, follow_up_pending=True),
                'follow_up_pending': True,
                'revert_reason': revert_reason,
            }, status=status.HTTP_200_OK)

        def _process_legacy():
            revert_count = 0
            for line in str(legacy.remarks or '').splitlines():
                if str(line).strip().lower().startswith('revert remark '):
                    revert_count += 1
            revert_reason = f"Revert Remark {revert_count + 1}: {revert_remark}"

            previous_status = legacy.status
            legacy.status = 'waiting'
            legacy.is_sm_signed = False
            legacy.sm_signed_at = None
            legacy.remarks = _append_note_line(legacy.remarks, revert_reason)
            legacy.save()

            synced_application = sync_loan_to_application(
                legacy,
                assigned_by_user=request.user,
                create_if_missing=True,
            )
            if synced_application:
                # Ensure workflow side also carries revert marker so auto follow-up
                # automation does not move this record back to Banking Processing.
                synced_application.status = 'Waiting for Processing'
                synced_application.is_sm_signed = False
                synced_application.sm_signed_at = None
                synced_application.approval_notes = _append_note_line(
                    synced_application.approval_notes,
                    revert_reason,
                )
                synced_application.follow_up_notified_at = timezone.now()
                synced_application.save(
                    update_fields=[
                        'status',
                        'is_sm_signed',
                        'sm_signed_at',
                        'approval_notes',
                        'follow_up_notified_at',
                        'updated_at',
                    ]
                )

                LoanStatusHistory.objects.create(
                    loan_application=synced_application,
                    from_status=_normalize_history_status(previous_status),
                    to_status='waiting',
                    changed_by=request.user,
                    reason=revert_reason,
                    is_auto_triggered=False,
                )

            return Response({
                'success': True,
                'message': 'Application moved to Follow Up for correction.',
                'new_status': 'Waiting for Processing',
                'status_display': FOLLOW_UP_PENDING_LABEL,
                'follow_up_pending': True,
                'revert_reason': revert_reason,
            }, status=status.HTTP_200_OK)

        for source in _source_order():
            if source == 'application' and _can_process_application():
                return _process_application()
            if source == 'legacy' and _can_process_legacy():
                return _process_legacy()

        for source in _source_order():
            if source == 'application' and loan_app and _is_authorized_processor(request.user, loan_app):
                return Response({
                    'success': False,
                    'error': f'Revert is allowed only in Banking Processing. Current status: {loan_app.status}.'
                }, status=status.HTTP_400_BAD_REQUEST)
            if source == 'legacy' and legacy and _is_authorized_processor(request.user, legacy):
                return Response({
                    'success': False,
                    'error': f'Revert is allowed only in Banking Processing. Current status: {legacy.status}.'
                }, status=status.HTTP_400_BAD_REQUEST)

        if loan_app or legacy:
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_sign_off_loan(request, loan_id):
    """
    Tick/sign action on Approved loan before final disbursement.
    Accepts marking signature as done (`is_sm_signed=true`) or not done (`is_sm_signed=false`).
    """
    try:
        requested = request.data or {}
        preferred_source = _normalize_entity_source(requested)
        loan_app = LoanApplication.objects.filter(id=loan_id).first()
        legacy = Loan.objects.filter(id=loan_id).first()

        def _source_order():
            if preferred_source == 'legacy':
                return ['legacy', 'application']
            return ['application', 'legacy']

        def _parse_bool(value, default=True):
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}

        def _can_process_application():
            return (
                loan_app
                and _is_authorized_processor(request.user, loan_app)
                and loan_app.status == 'Approved'
            )

        def _can_process_legacy():
            return (
                legacy
                and _is_authorized_processor(request.user, legacy)
                and legacy.status == 'approved'
            )

        def _process_application():
            sm_errors = _validate_sm_details(
                (loan_app.sm_name or '').strip(),
                (loan_app.sm_phone_number or '').strip(),
                (loan_app.sm_email or '').strip(),
            )
            if sm_errors:
                return Response({'success': False, 'error': ' '.join(sm_errors)}, status=status.HTTP_400_BAD_REQUEST)

            signature_done_raw = requested.get('is_sm_signed', requested.get('signature_done', None))
            signature_done = _parse_bool(signature_done_raw, default=True)
            bank_remark = str(requested.get('bank_remark', '')).strip()

            signer = request.user.get_full_name() or request.user.username or 'System'
            sign_reason = f"SM Signature Done: {'Yes' if signature_done else 'No'} (by {signer})"
            bank_remark_reason = f"Bank Remark: {bank_remark}" if bank_remark else ''
            sign_reason_with_remark = (
                _append_note_line(sign_reason, bank_remark_reason)
                if bank_remark_reason
                else sign_reason
            )

            prev = bool(loan_app.is_sm_signed)
            if signature_done:
                if not prev:
                    loan_app.is_sm_signed = True
                    loan_app.sm_signed_at = timezone.now()
                    loan_app.approval_notes = _append_note_line(loan_app.approval_notes, sign_reason_with_remark)
                    loan_app.save(update_fields=['is_sm_signed', 'sm_signed_at', 'approval_notes', 'updated_at'])

                    LoanStatusHistory.objects.create(
                        loan_application=loan_app,
                        from_status='approved',
                        to_status='approved',
                        changed_by=request.user,
                        reason=sign_reason_with_remark,
                        is_auto_triggered=False,
                    )

                    _append_related_loan_remark(loan_app, sign_reason_with_remark, status_override='approved')
                elif bank_remark_reason:
                    loan_app.approval_notes = _append_note_line(loan_app.approval_notes, bank_remark_reason)
                    loan_app.save(update_fields=['approval_notes', 'updated_at'])
                    _append_related_loan_remark(loan_app, bank_remark_reason, status_override='approved')
            else:
                if prev:
                    loan_app.is_sm_signed = False
                    loan_app.sm_signed_at = None
                    loan_app.approval_notes = _append_note_line(loan_app.approval_notes, sign_reason_with_remark)
                    loan_app.save(update_fields=['is_sm_signed', 'sm_signed_at', 'approval_notes', 'updated_at'])
                elif bank_remark_reason:
                    loan_app.approval_notes = _append_note_line(loan_app.approval_notes, bank_remark_reason)
                    loan_app.save(update_fields=['approval_notes', 'updated_at'])
                    _append_related_loan_remark(loan_app, bank_remark_reason, status_override='approved')

            return Response({
                'success': True,
                'message': 'Approved signature updated successfully.',
                'is_sm_signed': bool(loan_app.is_sm_signed),
                'sm_signed_at': loan_app.sm_signed_at.strftime('%Y-%m-%d %H:%M') if loan_app.sm_signed_at else '',
            }, status=status.HTTP_200_OK)

        def _process_legacy():
            sm_errors = _validate_sm_details(
                (legacy.sm_name or '').strip(),
                (legacy.sm_phone_number or '').strip(),
                (legacy.sm_email or '').strip(),
            )
            if sm_errors:
                return Response({'success': False, 'error': ' '.join(sm_errors)}, status=status.HTTP_400_BAD_REQUEST)

            signature_done_raw = requested.get('is_sm_signed', requested.get('signature_done', None))
            signature_done = _parse_bool(signature_done_raw, default=True)
            bank_remark = str(requested.get('bank_remark', '')).strip()

            signer = request.user.get_full_name() or request.user.username or 'System'
            sign_reason = f"SM Signature Done: {'Yes' if signature_done else 'No'} (by {signer})"
            bank_remark_reason = f"Bank Remark: {bank_remark}" if bank_remark else ''
            sign_reason_with_remark = (
                _append_note_line(sign_reason, bank_remark_reason)
                if bank_remark_reason
                else sign_reason
            )

            prev = bool(getattr(legacy, 'is_sm_signed', False))
            if signature_done:
                if not prev:
                    legacy.is_sm_signed = True
                    legacy.sm_signed_at = timezone.now()
                    legacy.remarks = _append_note_line(legacy.remarks, sign_reason_with_remark)
                    legacy.save()
                elif bank_remark_reason:
                    legacy.remarks = _append_note_line(legacy.remarks, bank_remark_reason)
                    legacy.save()
            else:
                if prev:
                    legacy.is_sm_signed = False
                    legacy.sm_signed_at = None
                    legacy.remarks = _append_note_line(legacy.remarks, sign_reason_with_remark)
                    legacy.save()
                elif bank_remark_reason:
                    legacy.remarks = _append_note_line(legacy.remarks, bank_remark_reason)
                    legacy.save()

            synced_application = sync_loan_to_application(
                legacy,
                assigned_by_user=request.user,
                create_if_missing=True,
            )
            if synced_application and signature_done and not prev:
                LoanStatusHistory.objects.create(
                    loan_application=synced_application,
                    from_status='approved',
                    to_status='approved',
                    changed_by=request.user,
                    reason=sign_reason_with_remark,
                    is_auto_triggered=False,
                )

            return Response({
                'success': True,
                'message': 'Approved signature updated successfully.',
                'is_sm_signed': bool(getattr(legacy, 'is_sm_signed', False)),
                'sm_signed_at': legacy.sm_signed_at.strftime('%Y-%m-%d %H:%M') if legacy.sm_signed_at else '',
            }, status=status.HTTP_200_OK)

        for source in _source_order():
            if source == 'application' and _can_process_application():
                return _process_application()
            if source == 'legacy' and _can_process_legacy():
                return _process_legacy()

        for source in _source_order():
            if source == 'application' and loan_app and _is_authorized_processor(request.user, loan_app):
                return Response({
                    'success': False,
                    'error': f'Sign is allowed only in Approved status. Current status: {loan_app.status}.'
                }, status=status.HTTP_400_BAD_REQUEST)
            if source == 'legacy' and legacy and _is_authorized_processor(request.user, legacy):
                return Response({
                    'success': False,
                    'error': f'Sign is allowed only in Approved status. Current status: {legacy.status}.'
                }, status=status.HTTP_400_BAD_REQUEST)

        if loan_app or legacy:
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_approve_loan(request, loan_id):
    """
    Approve loan from Banking Processing stage.
    Channel partner / leader / signature fields are optional and ignored.
    """
    try:
        payload = request.data or {}
        bank_remark = str(payload.get('bank_remark', '')).strip()
        approval_notes = str(payload.get('approval_notes', '')).strip()
        approval_reason = _append_note_line(
            approval_notes,
            f"Bank Remark: {bank_remark}" if bank_remark else '',
        ).strip() or 'Approved after banking verification'

        try:
            loan = LoanApplication.objects.get(id=loan_id)
            if not _is_authorized_processor(request.user, loan):
                return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
            if loan.status != BANKING_PROCESS_STATUS:
                return Response({
                    'success': False,
                    'error': f'Loan status is {loan.status}. Can only approve from Banking Processing.'
                }, status=status.HTTP_400_BAD_REQUEST)

            previous_status = loan.status
            loan.status = 'Approved'
            loan.approved_by = request.user
            loan.approved_at = timezone.now()
            loan.approval_notes = _append_note_line(
                _strip_revert_markers(loan.approval_notes),
                approval_reason,
            )
            loan.sm_name = None
            loan.sm_phone_number = None
            loan.sm_email = None
            loan.is_sm_signed = False
            loan.sm_signed_at = None
            loan.save(update_fields=[
                'status',
                'approved_by',
                'approved_at',
                'approval_notes',
                'sm_name',
                'sm_phone_number',
                'sm_email',
                'is_sm_signed',
                'sm_signed_at',
                'updated_at',
            ])

            LoanStatusHistory.objects.create(
                loan_application=loan,
                from_status='follow_up' if previous_status == BANKING_PROCESS_STATUS else 'waiting',
                to_status='approved',
                changed_by=request.user,
                reason=approval_reason,
                is_auto_triggered=False,
            )

            _append_related_loan_remark(loan, approval_reason, status_override='approved')

            return Response({
                'success': True,
                'message': 'Loan approved successfully',
                'new_status': 'Approved',
                'status_display': _ui_status_label('Approved'),
            }, status=status.HTTP_200_OK)

        except LoanApplication.DoesNotExist:
            legacy = Loan.objects.get(id=loan_id)
            if not _is_authorized_processor(request.user, legacy):
                return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
            if legacy.status != 'follow_up':
                return Response({
                    'success': False,
                    'error': f'Loan status is {legacy.status}. Can only approve from Banking Processing.'
                }, status=status.HTTP_400_BAD_REQUEST)

            previous_status = legacy.status
            legacy.status = 'approved'
            legacy.action_taken_at = timezone.now()
            legacy.is_sm_signed = False
            legacy.sm_signed_at = None
            legacy.sm_name = None
            legacy.sm_phone_number = None
            legacy.sm_email = None
            legacy.remarks = _append_note_line(
                _strip_revert_markers(legacy.remarks),
                approval_reason,
            )
            legacy.save(update_fields=[
                'status',
                'action_taken_at',
                'is_sm_signed',
                'sm_signed_at',
                'sm_name',
                'sm_phone_number',
                'sm_email',
                'remarks',
                'updated_at',
            ])

            synced_application = sync_loan_to_application(
                legacy,
                assigned_by_user=request.user,
                create_if_missing=True,
            )
            if synced_application:
                LoanStatusHistory.objects.create(
                    loan_application=synced_application,
                    from_status=_normalize_history_status(previous_status),
                    to_status='approved',
                    changed_by=request.user,
                    reason=approval_reason,
                    is_auto_triggered=False,
                )

            return Response({
                'success': True,
                'message': 'Loan approved successfully',
                'new_status': 'Approved',
                'status_display': _ui_status_label('Approved'),
            }, status=status.HTTP_200_OK)
    except Loan.DoesNotExist:
        return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_reject_loan(request, loan_id):
    """
    Employee rejects a loan assigned to them
    Updates status to 'Rejected' and notifies agent & admin
    """
    try:
        payload = request.data or {}
        preferred_source = _normalize_entity_source(payload)
        loan_app = LoanApplication.objects.filter(id=loan_id).first()
        legacy = Loan.objects.filter(id=loan_id).first()

        rejection_reason = str(payload.get('rejection_reason', '')).strip()
        if not rejection_reason:
            return Response({
                'success': False,
                'error': 'Rejection reason is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        bank_remark = str(payload.get('bank_remark', '')).strip()
        full_reason = rejection_reason if not bank_remark else f"{rejection_reason}\nBank Remark: {bank_remark}"

        def _source_order():
            if preferred_source == 'legacy':
                return ['legacy', 'application']
            return ['application', 'legacy']

        def _can_process_application():
            return (
                loan_app
                and _is_authorized_processor(request.user, loan_app)
                and loan_app.status in ['Waiting for Processing', BANKING_PROCESS_STATUS, 'Approved']
            )

        def _can_process_legacy():
            return (
                legacy
                and _is_authorized_processor(request.user, legacy)
                and legacy.status in ['waiting', 'follow_up', 'approved']
            )

        def _process_application():
            previous_status = loan_app.status
            loan_app.status = 'Rejected'
            loan_app.rejected_by = request.user
            loan_app.rejected_at = timezone.now()
            loan_app.rejection_reason = full_reason
            loan_app.is_sm_signed = False
            loan_app.sm_signed_at = None
            loan_app.save(update_fields=[
                'status',
                'rejected_by',
                'rejected_at',
                'rejection_reason',
                'is_sm_signed',
                'sm_signed_at',
                'updated_at',
            ])

            LoanStatusHistory.objects.create(
                loan_application=loan_app,
                from_status='follow_up' if previous_status == BANKING_PROCESS_STATUS else ('approved' if previous_status == 'Approved' else 'waiting'),
                to_status='rejected',
                changed_by=request.user,
                reason=full_reason,
                is_auto_triggered=False,
            )

            return Response({
                'success': True,
                'message': 'Loan rejected successfully',
                'new_status': 'Rejected',
                'status_display': _ui_status_label('Rejected'),
            }, status=status.HTTP_200_OK)

        def _process_legacy():
            previous_status = legacy.status
            legacy.status = 'rejected'
            legacy.action_taken_at = timezone.now()
            legacy.is_sm_signed = False
            legacy.sm_signed_at = None
            legacy.remarks = _append_bank_remark(legacy.remarks, full_reason)
            legacy.save()

            synced_application = sync_loan_to_application(
                legacy,
                assigned_by_user=request.user,
                create_if_missing=True,
            )
            if synced_application:
                LoanStatusHistory.objects.create(
                    loan_application=synced_application,
                    from_status=_normalize_history_status(previous_status),
                    to_status='rejected',
                    changed_by=request.user,
                    reason=full_reason,
                    is_auto_triggered=False,
                )

            return Response({
                'success': True,
                'message': 'Loan rejected successfully',
                'new_status': 'Rejected',
                'status_display': 'Rejected',
            }, status=status.HTTP_200_OK)

        for source in _source_order():
            if source == 'application' and _can_process_application():
                return _process_application()
            if source == 'legacy' and _can_process_legacy():
                return _process_legacy()

        for source in _source_order():
            if source == 'application' and loan_app and _is_authorized_processor(request.user, loan_app):
                return Response({
                    'success': False,
                    'error': f'Loan status is {loan_app.status}. Can only reject from Waiting/Banking Processing/Approved.'
                }, status=status.HTTP_400_BAD_REQUEST)
            if source == 'legacy' and legacy and _is_authorized_processor(request.user, legacy):
                return Response({
                    'success': False,
                    'error': f'Loan status is {legacy.status}. Can only reject from Waiting/Banking Processing/Approved.'
                }, status=status.HTTP_400_BAD_REQUEST)

        if loan_app or legacy:
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_disburse_loan(request, loan_id):
    """
    Employee marks a loan as disbursed
    Updates status to 'Disbursed' with amount and date
    Notifies agent & admin
    """
    try:
        payload = request.data or {}
        preferred_source = _normalize_entity_source(payload)
        loan_app = LoanApplication.objects.filter(id=loan_id).first()
        legacy = Loan.objects.filter(id=loan_id).first()

        disbursement_amount_raw = payload.get('disbursement_amount')
        disbursement_date_raw = payload.get('disbursement_date')
        disbursement_notes = str(payload.get('disbursement_notes') or payload.get('bank_remark') or '').strip()
        payload_sm_phone = str(payload.get('sm_phone_number') or payload.get('sm_phone') or '').strip()
        payload_sm_email = str(payload.get('sm_email') or '').strip()

        def _source_order():
            if preferred_source == 'legacy':
                return ['legacy', 'application']
            return ['application', 'legacy']

        def _can_process_application():
            return (
                loan_app
                and _is_authorized_processor(request.user, loan_app)
                and loan_app.status == 'Approved'
            )

        def _can_process_legacy():
            return (
                legacy
                and _is_authorized_processor(request.user, legacy)
                and legacy.status == 'approved'
            )

        def _process_application():
            applicant = loan_app.applicant
            disbursement_amount = disbursement_amount_raw
            disbursement_date = disbursement_date_raw
            if not disbursement_amount:
                disbursement_amount = float(applicant.loan_amount or 0)
            if not disbursement_date:
                disbursement_date = timezone.now().date().strftime('%Y-%m-%d')

            try:
                disbursement_amount = float(disbursement_amount)
                disbursement_date = datetime.strptime(disbursement_date, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                return Response({
                    'success': False,
                    'error': 'Invalid disbursement amount or date'
                }, status=status.HTTP_400_BAD_REQUEST)

            if disbursement_amount > float(applicant.loan_amount or 0):
                return Response({
                    'success': False,
                    'error': f'Disbursement amount cannot exceed loan amount ({applicant.loan_amount})'
                }, status=status.HTTP_400_BAD_REQUEST)

            sm_phone = (payload_sm_phone or (loan_app.sm_phone_number or '')).strip()
            sm_email = (payload_sm_email or (loan_app.sm_email or '')).strip()
            if not sm_phone:
                return Response({'success': False, 'error': 'SM phone number is required.'}, status=status.HTTP_400_BAD_REQUEST)
            sm_digits = re.sub(r'\D', '', sm_phone)
            if len(sm_digits) < 10 or len(sm_digits) > 15:
                return Response({'success': False, 'error': 'Enter a valid SM phone number (10-15 digits).'}, status=status.HTTP_400_BAD_REQUEST)
            if not sm_email or '@' not in sm_email:
                return Response({'success': False, 'error': 'Enter a valid SM email.'}, status=status.HTTP_400_BAD_REQUEST)

            previous_status = loan_app.status
            loan_app.status = 'Disbursed'
            loan_app.disbursed_by = request.user
            disbursed_at_dt = datetime.combine(disbursement_date, datetime.min.time())
            try:
                disbursed_at_dt = timezone.make_aware(disbursed_at_dt, timezone.get_current_timezone())
            except Exception:
                pass
            loan_app.disbursed_at = disbursed_at_dt
            loan_app.disbursement_amount = disbursement_amount
            reason_lines = [
                f'Disbursed amount: {disbursement_amount}',
                f'Disbursement Date: {disbursement_date.strftime("%Y-%m-%d")}',
            ]
            if disbursement_notes:
                reason_lines.append(f'Disbursement Notes: {disbursement_notes}')
            disburse_reason = '\n'.join(reason_lines)
            loan_app.approval_notes = _append_note_line(loan_app.approval_notes, disburse_reason)
            update_fields = [
                'status',
                'disbursed_by',
                'disbursed_at',
                'disbursement_amount',
                'approval_notes',
            ]
            if payload_sm_phone and loan_app.sm_phone_number != sm_phone:
                loan_app.sm_phone_number = sm_phone
                update_fields.append('sm_phone_number')
            if payload_sm_email and loan_app.sm_email != sm_email:
                loan_app.sm_email = sm_email
                update_fields.append('sm_email')
            loan_app.save(update_fields=update_fields + ['updated_at'])

            LoanStatusHistory.objects.create(
                loan_application=loan_app,
                from_status='follow_up' if previous_status == BANKING_PROCESS_STATUS else 'approved',
                to_status='disbursed',
                changed_by=request.user,
                reason=disburse_reason,
                is_auto_triggered=False,
            )

            _append_related_loan_remark(loan_app, disburse_reason, status_override='disbursed')

            return Response({
                'success': True,
                'message': 'Loan marked as disbursed successfully',
                'new_status': 'Disbursed',
                'disbursement_amount': float(disbursement_amount),
                'disbursement_date': disbursement_date.strftime('%Y-%m-%d'),
                'status_display': _ui_status_label('Disbursed'),
            }, status=status.HTTP_200_OK)

        def _process_legacy():
            disbursement_amount = disbursement_amount_raw
            if not disbursement_amount:
                disbursement_amount = float(legacy.loan_amount or 0)
            try:
                disbursement_amount = float(disbursement_amount)
            except (TypeError, ValueError):
                return Response({'success': False, 'error': 'Invalid disbursement amount'}, status=status.HTTP_400_BAD_REQUEST)

            if disbursement_amount > float(legacy.loan_amount or 0):
                return Response({
                    'success': False,
                    'error': f'Disbursement amount cannot exceed loan amount ({legacy.loan_amount})'
                }, status=status.HTTP_400_BAD_REQUEST)

            disbursement_date = disbursement_date_raw
            if not disbursement_date:
                disbursement_date = timezone.now().date().strftime('%Y-%m-%d')
            try:
                disbursement_date = datetime.strptime(disbursement_date, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                return Response({'success': False, 'error': 'Invalid disbursement date. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)

            sm_phone = (payload_sm_phone or (legacy.sm_phone_number or '')).strip()
            sm_email = (payload_sm_email or (legacy.sm_email or '')).strip()
            if not sm_phone:
                return Response({'success': False, 'error': 'SM phone number is required.'}, status=status.HTTP_400_BAD_REQUEST)
            sm_digits = re.sub(r'\D', '', sm_phone)
            if len(sm_digits) < 10 or len(sm_digits) > 15:
                return Response({'success': False, 'error': 'Enter a valid SM phone number (10-15 digits).'}, status=status.HTTP_400_BAD_REQUEST)
            if not sm_email or '@' not in sm_email:
                return Response({'success': False, 'error': 'Enter a valid SM email.'}, status=status.HTTP_400_BAD_REQUEST)

            previous_status = legacy.status
            legacy.status = 'disbursed'
            legacy.action_taken_at = timezone.now()
            reason_lines = [
                f'Disbursed amount: {disbursement_amount}',
                f'Disbursement Date: {disbursement_date.strftime("%Y-%m-%d")}',
            ]
            if disbursement_notes:
                reason_lines.append(f'Disbursement Notes: {disbursement_notes}')
            disburse_reason = '\n'.join(reason_lines)
            if payload_sm_phone:
                legacy.sm_phone_number = sm_phone
            if payload_sm_email:
                legacy.sm_email = sm_email
            legacy.remarks = _append_note_line(legacy.remarks, disburse_reason)
            legacy.save()

            synced_application = sync_loan_to_application(
                legacy,
                assigned_by_user=request.user,
                create_if_missing=True,
            )
            if synced_application:
                app_update_fields = []
                disbursed_at_dt = datetime.combine(disbursement_date, datetime.min.time())
                try:
                    disbursed_at_dt = timezone.make_aware(disbursed_at_dt, timezone.get_current_timezone())
                except Exception:
                    pass

                if synced_application.disbursed_by_id != request.user.id:
                    synced_application.disbursed_by = request.user
                    app_update_fields.append('disbursed_by')
                if synced_application.disbursed_at != disbursed_at_dt:
                    synced_application.disbursed_at = disbursed_at_dt
                    app_update_fields.append('disbursed_at')
                if synced_application.disbursement_amount != disbursement_amount:
                    synced_application.disbursement_amount = disbursement_amount
                    app_update_fields.append('disbursement_amount')
                approval_notes = _append_note_line(synced_application.approval_notes, disburse_reason)
                if synced_application.approval_notes != approval_notes:
                    synced_application.approval_notes = approval_notes
                    app_update_fields.append('approval_notes')

                if app_update_fields:
                    synced_application._skip_sync_to_loan = True
                    synced_application.save(update_fields=app_update_fields + ['updated_at'])

                LoanStatusHistory.objects.create(
                    loan_application=synced_application,
                    from_status=_normalize_history_status(previous_status),
                    to_status='disbursed',
                    changed_by=request.user,
                    reason=disburse_reason,
                    is_auto_triggered=False,
                )

            return Response({
                'success': True,
                'message': 'Loan marked as disbursed successfully',
                'new_status': 'Disbursed',
                'disbursement_amount': float(disbursement_amount),
                'disbursement_date': disbursement_date.strftime('%Y-%m-%d'),
                'status_display': 'Disbursed',
            }, status=status.HTTP_200_OK)

        for source in _source_order():
            if source == 'application' and _can_process_application():
                return _process_application()
            if source == 'legacy' and _can_process_legacy():
                return _process_legacy()

        for source in _source_order():
            if source == 'application' and loan_app and _is_authorized_processor(request.user, loan_app):
                return Response({
                    'success': False,
                    'error': f'Loan status is {loan_app.status}. Can only disburse from Approved status.'
                }, status=status.HTTP_400_BAD_REQUEST)
            if source == 'legacy' and legacy and _is_authorized_processor(request.user, legacy):
                return Response({
                    'success': False,
                    'error': f'Loan status is {legacy.status}. Can only disburse from Approved status.'
                }, status=status.HTTP_400_BAD_REQUEST)

        if loan_app or legacy:
            return Response({'success': False, 'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
