"""
Employee Management Views - Admin Only
Handles CRUD operations for employees
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.contrib import messages
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import User, Loan, ActivityLog


@login_required
@require_http_methods(["GET"])
def employee_management(request):
    """Admin: View and manage employees"""
    
    # Only admin can access
    if request.user.role != 'admin':
        messages.error(request, 'Access denied. Admin only.')
        return redirect('dashboard')
    
    # Get all employees
    employees = User.objects.filter(role='employee', is_active=True).order_by('-created_at')
    
    # Calculate stats
    total_employees = User.objects.filter(role='employee').count()
    active_employees = employees.count()
    
    # Get leads and disbursed amount for each employee
    loans_data = Loan.objects.filter(assigned_employee__isnull=False).values(
        'assigned_employee_id'
    ).annotate(
        leads=Count('id'),
        approved=Count('id', filter=Q(status='approved')),
        disbursed_amount=Sum('loan_amount', filter=Q(status='disbursed'))
    )
    
    loans_dict = {item['assigned_employee_id']: item for item in loans_data}
    total_leads = sum(item['leads'] for item in loans_data)
    total_disbursed = sum(item['disbursed_amount'] or 0 for item in loans_data)
    
    context = {
        'employees': employees,
        'total_employees': total_employees,
        'active_employees': active_employees,
        'total_leads': total_leads,
        'total_disbursed': total_disbursed,
        'loans_dict': loans_dict,
    }
    
    return render(request, 'core/employee_management.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def add_employee(request):
    """Admin: Add new employee"""
    
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    if request.method == 'POST':
        try:
            # Get form data
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            employee_id = request.POST.get('employee_id', '').strip()
            email = request.POST.get('email', '').strip()
            phone = request.POST.get('phone', '').strip()
            password = request.POST.get('password', '').strip()
            gender = request.POST.get('gender', '')
            address = request.POST.get('address', '')
            profile_photo = request.FILES.get('profile_photo')
            
            # Validation
            if not all([first_name, last_name, email, phone, password]):
                return JsonResponse({'error': 'All required fields must be filled'}, status=400)
            
            # Check if email already exists
            if User.objects.filter(email=email).exists():
                return JsonResponse({'error': 'Email already exists'}, status=400)
            
            # Check if employee_id already exists
            if User.objects.filter(employee_id=employee_id).exists():
                return JsonResponse({'error': 'Employee ID already exists'}, status=400)
            
            # Create user
            username = email.split('@')[0]  # Use email prefix as username
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role='employee',
                employee_id=employee_id,
                phone=phone,
                gender=gender,
                address=address,
            )
            
            if profile_photo:
                user.profile_photo = profile_photo
                user.save()
            
            messages.success(request, f'Employee {first_name} {last_name} created successfully!')
            return redirect('employee_management')
            
        except Exception as e:
            messages.error(request, f'Error creating employee: {str(e)}')
            return redirect('employee_management')
    
    return redirect('employee_management')


@login_required
@require_http_methods(["GET", "POST"])
def edit_employee(request, employee_id):
    """Admin: Edit employee details"""
    
    if request.user.role != 'admin':
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    employee = get_object_or_404(User, id=employee_id, role='employee')
    
    if request.method == 'POST':
        try:
            employee.first_name = request.POST.get('first_name', employee.first_name)
            employee.last_name = request.POST.get('last_name', employee.last_name)
            employee.phone = request.POST.get('phone', employee.phone)
            employee.address = request.POST.get('address', employee.address)
            employee.gender = request.POST.get('gender', employee.gender)
            
            if 'profile_photo' in request.FILES:
                employee.profile_photo = request.FILES['profile_photo']
            
            employee.save()
            
            messages.success(request, 'Employee updated successfully!')
            return redirect('employee_management')
            
        except Exception as e:
            messages.error(request, f'Error updating employee: {str(e)}')
            return redirect('employee_management')
    
    context = {'employee': employee}
    return render(request, 'core/edit_employee.html', context)


# API ENDPOINTS


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_employee(request, employee_id):
    """Get employee details for edit form"""
    
    if request.user.role != 'admin':
        return Response({'error': 'Access denied'}, status=403)
    
    try:
        employee = User.objects.get(id=employee_id, role='employee')
        
        return Response({
            'id': employee.id,
            'first_name': employee.first_name,
            'last_name': employee.last_name,
            'email': employee.email,
            'phone': employee.phone,
            'employee_id': employee.employee_id,
            'gender': employee.gender or '',
            'address': employee.address or '',
            'profile_photo': employee.profile_photo.url if employee.profile_photo else '',
        })
    except User.DoesNotExist:
        return Response({'error': 'Employee not found'}, status=404)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def api_delete_employee(request, employee_id):
    """Delete employee (soft delete - mark as inactive)"""
    
    if request.user.role != 'admin':
        return Response({'error': 'Access denied'}, status=403)
    
    try:
        employee = User.objects.get(id=employee_id, role='employee')
        
        # Soft delete - mark as inactive
        employee.is_active = False
        employee.save()
        
        return Response({'success': True, 'message': 'Employee deleted successfully'})
    except User.DoesNotExist:
        return Response({'error': 'Employee not found'}, status=404)
    except Exception as e:
        return Response({'error': str(e)}, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_employee_stats(request):
    """Get employee management stats"""
    
    if request.user.role != 'admin':
        return Response({'error': 'Access denied'}, status=403)
    
    total_employees = User.objects.filter(role='employee').count()
    active_employees = User.objects.filter(role='employee', is_active=True).count()
    
    # Calculate performance metrics
    performance_data = []
    employees = User.objects.filter(role='employee', is_active=True)
    
    for emp in employees:
        loans = Loan.objects.filter(assigned_employee=emp)
        total_loans = loans.count()
        approved = loans.filter(status='approved').count()
        disbursed = loans.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0
        
        performance_data.append({
            'id': emp.id,
            'name': emp.get_full_name(),
            'total_leads': total_loans,
            'approved': approved,
            'disbursed': float(disbursed),
        })
    
    total_leads = sum(item['total_loans'] for item in performance_data)
    total_disbursed = sum(item['disbursed'] for item in performance_data)
    
    return Response({
        'total_employees': total_employees,
        'active_employees': active_employees,
        'total_leads': total_leads,
        'total_disbursed': total_disbursed,
        'performance_data': performance_data,
    })

# ========== EMPLOYEE DASHBOARD VIEWS ==========

@login_required
@require_http_methods(["GET"])
def employee_dashboard(request):
    """Employee dashboard with stats and recent loans"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    return render(request, 'core/employee/dashboard.html')


