"""
FORM ISOLATION ROUTER
=====================
Production-grade router that ensures forms are ONLY rendered in New Entry section.
All other dashboard sections use read-only templates with NO form includes.

Architecture:
- form_only_view() → Renders application_form_only.html (New Entry ONLY)
- list_view_router() → Renders list page (table-based, NO forms)
- detail_view_router() → Renders read-only detail page (NO forms)
- Status-based template selector ensures proper isolation

Security:
- No form includes in base.html
- No form includes in dashboard layouts
- Forms ONLY accessible via New Entry routes
- All other sections are read-only
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .decorators import admin_required
from .models import Loan, Applicant


@admin_required
def new_entry_form_view(request):
    """
    ISOLATED FORM RENDER
    ====================
    Location: Admin → New Entry
    Status: WRITE ENABLED (form submission allowed)
    Template: partials/application_form_only.html
    
    This is the ONLY place where application forms are rendered.
    """
    context = {
        'page_title': 'New Entry',
        'page_section': 'new_entry',
        'form_mode': 'create',
        'show_form': True,  # ONLY set to True here
    }
    return render(request, 'core/admin_new_entry.html', context)


@admin_required
def new_entry_list_view(request):
    """
    NEW ENTRY LIST (TABLE)
    ======================
    Status: READ-ONLY
    Template: core/admin_new_entry_list.html
    Features: Table with quick actions, NO form fields
    """
    new_entries = Loan.objects.filter(status='new_entry').order_by('-created_at')
    context = {
        'page_title': 'New Entry',
        'page_section': 'new_entry',
        'loans': new_entries,
        'show_form': False,  # CRITICAL: Never show form in list
    }
    return render(request, 'core/admin_new_entry_list.html', context)


@admin_required  
def new_entry_detail_view(request, loan_id):
    """
    NEW ENTRY DETAIL (READ-ONLY)
    ===========================
    Status: READ-ONLY (no inline form)
    Template: core/admin_new_entry_detail.html
    Features: View details, edit via modal/separate form only
    
    If editing is needed, it should redirect to new_entry_form_view
    with the loan_id parameter, NOT render the form inline.
    """
    try:
        loan = Loan.objects.get(id=loan_id, status='new_entry')
    except Loan.DoesNotExist:
        return redirect('admin_new_entry_list')
    
    context = {
        'page_title': f'New Entry - {loan.full_name}',
        'page_section': 'new_entry',
        'loan': loan,
        'show_form': False,  # CRITICAL: Detail is read-only
        'readonly': True,
    }
    return render(request, 'core/admin_new_entry_detail.html', context)


@login_required
def waiting_list_view(request):
    """
    WAITING FOR PROCESSING - LIST (TABLE)
    ====================================
    Status: READ-ONLY
    Accessible: All roles (employee, dsa, admin)
    Template: dashboard/waiting_processing_list.html
    Features: Table with approval/rejection buttons, NO form
    """
    user = request.user
    
    if user.role == 'admin':
        waiting_loans = Loan.objects.filter(status='waiting').order_by('-created_at')
    elif user.role == 'employee':
        waiting_loans = Loan.objects.filter(
            status='waiting',
            assigned_employee=user
        ).order_by('-created_at')
    elif user.role == 'dsa':
        waiting_loans = Loan.objects.filter(
            status='waiting',
            assigned_agent__created_by=user
        ).order_by('-created_at')
    else:
        waiting_loans = Loan.objects.none()
    
    context = {
        'page_title': 'Waiting for Processing',
        'page_section': 'waiting',
        'loans': waiting_loans,
        'show_form': False,  # CRITICAL: Never show form
    }
    return render(request, 'dashboard/waiting_processing_list.html', context)


@login_required
def waiting_detail_view(request, loan_id):
    """
    WAITING FOR PROCESSING - DETAIL (READ-ONLY)
    =========================================
    Status: READ-ONLY (approval/rejection buttons only)
    Accessible: Assigned employee/agent + admin
    Template: dashboard/waiting_processing_detail.html
    Features: View loan details, approve/reject buttons, NO form
    """
    try:
        loan = Loan.objects.get(id=loan_id, status='waiting')
    except Loan.DoesNotExist:
        return redirect('waiting_list')
    
    # Check permission
    user = request.user
    if user.role == 'employee' and loan.assigned_employee != user:
        return redirect('waiting_list')
    elif user.role == 'dsa' and loan.assigned_agent.created_by != user:
        return redirect('waiting_list')
    
    context = {
        'page_title': f'Processing - {loan.full_name}',
        'page_section': 'waiting',
        'loan': loan,
        'show_form': False,  # CRITICAL: Detail is read-only
        'readonly': True,
        'show_actions': True,  # Enable approve/reject buttons
    }
    return render(request, 'dashboard/waiting_processing_detail.html', context)


@admin_required
def followup_list_view(request):
    """
    REQUIRED FOLLOW-UP - LIST (TABLE)
    ==============================
    Status: READ-ONLY
    Accessible: Admin only
    Template: dashboard/followup_list.html
    Features: Table with actions, NO form
    """
    followup_loans = Loan.objects.filter(status='follow_up').order_by('-created_at')
    
    context = {
        'page_title': 'Required Follow-up',
        'page_section': 'follow_up',
        'loans': followup_loans,
        'show_form': False,  # CRITICAL: Never show form
    }
    return render(request, 'dashboard/followup_list.html', context)


@admin_required
def followup_detail_view(request, loan_id):
    """
    REQUIRED FOLLOW-UP - DETAIL (READ-ONLY)
    ==================================
    Status: READ-ONLY (reassign button only)
    Template: dashboard/followup_detail.html
    Features: View details, reassign button, NO form
    """
    try:
        loan = Loan.objects.get(id=loan_id, status='follow_up')
    except Loan.DoesNotExist:
        return redirect('followup_list')
    
    context = {
        'page_title': f'Follow-up - {loan.full_name}',
        'page_section': 'follow_up',
        'loan': loan,
        'show_form': False,  # CRITICAL: Detail is read-only
        'readonly': True,
        'show_reassign': True,  # Enable reassign button only
    }
    return render(request, 'dashboard/followup_detail.html', context)


@login_required
def approved_list_view(request):
    """
    APPROVED - LIST (TABLE)
    ====================
    Status: READ-ONLY
    Accessible: All roles
    Template: dashboard/approved_list.html
    Features: Table only, NO form
    """
    user = request.user
    
    if user.role == 'admin':
        approved_loans = Loan.objects.filter(status='approved').order_by('-created_at')
    elif user.role == 'employee':
        approved_loans = Loan.objects.filter(
            status='approved',
            assigned_employee=user
        ).order_by('-created_at')
    elif user.role == 'dsa':
        approved_loans = Loan.objects.filter(
            status='approved',
            assigned_agent__created_by=user
        ).order_by('-created_at')
    else:
        approved_loans = Loan.objects.none()
    
    context = {
        'page_title': 'Approved',
        'page_section': 'approved',
        'loans': approved_loans,
        'show_form': False,  # CRITICAL: Never show form
    }
    return render(request, 'dashboard/approved_list.html', context)


@login_required
def approved_detail_view(request, loan_id):
    """
    APPROVED - DETAIL (READ-ONLY)
    ========================
    Status: READ-ONLY
    Template: dashboard/approved_detail.html
    Features: View details only, NO form, NO actions
    """
    try:
        loan = Loan.objects.get(id=loan_id, status='approved')
    except Loan.DoesNotExist:
        return redirect('approved_list')
    
    context = {
        'page_title': f'Approved - {loan.full_name}',
        'page_section': 'approved',
        'loan': loan,
        'show_form': False,  # CRITICAL: Detail is read-only
        'readonly': True,
    }
    return render(request, 'dashboard/approved_detail.html', context)


@login_required
def rejected_list_view(request):
    """
    REJECTED - LIST (TABLE)
    ===================
    Status: READ-ONLY
    Accessible: All roles
    Template: dashboard/rejected_list.html
    Features: Table only, NO form
    """
    user = request.user
    
    if user.role == 'admin':
        rejected_loans = Loan.objects.filter(status='rejected').order_by('-created_at')
    elif user.role == 'employee':
        rejected_loans = Loan.objects.filter(
            status='rejected',
            assigned_employee=user
        ).order_by('-created_at')
    elif user.role == 'dsa':
        rejected_loans = Loan.objects.filter(
            status='rejected',
            assigned_agent__created_by=user
        ).order_by('-created_at')
    else:
        rejected_loans = Loan.objects.none()
    
    context = {
        'page_title': 'Rejected',
        'page_section': 'rejected',
        'loans': rejected_loans,
        'show_form': False,  # CRITICAL: Never show form
    }
    return render(request, 'dashboard/rejected_list.html', context)


@login_required
def rejected_detail_view(request, loan_id):
    """
    REJECTED - DETAIL (READ-ONLY)
    ========================
    Status: READ-ONLY
    Template: dashboard/rejected_detail.html
    Features: View details only, NO form, NO actions
    """
    try:
        loan = Loan.objects.get(id=loan_id, status='rejected')
    except Loan.DoesNotExist:
        return redirect('rejected_list')
    
    context = {
        'page_title': f'Rejected - {loan.full_name}',
        'page_section': 'rejected',
        'loan': loan,
        'show_form': False,  # CRITICAL: Detail is read-only
        'readonly': True,
    }
    return render(request, 'dashboard/rejected_detail.html', context)


@login_required
def disbursed_list_view(request):
    """
    DISBURSED - LIST (TABLE)
    ====================
    Status: READ-ONLY
    Accessible: All roles
    Template: dashboard/disbursed_list.html
    Features: Table only, NO form
    """
    user = request.user
    
    if user.role == 'admin':
        disbursed_loans = Loan.objects.filter(status='disbursed').order_by('-created_at')
    elif user.role == 'employee':
        disbursed_loans = Loan.objects.filter(
            status='disbursed',
            assigned_employee=user
        ).order_by('-created_at')
    elif user.role == 'dsa':
        disbursed_loans = Loan.objects.filter(
            status='disbursed',
            assigned_agent__created_by=user
        ).order_by('-created_at')
    else:
        disbursed_loans = Loan.objects.none()
    
    context = {
        'page_title': 'Disbursed',
        'page_section': 'disbursed',
        'loans': disbursed_loans,
        'show_form': False,  # CRITICAL: Never show form
    }
    return render(request, 'dashboard/disbursed_list.html', context)


@login_required
def disbursed_detail_view(request, loan_id):
    """
    DISBURSED - DETAIL (READ-ONLY)
    ========================
    Status: READ-ONLY
    Template: dashboard/disbursed_detail.html
    Features: View details only, NO form, NO actions
    """
    try:
        loan = Loan.objects.get(id=loan_id, status='disbursed')
    except Loan.DoesNotExist:
        return redirect('disbursed_list')
    
    context = {
        'page_title': f'Disbursed - {loan.full_name}',
        'page_section': 'disbursed',
        'loan': loan,
        'show_form': False,  # CRITICAL: Detail is read-only
        'readonly': True,
    }
    return render(request, 'dashboard/disbursed_detail.html', context)
