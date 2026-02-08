"""
Professional Loan Management System - Dashboard & Admin Views
Production-ready views for loan management, employee management, and real-time dashboards
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.utils import timezone
from django.http import JsonResponse
from datetime import timedelta

from .models import Loan, User, Agent, Complaint, ActivityLog, LoanApplication, Applicant
from .decorators import admin_required, employee_required


# ============================================================================
# PROFESSIONAL LOAN APPLICATIONS VIEW
# ============================================================================

@admin_required
def professional_new_loan_applications(request):
    """
    New Loan Applications page - Professional Dashboard
    Shows applications with manual refresh via AJAX
    """
    context = {
        'page_title': 'New Loan Applications',
        'total_applications': Loan.objects.filter(status='new_entry').count(),
    }
    return render(request, 'core/new_loan_applications_professional.html', context)


# ============================================================================
# EMPLOYEE MANAGEMENT VIEW
# ============================================================================

@admin_required
def professional_employee_management(request):
    """
    Employee Management Panel - Admin only
    Add, view, edit, and delete employees with complete statistics
    """
    context = {
        'page_title': 'Employee Management',
        'total_employees': User.objects.filter(role='employee', is_active=True).count(),
    }
    return render(request, 'core/employee_management_professional.html', context)


# ============================================================================
# REAL-TIME DASHBOARD VIEWS
# ============================================================================

@login_required
def real_time_dashboard(request):
    """
    Real-time dashboard with live updates for all users
    Shows statistics, recent activities, and complaints
    """
    if request.user.role == 'admin':
        # Admin dashboard
        context = {
            'page_title': 'Admin Dashboard',
            'is_admin': True,
        }
    elif request.user.role == 'employee':
        # Employee dashboard
        context = {
            'page_title': 'Employee Dashboard',
            'is_admin': False,
        }
    else:
        return redirect('login')
    
    return render(request, 'core/real_time_dashboard.html', context)


# ============================================================================
# COMPLAINT MANAGEMENT VIEW
# ============================================================================

@admin_required
def admin_complaints_panel(request):
    """
    Admin Complaints Panel - View and manage complaints
    Real-time updates for incoming complaints
    """
    context = {
        'page_title': 'Complaints Management',
        'total_complaints': Complaint.objects.count(),
        'open_complaints': Complaint.objects.filter(status='open').count(),
    }
    return render(request, 'core/admin_complaints_panel.html', context)


# ============================================================================
# REPORTS DOWNLOAD VIEW
# ============================================================================

@login_required
def download_reports(request):
    """
    Reports Download Panel
    Users can download reports for 1 month, 6 months, or 1 year
    """
    if request.user.role == 'admin':
        context = {
            'page_title': 'Reports',
            'show_all_employees': True,
        }
    elif request.user.role == 'employee':
        context = {
            'page_title': 'My Reports',
            'show_all_employees': False,
        }
    else:
        return redirect('login')
    
    return render(request, 'core/reports_download.html', context)


# ============================================================================
# LOAN ASSIGNMENT MANAGEMENT
# ============================================================================

@admin_required
def loan_assignment_panel(request):
    """
    Loan Assignment Panel - Admin assigns loans to employees
    Shows unassigned loans and allows quick assignment
    """
    unassigned_loans = Loan.objects.filter(
        assigned_employee__isnull=True,
        status__in=['new_entry', 'waiting']
    ).order_by('-created_at')
    
    employees = User.objects.filter(role='employee', is_active=True).order_by('first_name')
    
    context = {
        'page_title': 'Loan Assignment',
        'unassigned_loans': unassigned_loans,
        'employees': employees,
        'total_unassigned': unassigned_loans.count(),
    }
    return render(request, 'core/loan_assignment_panel.html', context)


# ============================================================================
# EMPLOYEE DASHBOARD VIEW
# ============================================================================

@employee_required
def employee_dashboard_view(request):
    """
    Employee Dashboard - Shows assigned loans and statistics
    """
    user = request.user
    
    # Get employee's statistics
    assigned_loans = Loan.objects.filter(assigned_employee=user)
    
    context = {
        'page_title': 'Employee Dashboard',
        'total_loans': assigned_loans.count(),
        'new_entries': assigned_loans.filter(status='new_entry').count(),
        'waiting': assigned_loans.filter(status='waiting').count(),
        'approved': assigned_loans.filter(status='approved').count(),
        'rejected': assigned_loans.filter(status='rejected').count(),
        'disbursed': assigned_loans.filter(status='disbursed').count(),
    }
    return render(request, 'core/employee_dashboard_professional.html', context)


# ============================================================================
# ACTIVITY LOG VIEW
# ============================================================================

@admin_required
def activity_log_view(request):
    """
    Activity Log - View all system activities
    Shows who did what and when
    """
    activities = ActivityLog.objects.select_related(
        'user', 'related_loan', 'related_agent', 'related_complaint'
    ).order_by('-created_at')[:500]
    
    context = {
        'page_title': 'Activity Log',
        'activities': activities,
    }
    return render(request, 'core/activity_log.html', context)


# ============================================================================
# SYSTEM SETTINGS VIEW
# ============================================================================

@admin_required
def system_settings_view(request):
    """
    System Settings - Configure system-wide settings
    """
    context = {
        'page_title': 'System Settings',
    }
    return render(request, 'core/system_settings.html', context)