@login_required
@require_http_methods(["GET"])
def employee_all_loans(request):
    """Employee: View all loans processed (handled via API)"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    return render(request, 'core/employee/all_loans.html')


@login_required
@require_http_methods(["GET"])
def employee_loan_status_list(request, status_key):
    """Employee: View loans by status from dashboard cards"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')

    status_map = {
        'total': {
            'title': 'Total Assigned Loans',
            'subtitle': 'All loans currently assigned to you',
            'badge': 'All Status'
        },
        'new_entry': {
            'title': 'New Entry Loans',
            'subtitle': 'Fresh applications waiting for first action',
            'badge': 'New Entry'
        },
        'waiting': {
            'title': 'In Processing Loans',
            'subtitle': 'Applications waiting for employee review',
            'badge': 'In Processing'
        },
        'awaiting': {
            'title': 'Awaiting Action',
            'subtitle': 'Waiting and follow-up loans that need your action',
            'badge': 'Waiting + Follow-up'
        },
        'approved': {
            'title': 'Approved Loans',
            'subtitle': 'Loans approved by you',
            'badge': 'Approved'
        },
        'rejected': {
            'title': 'Rejected Loans',
            'subtitle': 'Loans rejected by you',
            'badge': 'Rejected'
        },
        'follow_up': {
            'title': 'Banking Processing Loans',
            'subtitle': 'Loans currently in banking verification stage',
            'badge': 'Banking Processing'
        },
        'follow_up_pending': {
            'title': 'Follow Up Loans',
            'subtitle': 'Reverted loans waiting for correction',
            'badge': 'Follow Up'
        },
        'disbursed': {
            'title': 'Disbursed Loans',
            'subtitle': 'Loans successfully disbursed',
            'badge': 'Disbursed'
        }
    }

    if status_key not in status_map:
        messages.error(request, 'Invalid loan status.')
        return redirect('employee_dashboard')

    context = {
        'page_title': status_map[status_key]['title'],
        'page_subtitle': status_map[status_key]['subtitle'],
        'page_badge': status_map[status_key]['badge'],
        'status_key': status_key,
    }

    return render(request, 'core/employee/loan_status_list.html', context)


