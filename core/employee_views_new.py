"""
Employee Panel Views - Complete Implementation
- All Loans Page
- New Entry Requests Page
- Dashboard Statistics
- Loan Actions (Approve/Reject/Disburse)
- Agent Management

Uses Loan model as single source of truth
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.http import JsonResponse
from django.db.models import Sum, Count, Q, F
from django.contrib import messages
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import json
from decimal import Decimal
from datetime import timedelta

from .models import User, Loan, Agent, ActivityLog, LoanDocument

# ============================================================
# EMPLOYEE DASHBOARD
# ============================================================

@login_required
@require_http_methods(["GET"])
def employee_dashboard(request):
    """Employee dashboard with stats and overview"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    return render(request, 'core/employee/dashboard.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_dashboard_stats(request):
    """Employee dashboard statistics
    Returns counts of loans by status assigned to employee
    Uses Loan model as source of truth
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Get all loans assigned to this employee
        loans = Loan.objects.filter(assigned_employee=request.user)
        
        # Calculate stats
        total_loans = loans.count()
        waiting_count = loans.filter(status='waiting').count()
        follow_up_count = loans.filter(status='follow_up').count()
        in_processing = waiting_count + follow_up_count
        approved = loans.filter(status='approved').count()
        rejected = loans.filter(status='rejected').count()
        disbursed = loans.filter(status='disbursed').count()
        
        # Calculate totals
        total_amount = loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or Decimal('0')
        approved_amount = loans.filter(status='approved').aggregate(Sum('loan_amount'))['loan_amount__sum'] or Decimal('0')
        disbursed_amount = loans.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or Decimal('0')
        
        return Response({
            'success': True,
            'total_loans': total_loans,
            'in_processing': in_processing,
            'waiting': waiting_count,
            'follow_up': follow_up_count,
            'approved': approved,
            'rejected': rejected,
            'disbursed': disbursed,
            'total_amount': float(total_amount),
            'approved_amount': float(approved_amount),
            'disbursed_amount': float(disbursed_amount),
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# EMPLOYEE ALL LOANS PAGE
# ============================================================

@login_required
@require_http_methods(["GET"])
def employee_all_loans(request):
    """Employee: View all loans assigned to them"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    return render(request, 'core/employee/all_loans.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_all_loans_api(request):
    """API endpoint for all loans assigned to employee
    
    Returns:
    - All loans assigned to this employee
    - Summary counts at top (Total, Approved, Rejected, Disbursed)
    - Table data with all required columns
    
    Query Params:
    - search: Search by applicant name, phone, email
    - status: Filter by status
    - page: Pagination
    - limit: Records per page
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Get filter parameters
        search = request.GET.get('search', '').strip()
        status_filter = request.GET.get('status', '').strip()
        page = int(request.GET.get('page', 1))
        limit = int(request.GET.get('limit', 20))
        
        # Base queryset: ONLY loans assigned to this employee
        queryset = Loan.objects.filter(
            assigned_employee=request.user
        ).select_related('assigned_agent', 'created_by').order_by('-created_at')
        
        # Apply filters
        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search) |
                Q(mobile_number__icontains=search) |
                Q(email__icontains=search)
            )
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Get summary counts from SAME queryset
        total_loans = queryset.count()
        approved_count = queryset.filter(status='approved').count()
        rejected_count = queryset.filter(status='rejected').count()
        disbursed_count = queryset.filter(status='disbursed').count()
        
        # Pagination
        from django.core.paginator import Paginator
        paginator = Paginator(queryset, limit)
        page_obj = paginator.get_page(page)
        
        # Build loan data
        loans_data = []
        for loan in page_obj:
            submitted_by = 'Unknown'
            if loan.assigned_agent:
                submitted_by = loan.assigned_agent.name or loan.assigned_agent.user.get_full_name() if loan.assigned_agent.user else 'Unknown'
            
            hours_pending = loan.get_hours_since_assignment() if hasattr(loan, 'get_hours_since_assignment') else 0
            
            loans_data.append({
                'id': loan.id,
                'loan_id': f'LOAN-{loan.id:06d}',
                'applicant_name': loan.full_name or 'N/A',
                'mobile': loan.mobile_number or '',
                'loan_type': loan.loan_type or 'N/A',
                'loan_amount': float(loan.loan_amount) if loan.loan_amount else 0,
                'tenure_months': loan.tenure_months or 0,
                'remarks': loan.remarks or '',
                'submitted_by': submitted_by,
                'assigned_date': loan.assigned_at.strftime('%Y-%m-%d') if loan.assigned_at else '-',
                'created_date': loan.created_at.strftime('%Y-%m-%d') if loan.created_at else '-',
                'created_time': loan.created_at.strftime('%H:%M') if loan.created_at else '',
                'status': loan.status,
                'status_display': loan.get_status_display(),
            })
        
        return Response({
            'success': True,
            'summary': {
                'total_loans': total_loans,
                'approved': approved_count,
                'rejected': rejected_count,
                'disbursed': disbursed_count,
            },
            'loans': loans_data,
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_items': total_loans,
                'items_per_page': limit,
            }
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# EMPLOYEE NEW ENTRY REQUEST PAGE
# ============================================================

@login_required
@require_http_methods(["GET"])
def employee_new_entry_request_page(request):
    """Render new entry request page for employee"""
    if request.user.role != 'employee':
        return redirect('dashboard')
    
    return render(request, 'core/employee/new_entry_request.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_new_entry_requests_api(request):
    """API endpoint for new entry requests (loans in WAITING or FOLLOWUP status)
    
    Returns:
    - Only loans assigned to this employee
    - Only status = WAITING or FOLLOWUP
    - With Hours Pending calculated
    - All required columns for table
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Get filter parameters
        search = request.GET.get('search', '').strip()
        page = int(request.GET.get('page', 1))
        limit = int(request.GET.get('limit', 20))
        
        # Base queryset: ONLY loans assigned to employee with WAITING or FOLLOW_UP status
        queryset = Loan.objects.filter(
            assigned_employee=request.user,
            status__in=['waiting', 'follow_up']
        ).select_related('assigned_agent', 'created_by').order_by('-assigned_at')
        
        # Apply search
        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search) |
                Q(mobile_number__icontains=search) |
                Q(email__icontains=search)
            )
        
        total_count = queryset.count()
        
        # Pagination
        from django.core.paginator import Paginator
        paginator = Paginator(queryset, limit)
        page_obj = paginator.get_page(page)
        
        # Build loan data
        loans_data = []
        for loan in page_obj:
            hours_pending = loan.get_hours_since_assignment() if hasattr(loan, 'get_hours_since_assignment') else 0
            
            loans_data.append({
                'id': loan.id,
                'loan_id': f'LOAN-{loan.id:06d}',
                'applicant_name': loan.full_name or 'N/A',
                'loan_type': loan.loan_type or 'N/A',
                'loan_amount': float(loan.loan_amount) if loan.loan_amount else 0,
                'assigned_date': loan.assigned_at.strftime('%Y-%m-%d %H:%M') if loan.assigned_at else '-',
                'hours_pending': hours_pending,
                'status': loan.status,
                'status_display': loan.get_status_display(),
            })
        
        return Response({
            'success': True,
            'loans': loans_data,
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_items': total_count,
                'items_per_page': limit,
            }
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# EMPLOYEE LOAN DETAIL PAGE
# ============================================================

@login_required
@require_http_methods(["GET"])
def employee_loan_detail_page(request, loan_id):
    """Render loan detail page for employee"""
    if request.user.role != 'employee':
        return redirect('dashboard')
    
    try:
        # Verify loan is assigned to this employee
        loan = Loan.objects.get(id=loan_id, assigned_employee=request.user)
        return render(request, 'core/employee/loan_detail.html', {'loan_id': loan_id})
    except Loan.DoesNotExist:
        messages.error(request, 'Loan not found or not assigned to you')
        return redirect('employee_new_entry_request')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_loan_detail_api(request, loan_id):
    """API endpoint for full loan detail
    
    Shows:
    - Full application details (read-only)
    - All uploaded documents
    - Current status
    - Action buttons based on status
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Verify loan is assigned to this employee
        loan = Loan.objects.select_related(
            'assigned_agent', 'assigned_employee', 'created_by'
        ).prefetch_related('documents').get(
            id=loan_id,
            assigned_employee=request.user
        )
        
        # Get documents
        documents = []
        for doc in loan.documents.all():
            documents.append({
                'id': doc.id,
                'type': doc.get_document_type_display(),
                'file_url': doc.file.url if doc.file else None,
                'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M'),
            })
        
        # Get agent info
        agent_name = 'Unknown'
        if loan.assigned_agent:
            agent_name = loan.assigned_agent.name
        
        # Determine available actions based on status
        available_actions = []
        if loan.status in ['waiting', 'follow_up']:
            available_actions = ['approve', 'reject']
        elif loan.status == 'approved':
            available_actions = ['disburse']
        
        hours_pending = loan.get_hours_since_assignment() if hasattr(loan, 'get_hours_since_assignment') else 0
        
        return Response({
            'success': True,
            'loan': {
                'id': loan.id,
                'loan_id': f'LOAN-{loan.id:06d}',
                'applicant': {
                    'full_name': loan.full_name,
                    'mobile_number': loan.mobile_number,
                    'email': loan.email,
                    'city': loan.city,
                    'state': loan.state,
                    'pin_code': loan.pin_code,
                },
                'loan_details': {
                    'type': loan.loan_type,
                    'amount': float(loan.loan_amount),
                    'tenure_months': loan.tenure_months,
                    'interest_rate': float(loan.interest_rate) if loan.interest_rate else 0,
                    'emi': float(loan.emi) if loan.emi else 0,
                    'purpose': loan.loan_purpose,
                },
                'bank_details': {
                    'bank_name': loan.bank_name,
                    'account_number': loan.bank_account_number,
                    'ifsc_code': loan.bank_ifsc_code,
                    'type': loan.bank_type,
                },
                'status': loan.status,
                'status_display': loan.get_status_display(),
                'assigned_date': loan.assigned_at.strftime('%Y-%m-%d %H:%M') if loan.assigned_at else '-',
                'assigned_by_name': loan.created_by.get_full_name() if loan.created_by else 'System',
                'hours_pending': hours_pending,
                'agent_name': agent_name,
                'documents': documents,
                'available_actions': available_actions,
                'remarks': loan.remarks,
            }
        }, status=status.HTTP_200_OK)
    
    except Loan.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Loan not found or not assigned to you'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# EMPLOYEE LOAN ACTIONS (Approve/Reject/Disburse)
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_approve_loan_api(request, loan_id):
    """Employee approves a loan
    
    - Changes status to APPROVED
    - Sets action_taken_at timestamp
    - Immediately visible in Admin panel
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        loan = Loan.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify status allows approval
        if loan.status not in ['waiting', 'follow_up']:
            return Response({
                'success': False,
                'error': f'Cannot approve loan in {loan.status} status'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Perform approval
        loan.status = 'approved'
        loan.action_taken_at = timezone.now()
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_approved',
            description=f"Employee {request.user.get_full_name()} approved loan for {loan.full_name}",
            user=request.user,
            related_loan=loan
        )
        
        return Response({
            'success': True,
            'message': 'Loan approved successfully',
            'new_status': 'approved'
        }, status=status.HTTP_200_OK)
    
    except Loan.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Loan not found or not assigned to you'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_reject_loan_api(request, loan_id):
    """Employee rejects a loan
    
    - Changes status to REJECTED
    - Sets action_taken_at timestamp
    - Stores rejection reason if provided
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        loan = Loan.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify status allows rejection
        if loan.status not in ['waiting', 'follow_up']:
            return Response({
                'success': False,
                'error': f'Cannot reject loan in {loan.status} status'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get rejection reason
        data = request.data if hasattr(request, 'data') else {}
        rejection_reason = data.get('reason', '').strip() if isinstance(data, dict) else ''
        
        # Perform rejection
        loan.status = 'rejected'
        loan.action_taken_at = timezone.now()
        if rejection_reason:
            loan.remarks = f"Rejection reason: {rejection_reason}"
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_rejected',
            description=f"Employee {request.user.get_full_name()} rejected loan for {loan.full_name}",
            user=request.user,
            related_loan=loan
        )
        
        return Response({
            'success': True,
            'message': 'Loan rejected successfully',
            'new_status': 'rejected'
        }, status=status.HTTP_200_OK)
    
    except Loan.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Loan not found or not assigned to you'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_disburse_loan_api(request, loan_id):
    """Employee marks loan as disbursed
    
    - Changes status to DISBURSED
    - Sets action_taken_at and disbursed_at timestamp
    - Stores disbursement amount if different from loan amount
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        loan = Loan.objects.get(id=loan_id, assigned_employee=request.user)
        
        # Verify status allows disbursement (must be approved first)
        if loan.status != 'approved':
            return Response({
                'success': False,
                'error': f'Loan must be approved before disbursement. Current status: {loan.status}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get disbursement details
        data = request.data if hasattr(request, 'data') else {}
        disbursement_amount = data.get('amount', str(loan.loan_amount)) if isinstance(data, dict) else str(loan.loan_amount)
        
        try:
            disbursement_amount = Decimal(disbursement_amount)
        except:
            disbursement_amount = loan.loan_amount
        
        # Perform disbursement
        loan.status = 'disbursed'
        loan.action_taken_at = timezone.now()
        loan.save()
        
        # Log activity
        ActivityLog.objects.create(
            action='loan_disbursed',
            description=f"Employee {request.user.get_full_name()} disbursed loan for {loan.full_name} - Amount: {disbursement_amount}",
            user=request.user,
            related_loan=loan
        )
        
        return Response({
            'success': True,
            'message': 'Loan disbursed successfully',
            'new_status': 'disbursed'
        }, status=status.HTTP_200_OK)
    
    except Loan.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Loan not found or not assigned to you'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# EMPLOYEE MY AGENTS PAGE
# ============================================================

@login_required
@require_http_methods(["GET"])
def employee_my_agents_page(request):
    """Render my agents page for employee"""
    if request.user.role != 'employee':
        return redirect('dashboard')
    
    return render(request, 'core/employee/my_agents.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_my_agents_api(request):
    """API endpoint for agents created by/assigned to employee
    
    Shows:
    - All agents created by this employee
    - All agents assigned to this employee (if any)
    - Mark creation source (Admin vs Employee-Created)
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Get agents created by this employee
        agents = Agent.objects.filter(created_by=request.user).exclude(status='blocked').order_by('-created_at')
        
        agents_data = []
        for agent in agents:
            # Count of loans created by this agent
            loan_count = Loan.objects.filter(assigned_agent=agent).count()
            
            agents_data.append({
                'id': agent.id,
                'name': agent.name,
                'email': agent.email,
                'phone': agent.phone,
                'city': agent.city,
                'state': agent.state,
                'status': agent.status,
                'created_by': 'Employee' if agent.created_by and agent.created_by.role == 'employee' else 'Admin',
                'created_at': agent.created_at.strftime('%Y-%m-%d'),
                'total_loans': loan_count,
            })
        
        return Response({
            'success': True,
            'agents': agents_data,
            'total': len(agents_data)
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_add_agent_api(request):
    """Employee adds a new agent under themselves
    
    - Creates new User with role=agent
    - Creates Agent profile linked to employee
    - Agent is marked as Employee-Created
    - Agent also visible in Admin panel
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can add agents'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Get form data
        name = request.data.get('name', '').strip()
        phone = request.data.get('phone', '').strip()
        email = request.data.get('email', '').strip()
        password = request.data.get('password', '').strip()
        city = request.data.get('city', '').strip()
        state = request.data.get('state', '').strip()
        
        # Validate required fields
        if not all([name, phone, email, password]):
            return Response({
                'success': False,
                'error': 'Name, Phone, Email, and Password are required'
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
            phone=phone,
            first_name=name.split()[0] if name else 'Agent',
            last_name=' '.join(name.split()[1:]) if len(name.split()) > 1 else '',
        )
        
        # Create Agent profile
        agent = Agent.objects.create(
            user=user,
            name=name,
            phone=phone,
            email=email,
            city=city,
            state=state,
            status='active',
            created_by=request.user  # Link to employee who created it
        )
        
        # Log activity
        ActivityLog.objects.create(
            action='agent_created',
            description=f"Employee {request.user.get_full_name()} created agent {name}",
            user=request.user,
            related_agent=agent
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_update_agent_api(request, agent_id):
    """Employee updates an agent they created"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can update agents'}, status=status.HTTP_403_FORBIDDEN)

    try:
        agent = get_object_or_404(Agent, id=agent_id, created_by=request.user)
        data = request.data

        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        email = data.get('email', '').strip()
        status_value = data.get('status', '').strip() or agent.status
        gender = data.get('gender', '').strip()
        address = data.get('address', '').strip()
        pin_code = data.get('pin_code', '').strip()
        state = data.get('state', '').strip()
        city = data.get('city', '').strip()

        if name:
            agent.name = name
        if phone:
            agent.phone = phone
        if email:
            agent.email = email
        if status_value:
            agent.status = status_value
        agent.gender = gender if gender else agent.gender
        agent.address = address if address else agent.address
        agent.pin_code = pin_code if pin_code else agent.pin_code
        agent.state = state if state else agent.state
        agent.city = city if city else agent.city

        if 'photo' in request.FILES:
            agent.profile_photo = request.FILES.get('photo')

        agent.save()

        if agent.user:
            if name:
                parts = name.split()
                agent.user.first_name = parts[0]
                agent.user.last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''
            if phone:
                agent.user.phone = phone
            if email:
                agent.user.email = email
            agent.user.save()

        return Response({
            'success': True,
            'message': 'Agent updated successfully'
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_delete_agent_api(request, agent_id):
    """Employee deletes (blocks) an agent they created"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can delete agents'}, status=status.HTTP_403_FORBIDDEN)

    try:
        agent = get_object_or_404(Agent, id=agent_id, created_by=request.user)

        agent.status = 'blocked'
        agent.save()

        if agent.user:
            agent.user.is_active = False
            agent.user.save()

        return Response({
            'success': True,
            'message': 'Agent removed successfully'
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_update_loan_api(request, loan_id):
    """Employee updates basic loan fields for assigned loan"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can update loans'}, status=status.HTTP_403_FORBIDDEN)

    try:
        loan = get_object_or_404(Loan, id=loan_id, assigned_employee=request.user)
        data = request.data

        if 'loan_amount' in data:
            try:
                loan.loan_amount = float(data.get('loan_amount') or 0)
            except (TypeError, ValueError):
                pass
        if 'tenure_months' in data:
            try:
                loan.tenure_months = int(data.get('tenure_months') or 0)
            except (TypeError, ValueError):
                pass
        if 'loan_type' in data and data.get('loan_type'):
            loan.loan_type = str(data.get('loan_type')).lower()
        if 'remarks' in data:
            loan.remarks = data.get('remarks') or ''

        loan.save()

        ActivityLog.objects.create(
            action='loan_updated',
            description=f"Employee {request.user.get_full_name()} updated loan #{loan.id}",
            user=request.user,
            related_loan=loan
        )

        return Response({
            'success': True,
            'message': 'Loan updated successfully'
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_delete_loan_api(request, loan_id):
    """Employee deletes (rejects) an assigned loan"""
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can delete loans'}, status=status.HTTP_403_FORBIDDEN)

    try:
        loan = get_object_or_404(Loan, id=loan_id, assigned_employee=request.user)
        reason = request.data.get('reason', '').strip() if isinstance(request.data, dict) else ''
        if not reason:
            reason = 'Deleted by employee'

        deleted_id = loan.id
        loan.delete()

        ActivityLog.objects.create(
            action='status_updated',
            description=f"Employee {request.user.get_full_name()} deleted loan #{deleted_id}. Reason: {reason}",
            user=request.user
        )

        return Response({
            'success': True,
            'message': 'Loan removed successfully'
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# LEGACY COMPATIBILITY - Keep old function names
# ============================================================

def employee_assigned_loans(request):
    """Redirect to new entry request page"""
    return employee_new_entry_request_page(request)


def employee_profile(request):
    """Employee profile view"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    context = {'user': request.user}
    return render(request, 'core/employee/profile.html', context)


def employee_settings(request):
    """Employee settings view"""
    if request.user.role != 'employee':
        messages.error(request, 'Access denied. Employee only.')
        return redirect('dashboard')
    
    context = {'user': request.user}
    return render(request, 'core/employee/settings.html', context)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_get_assigned_loans(request):
    """Legacy API endpoint - redirect to new endpoint"""
    return employee_new_entry_requests_api(request)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_loan_action(request):
    """Legacy endpoint for loan actions"""
    action = request.data.get('action', '').strip()
    loan_id = request.data.get('loan_id')
    
    if action == 'approve':
        return employee_approve_loan_api(request, loan_id)
    elif action == 'reject':
        return employee_reject_loan_api(request, loan_id)
    elif action == 'disburse':
        return employee_disburse_loan_api(request, loan_id)
    else:
        return Response({'error': 'Invalid action'}, status=status.HTTP_400_BAD_REQUEST)

# ============================================================
# EMPLOYEE PROFILE PHOTO UPLOAD
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def employee_upload_profile_photo(request):
    """Upload profile photo for employee
    
    Returns:
    - success: True/False
    - message: Success/error message
    - photo_url: URL of uploaded photo
    """
    if request.user.role != 'employee':
        return Response({'error': 'Only employees can access'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        if 'profile_photo' not in request.FILES:
            return Response({'error': 'No photo provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        photo = request.FILES['profile_photo']
        
        # Update user profile photo
        request.user.profile_photo = photo
        request.user.save()
        
        return Response({
            'success': True,
            'message': 'Photo uploaded successfully',
            'photo_url': request.user.profile_photo.url if request.user.profile_photo else None
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
