from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncMonth, TruncDay
from django.utils import timezone
from datetime import datetime, timedelta
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import User, Agent, Loan, Complaint, ComplaintComment, ActivityLog, LoanDocument, Applicant, LoanApplication, ApplicantDocument, SubAdminEntry, EmployeeProfile
from .serializers import (
    UserSerializer, AgentSerializer, LoanSerializer,
    ComplaintSerializer, ComplaintCommentSerializer,
    ActivityLogSerializer, DashboardStatsSerializer, LoanDocumentSerializer,
    ApplicantDocumentSerializer, ApplicantSerializer, LoanApplicationSerializer
)
from .decorators import admin_required, employee_required
from .forms import ApplicantStep1Form, ApplicantStep2Form, DocumentUploadForm
from .permissions import IsAdminUser, IsEmployeeUser, IsAgentUser, IsLoanOwnerOrAdmin


# Authentication Views
def login_view(request):
    if request.user.is_authenticated:
        # Redirect based on role
        if request.user.role == 'admin':
            return redirect('admin_all_loans')
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
        
        if user is not None and user.is_active:
            login(request, user)
            # Redirect based on role
            if user.role == 'admin':
                return redirect('admin_all_loans')
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
            return redirect('admin_all_loans')
        elif request.user.role == 'subadmin':
            return redirect('/subadmin/dashboard/')
    
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
                    return redirect('admin_all_loans')
                else:
                    return redirect('/subadmin/dashboard/')
            else:
                messages.error(request, 'Unauthorized access. Admin/SubAdmin privileges required.')
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
    
    employees = User.objects.filter(role='employee')
    
    # Count data for each employee
    employee_loans_count = {}
    employee_approved_count = {}
    
    for employee in employees:
        employee_loans_count[employee.id] = Loan.objects.filter(assigned_employee=employee).count()
        employee_approved_count[employee.id] = Loan.objects.filter(
            assigned_employee=employee,
            status='approved'
        ).count()
    
    context = {
        'employees': employees,
        'employee_loans_count': employee_loans_count,
        'employee_approved_count': employee_approved_count,
    }
    
    return render(request, 'core/admin/employees_list.html', context)


@login_required
def admin_all_agents(request):
    """View all agents"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    agents = Agent.objects.all()
    
    context = {
        'agents': agents,
    }
    
    return render(request, 'core/admin/agents_list.html', context)


@login_required
def admin_new_entries(request):
    """View New Entry loans"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    loans = Loan.objects.filter(status='new_entry').select_related('assigned_employee').order_by('-created_at')
    
    context = {
        'loans': loans,
        'status_name': 'New Entry',
        'status_icon': 'fa-file-alt',
        'status_color': '#667eea',
    }
    
    return render(request, 'core/admin/admin_loan_status_list.html', context)


@login_required
def admin_in_processing(request):
    """View In Processing loans"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    loans = Loan.objects.filter(status='in_processing').select_related('assigned_employee').order_by('-created_at')
    
    context = {
        'loans': loans,
        'status_name': 'In Processing',
        'status_icon': 'fa-hourglass-half',
        'status_color': '#f5576c',
    }
    
    return render(request, 'core/admin/admin_loan_status_list.html', context)


@login_required
def admin_follow_ups(request):
    """View Follow-up loans"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    loans = Loan.objects.filter(status='follow_up').select_related('assigned_employee').order_by('-created_at')
    
    context = {
        'loans': loans,
        'status_name': 'Follow-up',
        'status_icon': 'fa-phone',
        'status_color': '#fa709a',
    }
    
    return render(request, 'core/admin/admin_loan_status_list.html', context)


@login_required
def admin_approved(request):
    """View Approved loans"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    loans = Loan.objects.filter(status='approved').select_related('assigned_employee').order_by('-created_at')
    
    context = {
        'loans': loans,
        'status_name': 'Approved',
        'status_icon': 'fa-check-circle',
        'status_color': '#30cfd0',
    }
    
    return render(request, 'core/admin/admin_loan_status_list.html', context)


@login_required
def admin_rejected(request):
    """View Rejected loans"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    loans = Loan.objects.filter(status='rejected').select_related('assigned_employee').order_by('-created_at')
    
    context = {
        'loans': loans,
        'status_name': 'Rejected',
        'status_icon': 'fa-times-circle',
        'status_color': '#ff6b6b',
    }
    
    return render(request, 'core/admin/admin_loan_status_list.html', context)