@login_required
@require_http_methods(["GET"])
def employee_profile(request):
    """Employee profile view"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    # Render profile page with user data
    context = {
        'user': request.user
    }
    return render(request, 'core/employee/profile.html', context)


@login_required
@require_http_methods(["GET"])
def employee_settings(request):
    """Employee settings view"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    # Render settings page
    context = {
        'user': request.user
    }
    return render(request, 'core/employee/settings.html', context)


# ========== ASSIGNED LOANS (NEW REQUEST) ==========

@login_required
@require_http_methods(["GET"])
def employee_assigned_loans(request):
    """
    Employee: View assigned loans (requests from admin)
    Shows all loans assigned to this employee with full details
    Employee can approve, reject, or dispute
    """
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    return render(request, 'core/employee_assigned_loans.html')


@login_required
@require_http_methods(["GET"])
def employee_new_entry_request(request):
    """
    Employee: View new entry requests (loans assigned by admin)
    Shows assigned loans in table format
    """
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    return render(request, 'core/employee/new_entry_request.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_assigned_loans(request):
    """
    API: Get all loans assigned to current employee
    Returns detailed loan information with documents
    """
    if request.user.role != 'employee':
        return Response({'error': 'Access denied'}, status=403)
    
    try:
        assigned_loans = Loan.objects.filter(
            assigned_employee=request.user
        ).select_related('created_by').prefetch_related('documents').order_by('-created_at')
        
        loans_data = []
        for loan in assigned_loans:
            documents = []
            for doc in loan.documents.all():
                documents.append({
                    'id': doc.id,
                    'document_type': doc.document_type,
                    'document_type_display': doc.get_document_type_display(),
                    'file_url': doc.file.url,
                    'uploaded_at': doc.uploaded_at.isoformat(),
                })
            
            loans_data.append({
                'id': loan.id,
                'applicant_name': loan.full_name,
                'mobile_number': loan.mobile_number,
                'email': loan.email,
                'city': loan.city,
                'state': loan.state,
                'pin_code': loan.pin_code,
                'permanent_address': loan.permanent_address,
                'current_address': loan.current_address,
                'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else loan.loan_type,
                'loan_amount': float(loan.loan_amount),
                'tenure_months': loan.tenure_months,
                'interest_rate': float(loan.interest_rate) if loan.interest_rate else None,
                'emi': float(loan.emi) if loan.emi else None,
                'loan_purpose': loan.loan_purpose,
                'bank_name': loan.bank_name,
                'bank_account_number': loan.bank_account_number,
                'bank_ifsc_code': loan.bank_ifsc_code,
                'bank_type': loan.get_bank_type_display() if hasattr(loan, 'get_bank_type_display') else loan.bank_type,
                'has_co_applicant': loan.has_co_applicant,
                'co_applicant_name': loan.co_applicant_name,
                'co_applicant_phone': loan.co_applicant_phone,
                'co_applicant_email': loan.co_applicant_email,
                'has_guarantor': loan.has_guarantor,
                'guarantor_name': loan.guarantor_name,
                'guarantor_phone': loan.guarantor_phone,
                'guarantor_email': loan.guarantor_email,
                'remarks': loan.remarks,
                'status': loan.status,
                'created_at': loan.created_at.isoformat(),
                'documents': documents,
            })
        
        return Response({
            'success': True,
            'loans': loans_data,
            'count': len(loans_data),
        })
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e),
        }, status=400)


