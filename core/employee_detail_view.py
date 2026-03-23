hon@login_required(login_url='admin_login')
@user_passes_test(is_admin, login_url='admin_login')
@require_http_methods(["GET"])
def employee_detail(request, employee_id):
    """
    Employee Detail Page - Shows full employee information
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
