"""
Employee/Agent Dashboard Views
- View assigned loans
- Approve/Reject applications
- View documents
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from core.models import Loan, LoanDocument, ActivityLog, LoanApplication, Applicant

@login_required
def my_assigned_loans(request):
    """Show loans assigned to current employee/agent"""
    user = request.user
    
    if user.role == 'employee':
        loans = Loan.objects.filter(
            assigned_employee=user,
            status__in=['waiting', 'follow_up']
        ).order_by('-assigned_at')
    elif user.role == 'agent':
        from core.models import Agent
        try:
            agent = Agent.objects.get(user=user)
            loans = Loan.objects.filter(
                assigned_agent=agent,
                status__in=['waiting', 'follow_up']
            ).order_by('-assigned_at')
        except Agent.DoesNotExist:
            loans = Loan.objects.none()
    else:
        loans = Loan.objects.none()
    
    # Add hours since assignment
    for loan in loans:
        loan.hours_since_assignment = loan.get_hours_since_assignment()
    
    return render(request, 'core/my_assigned_loans.html', {
        'loans': loans,
        'total_count': loans.count(),
        'waiting_count': loans.filter(status='waiting').count(),
        'followup_count': loans.filter(status='follow_up').count(),
    })

@login_required
def loan_detail_for_action(request, loan_id):
    """View loan details with documents for approval/rejection"""
    user = request.user
    
    try:
        loan = Loan.objects.get(id=loan_id)
    except Loan.DoesNotExist:
        return JsonResponse({'error': 'Loan not found'}, status=404)
    
    # Check permission - only assigned user can view
    if user.role == 'employee' and loan.assigned_employee != user:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    elif user.role == 'agent':
        from core.models import Agent
        try:
            agent = Agent.objects.get(user=user)
            if loan.assigned_agent != agent:
                return JsonResponse({'error': 'Unauthorized'}, status=403)
        except Agent.DoesNotExist:
            return JsonResponse({'error': 'Agent not found'}, status=403)
    
    # Get all documents
    documents = LoanDocument.objects.filter(loan=loan)
    
    return render(request, 'core/loan_detail_for_action.html', {
        'loan': loan,
        'documents': documents,
        'hours_since_assignment': loan.get_hours_since_assignment(),
    })

@login_required
@require_http_methods(["POST"])
def approve_loan(request, loan_id):
    """Approve a loan application"""
    user = request.user
    
    try:
        loan = Loan.objects.get(id=loan_id)
    except Loan.DoesNotExist:
        return JsonResponse({'error': 'Loan not found'}, status=404)
    
    # Check permission
    if user.role == 'employee' and loan.assigned_employee != user:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    elif user.role == 'agent':
        from core.models import Agent
        try:
            agent = Agent.objects.get(user=user)
            if loan.assigned_agent != agent:
                return JsonResponse({'error': 'Unauthorized'}, status=403)
        except Agent.DoesNotExist:
            return JsonResponse({'error': 'Agent not found'}, status=403)
    
    # Update loan status
    loan.status = 'approved'
    loan.action_taken_at = timezone.now()
    loan.save()
    
    # Also update LoanApplication status to keep them in sync
    try:
        applicant = Applicant.objects.get(full_name=loan.full_name)
        loan_app = LoanApplication.objects.get(applicant=applicant)
        loan_app.status = 'Approved'
        loan_app.approved_by = user
        loan_app.approved_at = timezone.now()
        loan_app.save()
    except (Applicant.DoesNotExist, LoanApplication.DoesNotExist):
        pass  # If no matching LoanApplication, just continue
    
    # Log activity
    ActivityLog.objects.create(
        user=user,
        action='loan_approved',
        description=f'{user.first_name} {user.last_name} approved loan for {loan.full_name}',
        applicant_id=loan.id
    )
    
    return JsonResponse({
        'success': True,
        'message': f'Loan for {loan.full_name} has been approved',
        'status': 'approved'
    })

@login_required
@require_http_methods(["POST"])
def reject_loan(request, loan_id):
    """Reject a loan application"""
    user = request.user
    
    try:
        loan = Loan.objects.get(id=loan_id)
    except Loan.DoesNotExist:
        return JsonResponse({'error': 'Loan not found'}, status=404)
    
    # Check permission
    if user.role == 'employee' and loan.assigned_employee != user:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    elif user.role == 'agent':
        from core.models import Agent
        try:
            agent = Agent.objects.get(user=user)
            if loan.assigned_agent != agent:
                return JsonResponse({'error': 'Unauthorized'}, status=403)
        except Agent.DoesNotExist:
            return JsonResponse({'error': 'Agent not found'}, status=403)
    
    # Get rejection reason from POST data
    reason = request.POST.get('reason', 'No reason provided')
    
    # Update loan status
    loan.status = 'rejected'
    loan.action_taken_at = timezone.now()
    loan.remarks = f'Rejected by {user.get_full_name()}: {reason}'
    loan.save()
    
    # Also update LoanApplication status to keep them in sync
    try:
        applicant = Applicant.objects.get(full_name=loan.full_name)
        loan_app = LoanApplication.objects.get(applicant=applicant)
        loan_app.status = 'Rejected'
        loan_app.rejected_by = user
        loan_app.rejection_reason = reason
        loan_app.rejected_at = timezone.now()
        loan_app.save()
    except (Applicant.DoesNotExist, LoanApplication.DoesNotExist):
        pass  # If no matching LoanApplication, just continue
    
    # Log activity
    ActivityLog.objects.create(
        user=user,
        action='loan_rejected',
        description=f'{user.get_full_name()} rejected loan for {loan.full_name}: {reason}',
        applicant_id=loan.id
    )
    
    return JsonResponse({
        'success': True,
        'message': f'Loan for {loan.full_name} has been rejected',
        'status': 'rejected'
    })

@login_required
def get_assigned_loans_api(request):
    """API endpoint to get assigned loans (for dashboard)"""
    user = request.user
    
    if user.role == 'employee':
        loans = Loan.objects.filter(
            assigned_employee=user,
            status__in=['waiting', 'follow_up']
        )
    elif user.role == 'agent':
        from core.models import Agent
        try:
            agent = Agent.objects.get(user=user)
            loans = Loan.objects.filter(
                assigned_agent=agent,
                status__in=['waiting', 'follow_up']
            )
        except Agent.DoesNotExist:
            loans = Loan.objects.none()
    else:
        loans = Loan.objects.none()
    
    data = {
        'total_assigned': loans.count(),
        'waiting': loans.filter(status='waiting').count(),
        'follow_up': loans.filter(status='follow_up').count(),
        'loans': []
    }
    
    for loan in loans:
        data['loans'].append({
            'id': loan.id,
            'name': loan.full_name,
            'amount': str(loan.loan_amount),
            'status': loan.status,
            'assigned_at': loan.assigned_at.isoformat() if loan.assigned_at else None,
            'hours_since': loan.get_hours_since_assignment(),
        })
    
    return JsonResponse(data)