@login_required
@require_http_methods(["POST"])
def employee_loan_action(request):
    """
    API: Employee action on assigned loan (approve, reject, dispute)
    """
    if request.user.role != 'employee':
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    try:
        import json
        data = json.loads(request.body)
        
        loan_id = request.GET.get('loan_id')
        action = data.get('action')
        reason = data.get('reason', '')
        
        # Validate
        if not loan_id or not action:
            return JsonResponse({'success': False, 'message': 'Missing loan_id or action'}, status=400)
        
        # Get loan and verify assignment
        loan = Loan.objects.get(id=loan_id, assigned_employee=request.user)
        
        if action == 'approve':
            loan.status = 'approved'
            loan.save()
            
            ActivityLog.objects.create(
                action='loan_approved',
                description=f"Employee {request.user.get_full_name()} approved loan for {loan.full_name}",
                user=request.user
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Loan request approved successfully'
            })
        
        elif action == 'reject':
            if not reason:
                return JsonResponse({'success': False, 'message': 'Reason required for rejection'}, status=400)
            
            loan.status = 'rejected'
            loan.remarks = f"Rejected by Employee: {reason}" if not loan.remarks else f"{loan.remarks}\n\nRejected by Employee: {reason}"
            loan.save()
            
            ActivityLog.objects.create(
                action='loan_rejected',
                description=f"Employee {request.user.get_full_name()} rejected loan for {loan.full_name}. Reason: {reason}",
                user=request.user
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Loan request rejected successfully'
            })
        
        elif action == 'dispute':
            if not reason:
                return JsonResponse({'success': False, 'message': 'Reason required for dispute'}, status=400)
            
            # Update status to dispute
            loan.status = 'disputed'  # Assuming 'disputed' is a status
            loan.remarks = f"Disputed by Employee: {reason}" if not loan.remarks else f"{loan.remarks}\n\nDisputed by Employee: {reason}"
            loan.save()
            
            ActivityLog.objects.create(
                action='loan_disputed',
                description=f"Employee {request.user.get_full_name()} disputed loan for {loan.full_name}. Reason: {reason}",
                user=request.user
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Loan request disputed. Admin will review your dispute.'
            })
        
        else:
            return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)
    
    except Loan.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Loan not found or not assigned to you'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)