@login_required
def admin_disbursed(request):
    """View Disbursed loans"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    loans = Loan.objects.filter(status='disbursed').select_related('assigned_employee').order_by('-created_at')
    
    context = {
        'loans': loans,
        'status_name': 'Disbursed',
        'status_icon': 'fa-money-bill-wave',
        'status_color': '#11998e',
    }
    
    return render(request, 'core/admin/admin_loan_status_list.html', context)


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
def admin_reports(request):
    """Admin Reports page"""
    if request.user.role != 'admin':
        return redirect('dashboard')
    
    total_loans = Loan.objects.count()
    total_amount = Loan.objects.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    approved_count = Loan.objects.filter(status='approved').count()
    rejected_count = Loan.objects.filter(status='rejected').count()
    
    context = {
        'total_loans': total_loans,
        'total_amount': total_amount,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
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
            {'success': True, 'message': 'SubAdmin created successfully', 'id': user.id},
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
                'message': f'SubAdmin {subadmin.get_full_name()} has been {status_text}',
                'subadmin_id': subadmin_id,
                'new_status': subadmin.is_active,
                'old_status': old_status
            },
            status=status.HTTP_200_OK
        )
    
    except User.DoesNotExist:
        return Response(
            {'success': False, 'message': 'SubAdmin not found'},
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
        
        if username and password:
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
    """Multi-step registration wizard for Employee/Agent"""
    from .forms import ApplicantStep1Form, ApplicantStep2Form, DocumentUploadForm
    
    session_key = f'applicant_{role}'
    
    # Get or create applicant data in session
    applicant_data = request.session.get(session_key, {})
    
    if request.method == 'POST':
        if step == 1:
            form = ApplicantStep1Form(request.POST)
            if form.is_valid():
                # Save Step 1 data to session
                applicant_data = {
                    'role': form.cleaned_data['role'],
                    'full_name': form.cleaned_data['full_name'],
                    'username': form.cleaned_data['username'],
                    'mobile': form.cleaned_data['mobile'],
                    'email': form.cleaned_data['email'],
                    'city': form.cleaned_data['city'],
                    'state': form.cleaned_data['state'],
                    'pin_code': form.cleaned_data['pin_code'],
                    'gender': form.cleaned_data['gender'],
                }
                request.session[session_key] = applicant_data
                return redirect(f'/register/{role}/step/2/')
        
        elif step == 2:
            form = ApplicantStep2Form(request.POST)
            if form.is_valid():
                # Save Step 2 data to session
                applicant_data.update({
                    'loan_type': form.cleaned_data['loan_type'],
                    'loan_amount': str(form.cleaned_data['loan_amount']),
                    'tenure_months': form.cleaned_data['tenure_months'],
                    'interest_rate': str(form.cleaned_data['interest_rate']),
                    'loan_purpose': form.cleaned_data['loan_purpose'],
                    'bank_name': form.cleaned_data['bank_name'],
                    'bank_type': form.cleaned_data['bank_type'],
                    'account_number': form.cleaned_data['account_number'],
                    'ifsc_code': form.cleaned_data['ifsc_code'],
                })
                request.session[session_key] = applicant_data
                return redirect(f'/register/{role}/step/3/')
        
        elif step == 3:
            form = DocumentUploadForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    # Create Applicant
                    applicant = Applicant.objects.create(**applicant_data)
                    
                    # Create LoanApplication
                    loan_app = LoanApplication.objects.create(applicant=applicant)
                    
                    # Save documents
                    document_mapping = {
                        'photo': 'photo',
                        'pan_front': 'pan_front',
                        'pan_back': 'pan_back',
                        'aadhaar_front': 'aadhaar_front',
                        'aadhaar_back': 'aadhaar_back',
                        'permanent_address': 'permanent_address',
                        'current_address': 'current_address',
                        'salary_slip': 'salary_slip',
                        'bank_statement': 'bank_statement',
                        'form_16': 'form_16',
                        'service_book': 'service_book',
                    }
                    
                    for field_name, doc_type in document_mapping.items():
                        if field_name in request.FILES:
                            ApplicantDocument.objects.create(
                                loan_application=loan_app,
                                document_type=doc_type,
                                file=request.FILES[field_name],
                                is_required=field_name in ['photo', 'pan_front', 'pan_back', 'aadhaar_front', 'aadhaar_back', 'permanent_address']
                            )
                    
                    # Clear session
                    del request.session[session_key]
                    request.session.modified = True
                    
                    return redirect(f'/register/{role}/step/4/?applicant_id={applicant.id}')
                
                except Exception as e:
                    # Handle duplicate username or other errors
                    if 'username' in str(e).lower():
                        messages.error(request, 'Username already exists. Please choose a different username.')
                    else:
                        messages.error(request, f'Error during registration: {str(e)}')
                    # Go back to step 1 to re-enter data
                    return redirect(f'/register/{role}/step/1/')
        
        elif step == 4:
            applicant_id = request.GET.get('applicant_id')
            applicant = Applicant.objects.get(id=applicant_id)
            
            # Mark as submitted
            loan_app = applicant.loan_application
            loan_app.status = 'New Entry'
            loan_app.save()
            
            # Log activity
            ActivityLog.objects.create(
                action='loan_added',
                description=f"New {applicant.role.title()} application from {applicant.full_name}",
            )
            
            messages.success(request, 'Application submitted successfully! Your application has been added to the New Entries list.')
            
            # Clear session if it exists
            if session_key in request.session:
                del request.session[session_key]
                request.session.modified = True
            
            return redirect('new_entries')
    
    else:
        if step == 1:
            form = ApplicantStep1Form(initial={'role': role})
        elif step == 2:
            form = ApplicantStep2Form(initial=applicant_data)
        elif step == 3:
            form = DocumentUploadForm()
        elif step == 4:
            # Get applicant from URL parameter
            applicant_id = request.GET.get('applicant_id')
            if applicant_id:
                applicant = Applicant.objects.get(id=applicant_id)
                applicant_data = {
                    'full_name': applicant.full_name,
                    'role': applicant.role,
                    'mobile': applicant.mobile,
                    'email': applicant.email,
                    'city': applicant.city,
                    'state': applicant.state,
                    'loan_type': applicant.loan_type,
                    'loan_amount': applicant.loan_amount,
                    'tenure_months': applicant.tenure_months,
                    'interest_rate': applicant.interest_rate,
                    'bank_name': applicant.bank_name,
                    'account_number': applicant.account_number,
                }
            form = None
        else:
            form = None
    
    context = {
        'form': form,
        'step': step,
        'role': role,
        'progress': (step - 1) * 25,
        'applicant_data': applicant_data,
    }
    
    return render(request, 'core/registration_wizard.html', context)


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
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    employees = User.objects.filter(role='employee', is_active=True).values('id', 'username', 'first_name', 'last_name', 'email')
    return Response(list(employees))


@api_view(['GET'])
@login_required
def get_agents_list(request):
    """Get list of agents for assignment"""
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    agents = Agent.objects.filter(status='active').values('id', 'name', 'phone', 'email')
    return Response(list(agents))


@api_view(['POST'])
@login_required
def assign_to_employee(request, applicant_id):
    """Assign application to employee"""
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        employee_id = request.data.get('employee_id')
        
        employee = User.objects.get(id=employee_id, role='employee', is_active=True)
        loan_app.assigned_employee = employee
        loan_app.status = 'Waiting for Processing'
        loan_app.assigned_at = timezone.now()
        loan_app.assigned_by = request.user
        loan_app.save()
        
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
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        agent_id = request.data.get('agent_id')
        
        agent = Agent.objects.get(id=agent_id, status='active')
        loan_app.assigned_agent = agent
        loan_app.status = 'Waiting for Processing'
        loan_app.assigned_at = timezone.now()
        loan_app.assigned_by = request.user
        loan_app.save()
        
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
            ).count(),  # Will be calculated based on 24-hour rule
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
    """Manually trigger follow-up (admin only)"""
    if request.user.role != 'admin':
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        applicant = Applicant.objects.get(id=applicant_id)
        loan_app = applicant.loan_application
        
        if loan_app.status != 'Waiting for Processing':
            return Response({
                'error': f'Can only trigger follow-up for Waiting applications. Current status: {loan_app.status}'
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
            'message': 'Follow-up triggered successfully',
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
            description=f"Status changed {old_status} → {new_status} for {applicant.full_name}. Reason: {reason}",
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
            'is_overdue': app.hours_since_assignment > 24 if app.hours_since_assignment else False,
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
@permission_classes([IsEmployeeUser])
def employee_dashboard_stats(request):
    """
    Get employee dashboard statistics - Real-time data
    Only accessible by employee users
    Returns count of loans assigned to current employee by status
    """
    try:
        # Get all applications assigned to this employee
        assignments = LoanApplication.objects.filter(assigned_employee=request.user)
        
        stats = {
            'success': True,
            'total_assigned': assignments.count(),
            'processing': assignments.filter(status='Waiting for Processing').count(),
            'approved': assignments.filter(status='Approved').count(),
            'rejected': assignments.filter(status='Rejected').count(),
            'follow_up': assignments.filter(status='Required Follow-up').count(),
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
        messages.error(request, '❌ You do not have permission to access this form.')
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
                messages.error(request, '❌ You do not have permission to view this loan.')
                return redirect('dashboard')
            elif request.user.role == 'employee' and loan.assigned_to != request.user:
                messages.error(request, '❌ You do not have permission to view this loan.')
                return redirect('dashboard')
        
        return render(request, 'core/loan_detail.html', {'loan': loan})
    
    except Exception as e:
        messages.error(request, f'❌ Loan not found: {str(e)}')
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
        'page_title': 'Waiting for Processing'
    })


@admin_required
def loan_followup_view(request):
    """Required Follow-up - Loans with 24h+ no action"""
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
        new_entry_count = LoanApplication.objects.filter(status='New Entry').count()
        waiting_count = LoanApplication.objects.filter(status='Waiting for Processing').count()
        
        # Follow-up: loans assigned > 24h ago with no action
        followup_cutoff = now - timedelta(hours=24)
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
    - Assignment logic: On assign → status changes to 'Waiting for Processing', assigned_employee set, assigned_at recorded
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
    return render(request, 'core/employee/request_new_entry_loan.html')


@api_view(['GET'])
@permission_classes([IsEmployeeUser])
def employee_assigned_loans_list(request):
    """
    Get list of all loans assigned to employee with filters
    Returns table data for Request New Entry Loan page
    """
    try:
        # Get filter parameters
        status = request.GET.get('status', '').strip()
        from_date = request.GET.get('from_date', '').strip()
        to_date = request.GET.get('to_date', '').strip()
        page = int(request.GET.get('page', 1))
        limit = int(request.GET.get('limit', 20))
        
        # Base queryset - all loans assigned to current employee
        queryset = LoanApplication.objects.filter(
            assigned_employee=request.user
        ).select_related('applicant', 'assigned_by').order_by('-assigned_at')
        
        # Apply filters
        if status:
            queryset = queryset.filter(status=status)
        
        if from_date:
            try:
                from_date_obj = datetime.strptime(from_date, '%Y-%m-%d')
                queryset = queryset.filter(assigned_at__gte=from_date_obj)
            except:
                pass
        
        if to_date:
            try:
                to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                to_date_obj = to_date_obj.replace(hour=23, minute=59, second=59)
                queryset = queryset.filter(assigned_at__lte=to_date_obj)
            except:
                pass
        
        # Pagination
        paginator = Paginator(queryset, limit)
        page_obj = paginator.get_page(page)
        
        # Build response
        loans_data = []
        for loan in page_obj:
            applicant = loan.applicant
            hours_since = (timezone.now() - loan.assigned_at).total_seconds() / 3600 if loan.assigned_at else 0
            
            loans_data.append({
                'applicant_id': applicant.id,
                'applicant_name': applicant.full_name,
                'mobile': applicant.mobile,
                'email': applicant.email,
                'city': applicant.city,
                'loan_type': applicant.loan_type or 'N/A',
                'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                'loan_purpose': applicant.loan_purpose or 'N/A',
                'status': loan.status,
                'assigned_date': loan.assigned_at.strftime('%Y-%m-%d') if loan.assigned_at else '',
                'assigned_by_name': loan.assigned_by.get_full_name() if loan.assigned_by else 'System',
                'hours_since_assignment': round(hours_since, 1),
            })
        
        return Response({
            'success': True,
            'loans': loans_data,
            'total': queryset.count(),
            'page': page,
            'total_pages': paginator.num_pages,
            'per_page': limit,
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsEmployeeUser])
def employee_assigned_loan_detail(request, loan_id):
    """
    Get full details of a loan assigned to employee (read-only)
    """
    try:
        loan = LoanApplication.objects.get(id=loan_id, assigned_employee=request.user)
        applicant = loan.applicant
        
        loan_data = {
            'id': loan.id,
            'applicant_id': applicant.id,
            'applicant_name': applicant.full_name,
            'mobile': applicant.mobile,
            'email': applicant.email,
            'city': applicant.city,
            'state': applicant.state,
            'pin_code': applicant.pin_code,
            'permanent_address': applicant.permanent_address,
            'current_address': applicant.current_address,
            'loan_type': applicant.loan_type,
            'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
            'loan_purpose': applicant.loan_purpose,
            'status': loan.status,
            'assigned_date': loan.assigned_at.strftime('%Y-%m-%d %H:%M') if loan.assigned_at else '',
            'assigned_by_name': loan.assigned_by.get_full_name() if loan.assigned_by else 'System',
            'approval_notes': loan.approval_notes or '',
            'rejection_reason': loan.rejection_reason or '',
        }
        
        return Response({
            'success': True,
            'loan': loan_data,
        }, status=status.HTTP_200_OK)
    
    except LoanApplication.DoesNotExist:
        return Response({'success': False, 'error': 'Loan not found or not assigned to you'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsEmployeeUser])
def employee_approve_loan(request, loan_id):
    """
    Employee approves a loan assigned to them
    Updates status to 'Approved' and notifies agent & admin
    """
    try:
        # Get loan and verify it's assigned to employee
        loan = LoanApplication.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify loan status is Waiting for Processing
        if loan.status != 'Waiting for Processing':
            return Response({
                'success': False,
                'error': f'Loan status is {loan.status}. Can only approve loans in "Waiting for Processing" status.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update loan
        approval_notes = request.data.get('approval_notes', '').strip()
        loan.status = 'Approved'
        loan.approved_by = request.user
        loan.approved_at = timezone.now()
        loan.approval_notes = approval_notes
        loan.save()
        
        # TODO: Send notification to agent and admin
        
        return Response({
            'success': True,
            'message': 'Loan approved successfully',
            'new_status': 'Approved',
        }, status=status.HTTP_200_OK)
    
    except LoanApplication.DoesNotExist:
        return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsEmployeeUser])
def employee_reject_loan(request, loan_id):
    """
    Employee rejects a loan assigned to them
    Updates status to 'Rejected' and notifies agent & admin
    """
    try:
        # Get loan and verify it's assigned to employee
        loan = LoanApplication.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify loan status is Waiting for Processing
        if loan.status != 'Waiting for Processing':
            return Response({
                'success': False,
                'error': f'Loan status is {loan.status}. Can only reject loans in "Waiting for Processing" status.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get rejection reason (required)
        rejection_reason = request.data.get('rejection_reason', '').strip()
        if not rejection_reason:
            return Response({
                'success': False,
                'error': 'Rejection reason is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update loan
        loan.status = 'Rejected'
        loan.rejected_by = request.user
        loan.rejected_at = timezone.now()
        loan.rejection_reason = rejection_reason
        loan.save()
        
        # TODO: Send notification to agent and admin
        
        return Response({
            'success': True,
            'message': 'Loan rejected successfully',
            'new_status': 'Rejected',
        }, status=status.HTTP_200_OK)
    
    except LoanApplication.DoesNotExist:
        return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsEmployeeUser])
def employee_disburse_loan(request, loan_id):
    """
    Employee marks a loan as disbursed
    Updates status to 'Disbursed' with amount and date
    Notifies agent & admin
    """
    try:
        # Get loan and verify it's assigned to employee
        loan = LoanApplication.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify loan status is Waiting for Processing
        if loan.status != 'Waiting for Processing':
            return Response({
                'success': False,
                'error': f'Loan status is {loan.status}. Can only disburse loans in "Waiting for Processing" status.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get disbursement details
        disbursement_amount = request.data.get('disbursement_amount')
        disbursement_date = request.data.get('disbursement_date')
        
        if not disbursement_amount or not disbursement_date:
            return Response({
                'success': False,
                'error': 'Disbursement amount and date are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            disbursement_amount = float(disbursement_amount)
            disbursement_date = datetime.strptime(disbursement_date, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return Response({
                'success': False,
                'error': 'Invalid disbursement amount or date'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Verify amount doesn't exceed loan amount
        applicant = loan.applicant
        if disbursement_amount > float(applicant.loan_amount or 0):
            return Response({
                'success': False,
                'error': f'Disbursement amount cannot exceed loan amount (₹{applicant.loan_amount})'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update loan
        loan.status = 'Disbursed'
        loan.disbursed_by = request.user
        loan.disbursed_at = timezone.now()
        loan.disbursement_amount = disbursement_amount
        loan.save()
        
        # TODO: Send notification to agent and admin
        
        return Response({
            'success': True,
            'message': 'Loan marked as disbursed successfully',
            'new_status': 'Disbursed',
            'disbursement_amount': float(disbursement_amount),
            'disbursement_date': disbursement_date.strftime('%Y-%m-%d'),
        }, status=status.HTTP_200_OK)
    
    except LoanApplication.DoesNotExist:
        return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
