"""
REFACTORED VIEWS - CLEAN CONTEXT ISOLATION
============================================

KEY PRINCIPLES:
1. Dashboard views pass ONLY dashboard context
2. Listing views pass ONLY listing context
3. Form views pass ONLY form context
4. NO mixing of contexts

CONTEXT DATA SEPARATION:

Dashboard Context:
- stats: {total, counts by status, financial summaries}
- recent_activities: List of recent actions
- charts_data: Chart configuration if needed

Listing Context:
- items: Paginated data for display
- total_count: Total number of items
- filters: Active filters info

Form Context:
- form: Form instance
- instance: Object being edited (if edit)
- errors: Form errors if POST
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Q, Count, Sum
from core.models import LoanApplication, SubAdmin, Agent
from core.decorators import admin_required, subadmin_required

# ============================================================================
# ADMIN VIEWS - CLEAN SEPARATION
# ============================================================================

@login_required
@admin_required
def admin_dashboard(request):
    """
    ADMIN DASHBOARD - Dashboard widgets only
    Context: stats, recent_activities, charts_data
    """
    # Get statistics for dashboard
    stats = {
        'total_loans': LoanApplication.objects.count(),
        'new_entry': LoanApplication.objects.filter(status='new_entry').count(),
        'processing': LoanApplication.objects.filter(status='processing').count(),
        'approved': LoanApplication.objects.filter(status='approved').count(),
        'rejected': LoanApplication.objects.filter(status='rejected').count(),
        'disbursed': LoanApplication.objects.filter(status='disbursed').count(),
        'total_value': LoanApplication.objects.aggregate(
            total=Sum('loan_amount')
        )['total'] or 0,
        'disbursed_value': LoanApplication.objects.filter(
            status='disbursed'
        ).aggregate(total=Sum('loan_amount'))['total'] or 0,
        'pending_value': LoanApplication.objects.exclude(
            status='disbursed'
        ).aggregate(total=Sum('loan_amount'))['total'] or 0,
    }
    
    # Get recent activities
    recent_activities = [
        {
            'status': 'approved',
            'description': 'Loan application approved',
            'badge_color': 'success',
            'timestamp': '2 hours ago'
        },
        # Add from database as needed
    ]
    
    context = {
        'stats': stats,
        'recent_activities': recent_activities,
    }
    
    return render(request, 'admin_clean/dashboard.html', context)


@login_required
@admin_required
def admin_all_loans(request):
    """
    ADMIN ALL LOANS - Listing only (NO dashboard widgets)
    Context: page_title, filter_options
    Template loads data via API
    """
    context = {
        'page_title': 'All Loans',
    }
    
    return render(request, 'admin_clean/all_loans.html', context)


@login_required
@admin_required
def admin_subadmin_management(request):
    """
    ADMIN SUBADMIN MANAGEMENT - Listing with form
    Context: form, subadmins list
    """
    subadmins = SubAdmin.objects.all()
    
    context = {
        'page_title': 'SubAdmin Management',
        'subadmins_count': subadmins.count(),
    }
    
    return render(request, 'admin_clean/subadmin_management.html', context)


# ============================================================================
# ADMIN APIS - RETURN JSON DATA ONLY
# ============================================================================

@login_required
@admin_required
@require_http_methods(["GET"])
def api_admin_dashboard_stats(request):
    """
    API endpoint for admin dashboard stats
    Returns: All stats needed for dashboard widgets
    """
    stats = {
        'total_loans': LoanApplication.objects.count(),
        'new_entry': LoanApplication.objects.filter(status='new_entry').count(),
        'processing': LoanApplication.objects.filter(status='processing').count(),
        'approved': LoanApplication.objects.filter(status='approved').count(),
        'rejected': LoanApplication.objects.filter(status='rejected').count(),
        'disbursed': LoanApplication.objects.filter(status='disbursed').count(),
        'total_value': float(
            LoanApplication.objects.aggregate(total=Sum('loan_amount'))['total'] or 0
        ),
        'disbursed_value': float(
            LoanApplication.objects.filter(
                status='disbursed'
            ).aggregate(total=Sum('loan_amount'))['total'] or 0
        ),
    }
    
    return JsonResponse(stats)


@login_required
@admin_required
@require_http_methods(["GET"])
def api_admin_all_loans(request):
    """
    API endpoint for admin all loans listing
    Returns: Loans data for table display (NOT stats)
    """
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    
    loans_qs = LoanApplication.objects.all()
    
    if search_query:
        loans_qs = loans_qs.filter(
            Q(applicant_name__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    
    if status_filter:
        loans_qs = loans_qs.filter(status=status_filter)
    
    loans_data = [
        {
            'id': loan.id,
            'applicant_name': loan.applicant_name,
            'phone': loan.phone,
            'loan_amount': str(loan.loan_amount),
            'status': loan.status,
            'submission_date': loan.submission_date.isoformat(),
        }
        for loan in loans_qs
    ]
    
    return JsonResponse({'loans': loans_data})


# ============================================================================
# SUBADMIN VIEWS - CLEAN SEPARATION
# ============================================================================

@login_required
@subadmin_required
def subadmin_dashboard(request):
    """
    SUBADMIN DASHBOARD - Dashboard widgets only
    Context: stats, recent_activities
    """
    user_subadmin = request.user.subadmin_profile
    
    stats = {
        'total_loans': LoanApplication.objects.filter(
            agent__subadmin=user_subadmin
        ).count(),
        'processing': LoanApplication.objects.filter(
            agent__subadmin=user_subadmin,
            status='processing'
        ).count(),
        'approved': LoanApplication.objects.filter(
            agent__subadmin=user_subadmin,
            status='approved'
        ).count(),
        'my_agents': Agent.objects.filter(subadmin=user_subadmin).count(),
        'total_value': LoanApplication.objects.filter(
            agent__subadmin=user_subadmin
        ).aggregate(total=Sum('loan_amount'))['total'] or 0,
        'approved_value': LoanApplication.objects.filter(
            agent__subadmin=user_subadmin,
            status='approved'
        ).aggregate(total=Sum('loan_amount'))['total'] or 0,
        'pending_value': LoanApplication.objects.filter(
            agent__subadmin=user_subadmin
        ).exclude(status='disbursed').aggregate(
            total=Sum('loan_amount')
        )['total'] or 0,
    }
    
    context = {
        'stats': stats,
    }
    
    return render(request, 'subadmin_clean/dashboard.html', context)


@login_required
@subadmin_required
def subadmin_all_loans(request):
    """
    SUBADMIN ALL LOANS - Listing only (NO dashboard widgets)
    Context: page_title
    Template loads data via API
    """
    context = {
        'page_title': 'My Loans',
    }
    
    return render(request, 'subadmin_clean/all_loans.html', context)


# ============================================================================
# SUBADMIN APIS - RETURN JSON DATA ONLY
# ============================================================================

@login_required
@subadmin_required
@require_http_methods(["GET"])
def api_subadmin_dashboard_stats(request):
    """
    API endpoint for subadmin dashboard stats
    Returns: Stats needed for dashboard widgets
    """
    user_subadmin = request.user.subadmin_profile
    
    stats = {
        'total_loans': LoanApplication.objects.filter(
            agent__subadmin=user_subadmin
        ).count(),
        'processing': LoanApplication.objects.filter(
            agent__subadmin=user_subadmin,
            status='processing'
        ).count(),
        'approved': LoanApplication.objects.filter(
            agent__subadmin=user_subadmin,
            status='approved'
        ).count(),
        'my_agents': Agent.objects.filter(subadmin=user_subadmin).count(),
    }
    
    return JsonResponse(stats)


@login_required
@subadmin_required
@require_http_methods(["GET"])
def api_subadmin_all_loans(request):
    """
    API endpoint for subadmin all loans listing
    Returns: Loans data for table display (NOT stats)
    """
    user_subadmin = request.user.subadmin_profile
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    
    loans_qs = LoanApplication.objects.filter(
        agent__subadmin=user_subadmin
    )
    
    if search_query:
        loans_qs = loans_qs.filter(
            Q(applicant_name__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    
    if status_filter:
        loans_qs = loans_qs.filter(status=status_filter)
    
    loans_data = [
        {
            'id': loan.id,
            'applicant_name': loan.applicant_name,
            'agent_name': loan.agent.user.first_name if loan.agent else 'N/A',
            'loan_amount': str(loan.loan_amount),
            'status': loan.status,
            'submission_date': loan.submission_date.isoformat(),
        }
        for loan in loans_qs
    ]
    
    return JsonResponse({'loans': loans_data})