# ============================================================
# EMPLOYEE PANEL - NEW APIS FOR FINTECH PANEL
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_dashboard_stats(request):
    """Employee dashboard statistics
    Returns counts of loans by status assigned to employee
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        from .models import LoanApplication
        
        loans = LoanApplication.objects.filter(assigned_employee=request.user)
        
        return Response({
            'success': True,
            'total_assigned': loans.count(),
            'processing': loans.filter(status='Waiting for Processing').count(),
            'approved': loans.filter(status='Approved').count(),
            'rejected': loans.filter(status='Rejected').count(),
            'follow_up': loans.filter(status='Required Follow-up').count(),
            'disbursed': loans.filter(status='Disbursed').count(),
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_assigned_loans_list_api(request):
    """Get list of loans assigned to employee with detailed info"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        from .models import LoanApplication, Applicant
        from datetime import datetime
        from django.core.paginator import Paginator
        
        # Get filters
        status_filter = request.GET.get('status', '').strip()
        from_date = request.GET.get('from_date', '').strip()
        to_date = request.GET.get('to_date', '').strip()
        page = int(request.GET.get('page', 1))
        limit = int(request.GET.get('limit', 20))
        
        # Base queryset
        queryset = LoanApplication.objects.filter(
            assigned_employee=request.user
        ).select_related('applicant').order_by('-assigned_at')
        
        # Apply filters
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
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
                'id': loan.id,  # Loan ID from LoanApplication model
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
                'agent_name': applicant.agent_name if hasattr(applicant, 'agent_name') else 'N/A',
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
@permission_classes([IsAuthenticated])
def employee_all_processed_loans_api(request):
    """Get all loans processed by employee (approved, rejected, disbursed)"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        from .models import LoanApplication
        from django.core.paginator import Paginator
        
        # Get filters
        status_filter = request.GET.get('status', '').strip()
        from_date = request.GET.get('from_date', '').strip()
        to_date = request.GET.get('to_date', '').strip()
        page = int(request.GET.get('page', 1))
        limit = int(request.GET.get('limit', 20))
        
        # Base queryset - only loans that have been processed (not waiting)
        queryset = LoanApplication.objects.filter(
            assigned_employee=request.user,
            status__in=['Approved', 'Rejected', 'Disbursed', 'Required Follow-up']
        ).select_related('applicant').order_by('-updated_at')
        
        # Apply status filter
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Apply date filters
        if from_date:
            try:
                from datetime import datetime
                from_date_obj = datetime.strptime(from_date, '%Y-%m-%d')
                queryset = queryset.filter(updated_at__gte=from_date_obj)
            except:
                pass
        
        if to_date:
            try:
                from datetime import datetime
                to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                to_date_obj = to_date_obj.replace(hour=23, minute=59, second=59)
                queryset = queryset.filter(updated_at__lte=to_date_obj)
            except:
                pass
        
        # Pagination
        paginator = Paginator(queryset, limit)
        page_obj = paginator.get_page(page)
        
        # Build response
        loans_data = []
        for loan in page_obj:
            applicant = loan.applicant
            
            loans_data.append({
                'id': loan.id,
                'applicant_id': applicant.id,
                'applicant_name': applicant.full_name,
                'loan_type': applicant.loan_type or 'N/A',
                'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                'status': loan.status,
                'assigned_date': loan.assigned_at.strftime('%Y-%m-%d') if loan.assigned_at else '',
                'updated_date': loan.updated_at.strftime('%Y-%m-%d') if loan.updated_at else '',
                'assigned_by_name': loan.assigned_by.get_full_name() if loan.assigned_by else 'System',
                'approval_notes': loan.approval_notes or '',
                'rejection_reason': loan.rejection_reason or '',
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
@permission_classes([IsAuthenticated])
def employee_loan_detail_api(request, loan_id):
    """Get complete loan details for employee view"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        from .models import LoanApplication, Applicant
        
        # Get loan and verify assignment
        loan = LoanApplication.objects.select_related('applicant').get(
            id=loan_id, 
            assigned_employee=request.user
        )
        
        applicant = loan.applicant
        
        return Response({
            'success': True,
            'loan': {
                'applicant_id': applicant.id,
                'applicant_name': applicant.full_name,
                'mobile': applicant.mobile,
                'email': applicant.email,
                'city': applicant.city,
                'state': applicant.state,
                'pin_code': applicant.pin_code,
                'permanent_address': applicant.permanent_address or 'N/A',
                'current_address': applicant.current_address or 'N/A',
                'loan_type': applicant.loan_type or 'N/A',
                'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                'loan_purpose': applicant.loan_purpose or 'N/A',
                'tenure_months': applicant.tenure_months or 0,
                'interest_rate': float(applicant.interest_rate) if applicant.interest_rate else 0,
                'emi': float(applicant.emi) if applicant.emi else 0,
                'bank_name': applicant.bank_name or 'N/A',
                'bank_type': applicant.bank_type or 'N/A',
                'account_number': applicant.account_number or 'N/A',
                'ifsc_code': applicant.ifsc_code or 'N/A',
                'status': loan.status,
                'assigned_date': loan.assigned_at.strftime('%Y-%m-%d %H:%M') if loan.assigned_at else '',
                'assigned_by_name': loan.assigned_by.get_full_name() if loan.assigned_by else 'System',
                'approval_notes': loan.approval_notes or '',
                'rejection_reason': loan.rejection_reason or '',
            }
        }, status=status.HTTP_200_OK)
    
    except LoanApplication.DoesNotExist:
        return Response({'success': False, 'error': 'Loan not found or not assigned to you'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_my_agents_api(request):
    """Get list of agents linked to employee:
    1. Agents created by this employee
    2. Agents that have submitted loans to this employee
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        from .models import LoanApplication, Agent
        
        agents_dict = {}
        
        # 1. Get agents created by this employee
        created_agents = Agent.objects.filter(created_by=request.user).select_related('user')
        for agent in created_agents:
            agents_dict[agent.id] = {
                'agent_id': agent.agent_id or agent.id,
                'agent_name': agent.name,
                'email': agent.email or 'N/A',
                'phone': agent.phone or 'N/A',
                'is_active': agent.status == 'active',
                'total_loans': 0,
                'approved_loans': 0,
                'rejected_loans': 0,
            }
        
        # 2. Get unique agents from loans assigned to this employee
        loans = LoanApplication.objects.filter(
            assigned_employee=request.user
        ).select_related('applicant')
        
        for loan in loans:
            applicant = loan.applicant
            if hasattr(applicant, 'agent_id') and applicant.agent_id:
                agent_id = applicant.agent_id
                if agent_id not in agents_dict:
                    agents_dict[agent_id] = {
                        'agent_id': agent_id,
                        'agent_name': applicant.agent_name if hasattr(applicant, 'agent_name') else 'N/A',
                        'email': applicant.agent_email if hasattr(applicant, 'agent_email') else 'N/A',
                        'phone': applicant.agent_phone if hasattr(applicant, 'agent_phone') else 'N/A',
                        'is_active': True,
                        'total_loans': 0,
                        'approved_loans': 0,
                        'rejected_loans': 0,
                    }
        
        # Calculate statistics for loans
        for loan in loans:
            applicant = loan.applicant
            if hasattr(applicant, 'agent_id') and applicant.agent_id:
                agent_id = applicant.agent_id
                if agent_id in agents_dict:
                    agents_dict[agent_id]['total_loans'] += 1
                    if loan.status == 'Approved':
                        agents_dict[agent_id]['approved_loans'] += 1
                    elif loan.status == 'Rejected':
                        agents_dict[agent_id]['rejected_loans'] += 1
        
        agents_list = list(agents_dict.values())
        
        # Calculate overall stats
        total_agents = len(agents_list)
        total_loans = sum(a['total_loans'] for a in agents_list)
        total_approved = sum(a['approved_loans'] for a in agents_list)
        total_rejected = sum(a['rejected_loans'] for a in agents_list)
        
        return Response({
            'success': True,
            'agents': agents_list,
            'stats': {
                'total_agents': total_agents,
                'total_loans': total_loans,
                'total_approved': total_approved,
                'total_rejected': total_rejected,
            }
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_approve_loan_api(request, loan_id):
    """Employee approves a loan"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        from .models import LoanApplication
        
        loan = LoanApplication.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify loan is in Waiting for Processing status
        if loan.status != 'Waiting for Processing':
            return Response({
                'success': False,
                'error': f'Loan status is {loan.status}. Can only approve loans in "Waiting for Processing" status.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update loan
        approval_notes = request.data.get('approval_notes', '').strip()
        loan.status = 'Approved'
        loan.approval_notes = approval_notes
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_approved',
            description=f"Employee {request.user.get_full_name()} approved loan #{loan.id}",
            user=request.user
        )
        
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
@permission_classes([IsAuthenticated])
def employee_reject_loan_api(request, loan_id):
    """Employee rejects a loan"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        from .models import LoanApplication
        
        loan = LoanApplication.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify loan is in Waiting for Processing status
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
        loan.rejection_reason = rejection_reason
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_rejected',
            description=f"Employee {request.user.get_full_name()} rejected loan #{loan.id}. Reason: {rejection_reason}",
            user=request.user
        )
        
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
@permission_classes([IsAuthenticated])
def employee_disburse_loan_api(request, loan_id):
    """Employee marks a loan as disbursed"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        from .models import LoanApplication
        from datetime import datetime
        
        loan = LoanApplication.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify loan is in Approved status
        if loan.status != 'Approved':
            return Response({
                'success': False,
                'error': f'Loan status is {loan.status}. Can only disburse approved loans.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update loan
        loan.status = 'Disbursed'
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_disbursed',
            description=f"Employee {request.user.get_full_name()} marked loan #{loan.id} as disbursed",
            user=request.user
        )
        
        return Response({
            'success': True,
            'message': 'Loan marked as disbursed successfully',
            'new_status': 'Disbursed',
        }, status=status.HTTP_200_OK)
    
    except LoanApplication.DoesNotExist:
        return Response({'success': False, 'error': 'Loan not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_new_entry_request_page(request):
    """Render new entry request page for employee"""
    if request.user.role != 'employee':
        return redirect('dashboard')
    
    return render(request, 'core/employee/new_entry_request.html')


def employee_loan_detail_page(request, loan_id):
    """Render loan detail page for employee"""
    if request.user.role != 'employee':
        return redirect('dashboard')
    
    try:
        from .models import LoanApplication
        
        # Verify loan is assigned to this employee
        loan = LoanApplication.objects.get(id=loan_id, assigned_employee=request.user)
        
        return render(request, 'core/employee/loan_detail.html', {'loan_id': loan_id})
    
    except LoanApplication.DoesNotExist:
        from django.http import Http404
        raise Http404("Loan not found or not assigned to you")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_my_agents_page(request):
    """Render my agents page for employee"""
    if request.user.role != 'employee':
        return redirect('dashboard')
    
    return render(request, 'core/employee/my_agents.html')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_add_agent_api(request):
    """Employee adds a new agent under themselves"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can add agents'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        from .models import User, Agent
        from django.contrib.auth.models import User as DjangoUser
        
        # Get form data
        name = request.data.get('name', '').strip()
        phone = request.data.get('phone', '').strip()
        email = request.data.get('email', '').strip()
        password = request.data.get('password', '').strip()
        agent_status = request.data.get('status', 'active')
        
        # Optional fields
        gender = request.data.get('gender', '').strip()
        address = request.data.get('address', '').strip()
        pin_code = request.data.get('pin_code', '').strip()
        state = request.data.get('state', '').strip()
        photo = request.FILES.get('photo')
        
        # Validate required fields
        if not all([name, phone, email, password]):
            return Response({
                'success': False,
                'error': 'All fields are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate phone format
        if not phone.isdigit() or len(phone) < 10:
            return Response({
                'success': False,
                'error': 'Invalid phone number. Must be at least 10 digits'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if email already exists
        if User.objects.filter(email=email).exists():
            return Response({
                'success': False,
                'error': 'Email already exists'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create User account for agent
        username = email.split('@')[0]
        # Make username unique
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role='agent',
            phone=phone
        )
        
        # Create Agent profile with all fields
        agent = Agent.objects.create(
            user=user,
            name=name,
            phone=phone,
            email=email,
            status=agent_status,
            gender=gender if gender else None,
            address=address if address else None,
            pin_code=pin_code if pin_code else None,
            state=state if state else None,
            created_by=request.user  # Link to employee who created it
        )
        
        # Save photo if provided
        if photo:
            agent.profile_photo = photo
            agent.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='agent_created',
            description=f"Employee {request.user.get_full_name()} created agent {name}",
            user=request.user
        )
        
        return Response({
            'success': True,
            'message': f'Agent {name} created successfully',
            'agent_id': agent.id,
        }, status=status.HTTP_201_CREATED)
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# MONTHLY LOANS DATA API
# ============================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_monthly_loans_api(request):
    """
    Get monthly loans data for the current year
    Returns loan count for each month (Jan-Dec)
    """
    try:
        from datetime import datetime
        from django.db.models.functions import ExtractMonth
        
        current_year = datetime.now().year
        monthly_data = [0] * 12
        
        # Get loans assigned to current employee, grouped by month
        loans = Loan.objects.filter(
            assigned_employee=request.user,
            assigned_at__year=current_year
        ).annotate(month=ExtractMonth('assigned_at')).values('month').annotate(count=Count('id'))
        
        # Build monthly data array
        for item in loans:
            if item['month'] and 1 <= item['month'] <= 12:
                monthly_data[item['month'] - 1] = item['count']
        
        return Response({
            'success': True,
            'monthly_data': monthly_data,
            'year': current_year
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e),
            'monthly_data': [0] * 12
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_all_loans_history_api(request):
    """Get all loans created/assigned to the employee"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        from .models import LoanApplication, Applicant
        from datetime import datetime
        from django.core.paginator import Paginator
        from django.db.models import Q
        
        # Get filters
        status_filter = request.GET.get('status', '').strip()
        loan_type_filter = request.GET.get('loan_type', '').strip()
        search_query = request.GET.get('search', '').strip()
        page = int(request.GET.get('page', 1))
        limit = int(request.GET.get('limit', 20))
        
        # Base queryset - get all loans assigned to or created by this employee
        queryset = LoanApplication.objects.filter(
            assigned_employee=request.user
        ).select_related('applicant').order_by('-created_at')
        
        # Apply status filter
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Apply loan type filter  
        if loan_type_filter:
            queryset = queryset.filter(applicant__loan_type=loan_type_filter)
        
        # Apply search filter
        if search_query:
            queryset = queryset.filter(
                Q(applicant__full_name__icontains=search_query) |
                Q(applicant__mobile__icontains=search_query) |
                Q(applicant__id__icontains=search_query)
            )
        
        # Pagination
        paginator = Paginator(queryset, limit)
        page_obj = paginator.get_page(page)
        
        # Build response
        loans_data = []
        for loan in page_obj:
            applicant = loan.applicant
            
            loans_data.append({
                'id': loan.id,
                'applicant_id': applicant.id,
                'applicant_name': applicant.full_name,
                'mobile': applicant.mobile,
                'email': applicant.email,
                'city': applicant.city or 'N/A',
                'loan_type': applicant.loan_type or 'N/A',
                'loan_amount': float(applicant.loan_amount) if applicant.loan_amount else 0,
                'loan_purpose': applicant.loan_purpose or 'N/A',
                'status': loan.status,
                'created_date': loan.created_at.strftime('%Y-%m-%d') if loan.created_at else '',
                'created_time': loan.created_at.strftime('%H:%M') if loan.created_at else '',
                'applicant_photo': applicant.photo.url if applicant.photo else None,
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


