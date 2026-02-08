"""
SubAdmin Panel Views - Production-Grade Implementation
Provides complete visibility and management for SubAdmin role
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum, F, Prefetch, Value, CharField
from django.db.models.functions import Concat
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from .decorators import subadmin_required
from .models import User, LoanApplication, Complaint, SubAdminEntry, Loan, LoanStatusHistory, Agent, LoanDocument
from django.utils import timezone
from datetime import timedelta
import json
import logging

logger = logging.getLogger(__name__)


# ============ DASHBOARD ============

@login_required(login_url='login')
@subadmin_required
def subadmin_dashboard(request):
    """
    SubAdmin Dashboard - Overview of all managed loans and team
    Shows:
    - Total loans by status
    - Team metrics (agents, employees)
    - Recent activities
    - Quick action cards
    """
    user = request.user
    
    # Get all loans (SubAdmin has visibility to all)
    all_loans = Loan.objects.all().select_related('assigned_employee', 'assigned_agent')
    
    # Calculate statistics
    total_loans = all_loans.count()
    
    # Loan status breakdown
    status_stats = {
        'total': total_loans,
        'new_entry': all_loans.filter(status='new_entry').count(),
        'waiting': all_loans.filter(status='waiting').count(),
        'follow_up': all_loans.filter(status='follow_up').count(),
        'approved': all_loans.filter(status='approved').count(),
        'rejected': all_loans.filter(status='rejected').count(),
        'disbursed': all_loans.filter(status='disbursed').count(),
    }
    
    # Calculate percentages
    total_for_percent = total_loans if total_loans > 0 else 1
    status_stats['new_entry_pct'] = int((status_stats['new_entry'] / total_for_percent) * 100)
    status_stats['waiting_pct'] = int((status_stats['waiting'] / total_for_percent) * 100)
    status_stats['follow_up_pct'] = int((status_stats['follow_up'] / total_for_percent) * 100)
    status_stats['approved_pct'] = int((status_stats['approved'] / total_for_percent) * 100)
    status_stats['rejected_pct'] = int((status_stats['rejected'] / total_for_percent) * 100)
    status_stats['disbursed_pct'] = int((status_stats['disbursed'] / total_for_percent) * 100)
    
    # Loan amount statistics
    status_stats['total_value'] = all_loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    status_stats['approved_value'] = all_loans.filter(status='approved').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    status_stats['disbursed_value'] = all_loans.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    
    # Team statistics
    active_agents = Agent.objects.filter(status='active').count()
    all_agents = Agent.objects.count()
    active_employees = User.objects.filter(role='employee', is_active=True).count()
    all_employees = User.objects.filter(role='employee').count()
    
    team_stats = {
        'active_agents': active_agents,
        'all_agents': all_agents,
        'active_employees': active_employees,
        'all_employees': all_employees,
        'total_team': active_agents + active_employees,
    }
    
    # Monthly loan trend (last 6 months)
    from datetime import datetime, timedelta
    monthly_data = []
    for i in range(5, -1, -1):
        start_date = timezone.now().replace(day=1) - timedelta(days=30*i)
        end_date = start_date + timedelta(days=30)
        
        month_loans = all_loans.filter(
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        
        monthly_data.append({
            'month': start_date.strftime('%b %Y'),
            'total': month_loans.count(),
            'approved': month_loans.filter(status='approved').count(),
            'disbursed': month_loans.filter(status='disbursed').count(),
        })
    
    context = {
        'page_title': 'SubAdmin Dashboard',
        'status_stats': status_stats,
        'team_stats': team_stats,
        'monthly_data': monthly_data,
    }
    
    return render(request, 'core/subadmin/dashboard.html', context)


@login_required(login_url='login')
@subadmin_required
@require_http_methods(['GET'])
def api_subadmin_dashboard_stats(request):
    """
    SubAdmin Dashboard Stats API
    Returns JSON with dashboard statistics for dynamic loading
    """
    try:
        # Get all loans (SubAdmin has visibility to all)
        all_loans = Loan.objects.all()
        
        # Loan status breakdown
        status_stats = {
            'total': all_loans.count(),
            'new_entry': all_loans.filter(status='new_entry').count(),
            'waiting': all_loans.filter(status='waiting').count(),
            'follow_up': all_loans.filter(status='follow_up').count(),
            'approved': all_loans.filter(status='approved').count(),
            'rejected': all_loans.filter(status='rejected').count(),
            'disbursed': all_loans.filter(status='disbursed').count(),
        }
        
        # Calculate percentages
        total_for_percent = status_stats['total'] if status_stats['total'] > 0 else 1
        status_stats['new_entry_pct'] = int((status_stats['new_entry'] / total_for_percent) * 100)
        status_stats['waiting_pct'] = int((status_stats['waiting'] / total_for_percent) * 100)
        status_stats['follow_up_pct'] = int((status_stats['follow_up'] / total_for_percent) * 100)
        status_stats['approved_pct'] = int((status_stats['approved'] / total_for_percent) * 100)
        status_stats['rejected_pct'] = int((status_stats['rejected'] / total_for_percent) * 100)
        status_stats['disbursed_pct'] = int((status_stats['disbursed'] / total_for_percent) * 100)
        
        # Loan amount statistics
        status_stats['total_value'] = all_loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
        
        # Team statistics
        active_agents = Agent.objects.filter(status='active').count()
        all_agents = Agent.objects.count()
        active_employees = User.objects.filter(role='employee', is_active=True).count()
        all_employees = User.objects.filter(role='employee').count()
        
        team_stats = {
            'active_agents': active_agents,
            'all_agents': all_agents,
            'active_employees': active_employees,
            'all_employees': all_employees,
            'total_team': active_agents + active_employees,
        }
        
        return JsonResponse({
            'success': True,
            'status_stats': status_stats,
            'team_stats': team_stats,
        })
    except Exception as e:
        logger.error(f"Error in api_subadmin_dashboard_stats: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


# ============ MY ALL LOANS ============

@login_required(login_url='login')
@subadmin_required
def subadmin_all_loans(request):
    """
    SubAdmin - All Loans Page
    Shows ALL loans in system with advanced filtering
    
    Features:
    - Search by Loan ID, Name, Phone
    - Filter by Status
    - Filter by Agent / Employee
    - Date range filter
    - Sortable columns
    - Real-time counts
    """
    # Start with all loans
    loans_qs = Loan.objects.all().select_related('assigned_employee', 'assigned_agent')
    
    # Apply filters
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    agent_filter = request.GET.get('agent', '')
    employee_filter = request.GET.get('employee', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # Search filter
    if search_query:
        loans_qs = loans_qs.filter(
            Q(full_name__icontains=search_query) |
            Q(mobile_number__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(id__icontains=search_query)
        )
    
    # Status filter
    if status_filter:
        loans_qs = loans_qs.filter(status=status_filter)
    
    # Agent filter
    if agent_filter:
        loans_qs = loans_qs.filter(assigned_agent_id=agent_filter)
    
    # Employee filter
    if employee_filter:
        loans_qs = loans_qs.filter(assigned_employee_id=employee_filter)
    
    # Date range filter
    if date_from:
        try:
            from datetime import datetime
            start_date = datetime.strptime(date_from, '%Y-%m-%d')
            loans_qs = loans_qs.filter(created_at__gte=start_date)
        except:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            end_date = datetime.strptime(date_to, '%Y-%m-%d')
            loans_qs = loans_qs.filter(created_at__lte=end_date)
        except:
            pass
    
    # Order by latest first
    loans_qs = loans_qs.order_by('-created_at')
    
    # Get filter options
    agents = Agent.objects.all().values('id', 'name').distinct()
    employees = User.objects.filter(role='employee').values('id', 'first_name', 'last_name').distinct()
    
    # Real-time counts
    all_loans_count = Loan.objects.count()
    status_counts = {
        'new_entry': Loan.objects.filter(status='new_entry').count(),
        'waiting': Loan.objects.filter(status='waiting').count(),
        'follow_up': Loan.objects.filter(status='follow_up').count(),
        'approved': Loan.objects.filter(status='approved').count(),
        'rejected': Loan.objects.filter(status='rejected').count(),
        'disbursed': Loan.objects.filter(status='disbursed').count(),
    }
    
    # Pagination
    paginator = Paginator(loans_qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Format loans for display
    loans_list = []
    for loan in page_obj:
        loans_list.append({
            'id': loan.id,
            'loan_id': f'LOAN-{loan.id:06d}',
            'applicant_name': loan.full_name,
            'phone': loan.mobile_number,
            'loan_type': loan.loan_type,
            'amount': loan.loan_amount,
            'agent': loan.assigned_agent.name if loan.assigned_agent else 'Unassigned',
            'employee': loan.assigned_employee.get_full_name() if loan.assigned_employee else 'Unassigned',
            'status': loan.status,
            'status_display': loan.get_status_display(),
            'created_date': loan.created_at.strftime('%Y-%m-%d'),
        })
    
    context = {
        'page_title': 'All Loans',
        'loans': loans_list,
        'paginator': paginator,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'total_loans': all_loans_count,
        'status_counts': status_counts,
        'agents': agents,
        'employees': employees,
        'search_query': search_query,
        'status_filter': status_filter,
        'agent_filter': agent_filter,
        'employee_filter': employee_filter,
        'date_from': date_from,
        'date_to': date_to,
    }
    
    return render(request, 'core/subadmin/all_loans.html', context)


# ============ LOAN DETAIL ============

@login_required(login_url='login')
@subadmin_required
def subadmin_loan_detail(request, loan_id):
    """
    SubAdmin Loan Detail Page
    Shows:
    - Full loan application (read-only)
    - All uploaded documents
    - Assignment section (can reassign)
    - Status history timeline
    - Internal remarks
    """
    loan = get_object_or_404(Loan, id=loan_id)
    
    # Get loan documents
    documents = LoanDocument.objects.filter(loan=loan)
    
    # Get status history
    status_history = LoanStatusHistory.objects.filter(loan=loan).order_by('-created_at')
    
    # Format status history for timeline
    history_timeline = []
    for history in status_history:
        history_timeline.append({
            'status': history.status,
            'timestamp': history.created_at,
            'changed_by': history.changed_by.get_full_name() if history.changed_by else 'System',
            'remarks': history.remarks,
        })
    
    # Get available employees for reassignment
    available_employees = User.objects.filter(role='employee', is_active=True)
    
    context = {
        'page_title': f'Loan Detail - {loan.full_name}',
        'loan': loan,
        'documents': documents,
        'history_timeline': history_timeline,
        'available_employees': available_employees,
    }
    
    return render(request, 'core/subadmin/loan_detail.html', context)


@login_required(login_url='login')
@subadmin_required
@require_POST
def subadmin_assign_employee_api(request, loan_id):
    """
    API: Assign/Reassign employee to loan
    """
    try:
        loan = get_object_or_404(Loan, id=loan_id)
        employee_id = request.POST.get('employee_id')
        remarks = request.POST.get('remarks', '')
        
        if not employee_id:
            return JsonResponse({'error': 'Employee ID required'}, status=400)
        
        employee = get_object_or_404(User, id=employee_id, role='employee')
        
        # Update loan assignment
        old_employee = loan.assigned_employee
        loan.assigned_employee = employee
        loan.assigned_at = timezone.now()
        loan.save()
        
        # Create status history
        LoanStatusHistory.objects.create(
            loan=loan,
            status=loan.status,
            changed_by=request.user,
            remarks=f'Reassigned from {old_employee.get_full_name() if old_employee else "Unassigned"} to {employee.get_full_name()} by SubAdmin. {remarks}'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Loan assigned to {employee.get_full_name()}'
        })
    
    except Exception as e:
        logger.error(f"Error assigning employee: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


# ============ MY AGENTS ============

@login_required(login_url='login')
@subadmin_required
def subadmin_my_agents(request):
    """
    SubAdmin - My Agents Page
    Shows ALL agents and sub-agents with stats
    
    Columns:
    - Name
    - Email
    - Phone
    - Created By
    - Total Loans
    - Status
    - Action: View
    """
    agents_qs = Agent.objects.all()
    
    # Search filter
    search_query = request.GET.get('q', '').strip()
    if search_query:
        agents_qs = agents_qs.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    
    # Status filter
    status_filter = request.GET.get('status', '')
    if status_filter:
        agents_qs = agents_qs.filter(status=status_filter)
    
    # Add loan counts
    agents_qs = agents_qs.annotate(
        agent_total_loans=Count('loans'),
        agent_approved_count=Count('loans', filter=Q(loans__status='approved')),
    )
    
    agents_qs = agents_qs.order_by('-created_at')
    
    # Real-time counts
    total_agents = Agent.objects.count()
    active_agents = Agent.objects.filter(status='active').count()
    blocked_agents = Agent.objects.filter(status='blocked').count()
    
    # Pagination
    paginator = Paginator(agents_qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    agents_list = []
    for agent in page_obj:
        agents_list.append({
            'id': agent.id,
            'name': agent.name,
            'email': agent.email or 'N/A',
            'phone': agent.phone,
            'created_by': agent.created_by.get_full_name() if agent.created_by else 'Admin',
            'total_loans': agent.agent_total_loans,
            'approved_count': agent.agent_approved_count,
            'status': agent.status,
            'created_date': agent.created_at.strftime('%Y-%m-%d'),
        })
    
    context = {
        'page_title': 'All Agents',
        'agents': agents_list,
        'paginator': paginator,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'total_agents': total_agents,
        'active_agents': active_agents,
        'blocked_agents': blocked_agents,
        'search_query': search_query,
        'status_filter': status_filter,
    }
    
    return render(request, 'core/subadmin/my_agents.html', context)


@login_required(login_url='login')
@subadmin_required
def subadmin_agent_detail(request, agent_id):
    """
    SubAdmin Agent Detail Page
    Shows:
    - Agent profile
    - Loans submitted by agent
    - Loan status summary
    """
    agent = get_object_or_404(Agent, id=agent_id)
    
    # Get loans from this agent
    loans = Loan.objects.filter(assigned_agent=agent).select_related('assigned_employee')
    
    # Status breakdown
    loan_stats = {
        'total': loans.count(),
        'new_entry': loans.filter(status='new_entry').count(),
        'approved': loans.filter(status='approved').count(),
        'rejected': loans.filter(status='rejected').count(),
        'disbursed': loans.filter(status='disbursed').count(),
    }
    
    # Amount stats
    loan_stats['total_amount'] = loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    loan_stats['disbursed_amount'] = loans.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
    
    context = {
        'page_title': f'Agent Detail - {agent.name}',
        'agent': agent,
        'loan_stats': loan_stats,
        'loans': loans[:10],  # Latest 10
    }
    
    return render(request, 'core/subadmin/agent_detail.html', context)


# ============ MY EMPLOYEES ============

@login_required(login_url='login')
@subadmin_required
def subadmin_my_employees(request):
    """
    SubAdmin - My Employees Page
    Shows ALL employees with performance stats
    
    Columns:
    - Employee ID
    - Name
    - Email
    - Phone
    - Assigned Loans
    - Approved
    - Rejected
    - Status
    - Action: View
    """
    employees_qs = User.objects.filter(role='employee')
    
    # Search filter
    search_query = request.GET.get('q', '').strip()
    if search_query:
        employees_qs = employees_qs.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    
    # Status filter
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        employees_qs = employees_qs.filter(is_active=True)
    elif status_filter == 'inactive':
        employees_qs = employees_qs.filter(is_active=False)
    
    # Add loan counts
    employees_qs = employees_qs.annotate(
        total_assigned_loans=Count('loans_as_employee'),
        total_approved_count=Count('loans_as_employee', filter=Q(loans_as_employee__status='approved')),
        total_rejected_count=Count('loans_as_employee', filter=Q(loans_as_employee__status='rejected')),
    )
    
    employees_qs = employees_qs.order_by('-created_at')
    
    # Real-time counts
    total_employees = User.objects.filter(role='employee').count()
    active_employees = User.objects.filter(role='employee', is_active=True).count()
    
    # Pagination
    paginator = Paginator(employees_qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    employees_list = []
    for emp in page_obj:
        employees_list.append({
            'id': emp.id,
            'employee_id': emp.employee_id or f'EMP{emp.id:04d}',
            'name': emp.get_full_name() or emp.username,
            'email': emp.email,
            'phone': emp.phone or 'N/A',
            'assigned_loans': emp.total_assigned_loans,
            'approved': emp.total_approved_count,
            'rejected': emp.total_rejected_count,
            'status': 'Active' if emp.is_active else 'Inactive',
            'created_date': emp.created_at.strftime('%Y-%m-%d'),
        })
    
    context = {
        'page_title': 'All Employees',
        'employees': employees_list,
        'paginator': paginator,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'total_employees': total_employees,
        'active_employees': active_employees,
        'search_query': search_query,
        'status_filter': status_filter,
    }
    
    return render(request, 'core/subadmin/my_employees.html', context)


@login_required(login_url='login')
@subadmin_required
def subadmin_employee_detail(request, employee_id):
    """
    SubAdmin Employee Detail Page
    Shows:
    - Employee profile
    - Assigned loans
    - Performance summary
    - Agents under this employee (if any)
    """
    employee = get_object_or_404(User, id=employee_id, role='employee')
    
    # Get assigned loans
    loans = Loan.objects.filter(assigned_employee=employee)
    
    # Performance stats
    perf_stats = {
        'total': loans.count(),
        'approved': loans.filter(status='approved').count(),
        'rejected': loans.filter(status='rejected').count(),
        'pending': loans.filter(status__in=['waiting', 'follow_up']).count(),
        'disbursed': loans.filter(status='disbursed').count(),
    }
    
    # Calculate approval rate
    if perf_stats['total'] > 0:
        perf_stats['approval_rate'] = int((perf_stats['approved'] / perf_stats['total']) * 100)
    else:
        perf_stats['approval_rate'] = 0
    
    context = {
        'page_title': f'Employee Detail - {employee.get_full_name()}',
        'employee': employee,
        'perf_stats': perf_stats,
        'loans': loans[:10],  # Latest 10
    }
    
    return render(request, 'core/subadmin/employee_detail.html', context)


# ============ REPORTS ============

@login_required(login_url='login')
@subadmin_required
def subadmin_reports(request):
    """
    SubAdmin Reports Page
    Shows:
    - Loan count by status
    - Monthly disbursement
    - Employee performance
    - Agent performance
    - Charts and analytics
    """
    all_loans = Loan.objects.all()
    
    # Overall statistics
    report_stats = {
        'total_applications': all_loans.count(),
        'total_approved': all_loans.filter(status='approved').count(),
        'total_rejected': all_loans.filter(status='rejected').count(),
        'total_disbursed': all_loans.filter(status='disbursed').count(),
        'total_value': all_loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
        'disbursed_value': all_loans.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
    }
    
    # Calculate approval rate
    if report_stats['total_applications'] > 0:
        report_stats['approval_rate'] = int((report_stats['total_approved'] / report_stats['total_applications']) * 100)
    else:
        report_stats['approval_rate'] = 0
    
    # Employee performance
    top_employees = User.objects.filter(role='employee').annotate(
        emp_total_loans=Count('loans_as_employee'),
        emp_approved_count=Count('loans_as_employee', filter=Q(loans_as_employee__status='approved')),
    ).order_by('-emp_approved_count')[:10]
    
    employee_performance = []
    for emp in top_employees:
        if emp.emp_total_loans > 0:
            rate = int((emp.emp_approved_count / emp.emp_total_loans) * 100)
        else:
            rate = 0
        
        employee_performance.append({
            'name': emp.get_full_name(),
            'total': emp.emp_total_loans,
            'approved': emp.emp_approved_count,
            'rate': rate,
        })
    
    # Agent performance
    top_agents = Agent.objects.annotate(
        agent_total_loans=Count('loans'),
        agent_approved_count=Count('loans', filter=Q(loans__status='approved')),
    ).order_by('-agent_total_loans')[:10]
    
    agent_performance = []
    for agent in top_agents:
        if agent.agent_total_loans > 0:
            rate = int((agent.agent_approved_count / agent.agent_total_loans) * 100)
        else:
            rate = 0
        
        agent_performance.append({
            'name': agent.name,
            'total': agent.agent_total_loans,
            'approved': agent.agent_approved_count,
            'rate': rate,
        })
    
    # Monthly trend
    monthly_trend = []
    for i in range(11, -1, -1):
        month_date = timezone.now() - timedelta(days=30*i)
        month_start = month_date.replace(day=1)
        month_end = (month_date + timedelta(days=30)).replace(day=1)
        
        month_loans = all_loans.filter(created_at__gte=month_start, created_at__lt=month_end)
        
        monthly_trend.append({
            'month': month_start.strftime('%b %Y'),
            'applications': month_loans.count(),
            'approved': month_loans.filter(status='approved').count(),
            'disbursed': month_loans.filter(status='disbursed').count(),
            'value': month_loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
        })
    
    context = {
        'page_title': 'Reports & Analytics',
        'report_stats': report_stats,
        'employee_performance': employee_performance,
        'agent_performance': agent_performance,
        'monthly_trend': monthly_trend,
    }
    
    return render(request, 'core/subadmin/reports.html', context)


# ============ COMPLAINTS ============

@login_required(login_url='login')
@subadmin_required
def subadmin_complaints(request):
    """
    SubAdmin Complaints Page
    Shows:
    - All complaints with status
    - Ability to add remarks
    - Update status
    - Track resolution
    """
    complaints_qs = Complaint.objects.all().select_related('loan')
    
    # Search filter
    search_query = request.GET.get('q', '').strip()
    if search_query:
        complaints_qs = complaints_qs.filter(
            Q(subject__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    # Status filter
    status_filter = request.GET.get('status', '')
    if status_filter:
        complaints_qs = complaints_qs.filter(status=status_filter)
    
    complaints_qs = complaints_qs.order_by('-created_at')
    
    # Status counts
    complaint_counts = {
        'total': Complaint.objects.count(),
        'open': Complaint.objects.filter(status='open').count(),
        'in_progress': Complaint.objects.filter(status='in_progress').count(),
        'resolved': Complaint.objects.filter(status='resolved').count(),
    }
    
    # Pagination
    paginator = Paginator(complaints_qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    complaints_list = []
    for complaint in page_obj:
        complaints_list.append({
            'id': complaint.id,
            'subject': complaint.description,
            'description': complaint.description,
            'status': complaint.status,
            'priority': complaint.priority if hasattr(complaint, 'priority') else 'Medium',
            'created_date': complaint.created_at.strftime('%Y-%m-%d'),
            'loan_id': complaint.loan.id if complaint.loan else None,
        })
    
    context = {
        'page_title': 'Complaints Management',
        'complaints': complaints_list,
        'paginator': paginator,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'complaint_counts': complaint_counts,
        'search_query': search_query,
        'status_filter': status_filter,
    }
    
    return render(request, 'core/subadmin/complaints.html', context)


# ============ SETTINGS ============

@login_required(login_url='login')
@subadmin_required
def subadmin_settings(request):
    """
    SubAdmin Settings Page
    - Profile update
    - Password change
    - Notification preferences
    """
    user = request.user
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'update_profile':
            user.first_name = request.POST.get('first_name', user.first_name)
            user.last_name = request.POST.get('last_name', user.last_name)
            user.email = request.POST.get('email', user.email)
            user.phone = request.POST.get('phone', user.phone)
            user.save()
            
            return JsonResponse({'success': True, 'message': 'Profile updated successfully'})
        
        elif action == 'change_password':
            old_password = request.POST.get('old_password')
            new_password = request.POST.get('new_password')
            
            if user.check_password(old_password):
                user.set_password(new_password)
                user.save()
                return JsonResponse({'success': True, 'message': 'Password changed successfully'})
            else:
                return JsonResponse({'success': False, 'message': 'Old password is incorrect'}, status=400)
    
    context = {
        'page_title': 'Settings',
        'user': user,
    }
    
    return render(request, 'core/subadmin/settings.html', context)


# ============ ADD NEW LOAN ============

@login_required(login_url='login')
@subadmin_required
@require_http_methods(['GET', 'POST'])
def subadmin_add_loan(request):
    """
    SubAdmin Add New Loan - Create new loan applications
    """
    if request.method == 'POST':
        try:
            # Extract form data
            applicant_name = request.POST.get('applicant_name')
            applicant_email = request.POST.get('applicant_email')
            applicant_mobile = request.POST.get('applicant_mobile')
            fathers_name = request.POST.get('fathers_name')
            dob = request.POST.get('dob')
            gender = request.POST.get('gender')
            
            permanent_address = request.POST.get('permanent_address')
            permanent_city = request.POST.get('permanent_city')
            permanent_pin = request.POST.get('permanent_pin')
            
            occupation = request.POST.get('occupation')
            year_of_experience = request.POST.get('year_of_experience')
            monthly_income = request.POST.get('monthly_income')
            
            # Optional employment fields
            company_name = request.POST.get('company_name', '')
            designation = request.POST.get('designation', '')
            nature_of_business = request.POST.get('nature_of_business', '')
            
            loan_type = request.POST.get('loan_type')
            loan_amount_required = request.POST.get('loan_amount_required')
            loan_tenure = request.POST.get('loan_tenure')
            
            bank_name = request.POST.get('bank_name')
            account_number = request.POST.get('account_number')
            ifsc_code = request.POST.get('ifsc_code')
            
            aadhar_number = request.POST.get('aadhar_number')
            pan_number = request.POST.get('pan_number')
            cibil_score = request.POST.get('cibil_score', 0)
            
            ref1_name = request.POST.get('ref1_name')
            ref1_mobile = request.POST.get('ref1_mobile')
            ref2_name = request.POST.get('ref2_name')
            ref2_mobile = request.POST.get('ref2_mobile')
            
            # Create LoanApplication entry
            loan_application = LoanApplication.objects.create(
                name=applicant_name,
                email=applicant_email,
                mobile_no=applicant_mobile,
                fathers_name=fathers_name,
                dob=dob,
                gender=gender,
                permanent_address=permanent_address,
                permanent_city=permanent_city,
                permanent_pin=permanent_pin,
                occupation=occupation,
                year_of_experience=int(year_of_experience) if year_of_experience else 0,
                monthly_income=float(monthly_income) if monthly_income else 0,
                company_name=company_name,
                designation=designation,
                nature_of_business=nature_of_business,
                loan_type=loan_type,
                loan_amount_required=float(loan_amount_required) if loan_amount_required else 0,
                loan_tenure=int(loan_tenure) if loan_tenure else 0,
                bank_name=bank_name,
                account_number=account_number,
                ifsc_code=ifsc_code,
                aadhar_number=aadhar_number,
                pan_number=pan_number,
                cibil_score=int(cibil_score) if cibil_score else 0,
                reference1_name=ref1_name,
                reference1_mobile=ref1_mobile,
                reference2_name=ref2_name,
                reference2_mobile=ref2_mobile,
                status='new_entry',
                created_by=request.user,
            )
            
            # Handle document uploads
            documents_names = request.POST.getlist('document_name[]')
            documents_files = request.FILES.getlist('document_file[]')
            
            for name, file in zip(documents_names, documents_files):
                if file:
                    LoanDocument.objects.create(
                        loan_application=loan_application,
                        document_name=name,
                        document_file=file,
                        uploaded_by=request.user,
                    )
            
            # Create corresponding Loan entry
            Loan.objects.create(
                applicant_name=applicant_name,
                applicant_email=applicant_email,
                applicant_mobile=applicant_mobile,
                loan_type=loan_type,
                loan_amount=float(loan_amount_required) if loan_amount_required else 0,
                status='new_entry',
                created_by=request.user,
            )
            
            from django.contrib import messages
            messages.success(request, 'Loan application created successfully!')
            return redirect('subadmin_all_loans')
            
        except Exception as e:
            logger.error(f"Error creating loan: {str(e)}")
            from django.contrib import messages
            messages.error(request, f'Error creating loan: {str(e)}')
            return render(request, 'core/subadmin/add_loan.html')
    
    context = {
        'page_title': 'Add New Loan Application',
    }
    return render(request, 'core/subadmin/add_loan.html', context)

