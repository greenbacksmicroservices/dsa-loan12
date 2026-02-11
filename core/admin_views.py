# ============ ADMIN DASHBOARD & ALL LOANS VIEWS ============

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Sum, Count, F, Prefetch
from django.core.paginator import Paginator
from django.utils import timezone
import json
import logging

from .models import LoanApplication, Applicant, ApplicantDocument, LoanAssignment, LoanStatusHistory, User, Agent, Loan
from .decorators import admin_required

logger = logging.getLogger(__name__)


@login_required(login_url='admin_login')
@admin_required
def admin_dashboard(request):
    """
    ADMIN DASHBOARD - Shows real statistics and summary
    """
    try:
        # Get all Loan counts by status (real-time)
        new_entry_count = Loan.objects.filter(status='new_entry').count()
        in_processing_count = Loan.objects.filter(status='waiting').count()
        followup_count = Loan.objects.filter(status='follow_up').count()
        approved_count = Loan.objects.filter(status='approved').count()
        rejected_count = Loan.objects.filter(status='rejected').count()
        disbursed_count = Loan.objects.filter(status='disbursed').count()
        
        # Team counts
        total_agents = Agent.objects.count()
        active_agents = Agent.objects.filter(status='active').count()
        total_employees = User.objects.filter(role='employee').count()
        active_employees = User.objects.filter(role='employee', is_active=True).count()
        total_subadmins = User.objects.filter(role='subadmin').count()
        
        # Calculate statistics
        total_applications = (new_entry_count + in_processing_count + followup_count +
                            approved_count + rejected_count + disbursed_count)
        
        approval_rate = 0
        if total_applications > 0:
            approval_rate = int((approved_count / total_applications) * 100)
        
        rejection_rate = 0
        if total_applications > 0:
            rejection_rate = int((rejected_count / total_applications) * 100)
        
        disbursement_rate = 0
        if total_applications > 0:
            disbursement_rate = int((disbursed_count / total_applications) * 100)
        
        context = {
            'page_title': 'Admin Dashboard',
            'new_entry_count': new_entry_count,
            'in_processing_count': in_processing_count,
            'followup_count': followup_count,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'disbursed_count': disbursed_count,
            'total_applications': total_applications,
            'total_agents': total_agents,
            'active_agents': active_agents,
            'total_employees': total_employees,
            'active_employees': active_employees,
            'total_subadmins': total_subadmins,
            'approval_rate': approval_rate,
            'rejection_rate': rejection_rate,
            'disbursement_rate': disbursement_rate,
        }
        return render(request, 'core/admin/admin_dashboard.html', context)
    except Exception as e:
        logger.error(f"Error loading admin dashboard: {str(e)}")
        context = {'page_title': 'Admin Dashboard', 'error': str(e)}
        return render(request, 'core/admin/admin_dashboard.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_all_loans(request):
    """
    ADMIN ALL LOANS - Shows comprehensive table with all loan details
    Displays loans in table format with 10 required columns
    """
    from django.db.models import Q
    
    # Get search and status filter parameters
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    
    # Start with all loans ordered by creation date (newest first)
    loans = Loan.objects.all().order_by('-created_at')
    
    # Apply search filter if provided
    if search_query:
        loans = loans.filter(
            Q(full_name__icontains=search_query) |
            Q(mobile_number__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(user_id__icontains=search_query)
        )

    # Apply status filter if provided
    if status_filter:
        loans = loans.filter(status=status_filter)
    
    context = {
        'page_title': 'All Loans - Master Database',
        'loans': loans,
        'search_query': search_query,
        'status_filter': status_filter,
        'total_loans': loans.count(),
    }
    return render(request, 'core/admin/all_loans.html', context)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_dashboard_stats(request):
    """
    DASHBOARD STATS API - Returns stats ONLY (no loans data)
    Called by admin_dashboard template
    """
    try:
        total_loans = Loan.objects.count()
        stats = {
            'total': total_loans,
            'new_entry': Loan.objects.filter(status='new_entry').count(),
            'processing': Loan.objects.filter(status='waiting').count(),
            'follow_up': Loan.objects.filter(status='follow_up').count(),
            'approved': Loan.objects.filter(status='approved').count(),
            'rejected': Loan.objects.filter(status='rejected').count(),
            'disbursed': Loan.objects.filter(status='disbursed').count(),
            'total_value': Loan.objects.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
            'approved_value': Loan.objects.filter(status='approved').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
            'disbursed_value': Loan.objects.filter(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
            'pending_value': Loan.objects.exclude(status='disbursed').aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
        }
        return JsonResponse(stats)
    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_all_loans(request):
    """
    LOANS LISTING API - Returns loans ONLY (no stats data)
    Called by all_loans template
    """
    try:
        status_filter = request.GET.get('status', 'all')
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 25))
        search = request.GET.get('search', '').strip()
        
        query = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
        ).prefetch_related(
            'documents',
            'status_history'
        )
        
        status_map = {
            'approved': 'Approved',
            'rejected': 'Rejected',
            'disbursed': 'Disbursed',
            'new_entry': 'New Entry',
            'waiting': 'Waiting for Processing',
            'follow_up': 'Required Follow-up',
        }
        
        if status_filter != 'all' and status_filter in status_map:
            query = query.filter(status=status_map[status_filter])
        
        if search:
            query = query.filter(
                Q(applicant__full_name__icontains=search) |
                Q(applicant__email__icontains=search) |
                Q(applicant__mobile__icontains=search) |
                Q(id__icontains=search)
            )
        
        total_count = query.count()
        query = query.order_by('-created_at')
        
        paginator = Paginator(query, per_page)
        page_obj = paginator.get_page(page)
        
        loans_data = []
        for loan in page_obj:
            agent_name = ''
            if loan.assigned_agent:
                agent_name = loan.assigned_agent.name
            
            employee_name = ''
            if loan.assigned_employee:
                employee_name = loan.assigned_employee.get_full_name()
            
            loans_data.append({
                'id': loan.id,
                'loan_id': f'LOAN-{loan.id:06d}',
                'applicant_name': loan.applicant.full_name if loan.applicant else 'N/A',
                'applicant_email': loan.applicant.email if loan.applicant else 'N/A',
                'loan_type': loan.applicant.loan_type if loan.applicant else 'N/A',
                'loan_amount': str(loan.applicant.loan_amount) if loan.applicant and loan.applicant.loan_amount else '0',
                'agent_name': agent_name,
                'employee_name': employee_name,
                'status': loan.status,
                'status_display': loan.get_status_display(),
                'submitted_date': loan.created_at.strftime('%Y-%m-%d'),
                'last_updated_date': loan.updated_at.strftime('%Y-%m-%d'),
            })
        
        return JsonResponse({
            'success': True,
            'loans': loans_data,
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_count': total_count,
                'per_page': per_page
            }
        })
    
    except Exception as e:
        logger.error(f"Error fetching loans: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
def admin_loan_detail(request, loan_id):
    """
    Detailed view page for a single loan
    """
    try:
        loan = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
        ).prefetch_related(
            'documents',
            'status_history'
        ).get(id=loan_id)
        
        context = {
            'page_title': f'Loan Details - {loan.applicant.full_name if loan.applicant else "Loan"}',
            'loan': loan,
            'applicant': loan.applicant,
            'documents': loan.documents.all(),
            'status_history': loan.status_history.all(),
        }
        
        return render(request, 'core/admin/all_loans_detail.html', context)
    
    except LoanApplication.DoesNotExist:
        return redirect('admin_all_loans')


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_loan_detail(request, loan_id):
    """
    API endpoint to fetch full loan details in JSON format
    """
    try:
        loan = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
        ).prefetch_related(
            'documents',
            'status_history'
        ).get(id=loan_id)
        
        applicant_data = {
            'full_name': loan.applicant.full_name if loan.applicant else 'N/A',
            'email': loan.applicant.email if loan.applicant else 'N/A',
            'mobile': loan.applicant.mobile if loan.applicant else 'N/A',
            'city': loan.applicant.city if loan.applicant else 'N/A',
            'state': loan.applicant.state if loan.applicant else 'N/A',
            'pin_code': loan.applicant.pin_code if loan.applicant else 'N/A',
        }
        
        loan_data = {
            'loan_type': loan.applicant.loan_type if loan.applicant else 'N/A',
            'loan_amount': str(loan.applicant.loan_amount) if loan.applicant and loan.applicant.loan_amount else '0.00',
            'tenure_months': loan.applicant.tenure_months if loan.applicant else 'N/A',
            'interest_rate': str(loan.applicant.interest_rate) if loan.applicant and loan.applicant.interest_rate else 'N/A',
            'loan_purpose': loan.applicant.loan_purpose if loan.applicant else 'N/A',
            'bank_name': loan.applicant.bank_name if loan.applicant else 'N/A',
        }
        
        documents_data = []
        for doc in loan.documents.all():
            documents_data.append({
                'id': doc.id,
                'type': doc.get_document_type_display() if hasattr(doc, 'get_document_type_display') else str(doc.document_type),
                'file_url': doc.file.url if doc.file else '#',
                'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else 'N/A',
            })
        
        return JsonResponse({
            'success': True,
            'loan_id': loan.id,
            'status': loan.status,
            'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'applicant': applicant_data,
            'loan_details': loan_data,
            'documents': documents_data,
            'agent_name': loan.assigned_agent.name if loan.assigned_agent else 'N/A',
            'employee_name': loan.assigned_employee.get_full_name() if loan.assigned_employee else 'N/A',
        })
    
    except LoanApplication.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Loan not found'
        }, status=404)


@login_required(login_url='admin_login')
@admin_required
def admin_edit_loan(request, loan_id):
    """
    Edit loan page
    """
    loan = get_object_or_404(LoanApplication, id=loan_id)
    context = {
        'page_title': f'Edit Loan - {loan.applicant.full_name if loan.applicant else "Loan"}',
        'loan': loan,
    }
    return render(request, 'core/admin/all_loans_edit.html', context)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_delete_loan(request, loan_id):
    """
    Soft delete a loan
    """
    try:
        loan = get_object_or_404(LoanApplication, id=loan_id)
        loan.is_deleted = True
        loan.deleted_at = timezone.now()
        loan.save()
        
        logger.info(f"Loan {loan_id} soft deleted by {request.user.username}")
        return JsonResponse({
            'success': True,
            'message': 'Loan deleted successfully'
        })
    
    except Exception as e:
        logger.error(f"Error deleting loan: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_reassign_loan(request, loan_id):
    """
    Reassign loan to different employee
    """
    try:
        data = json.loads(request.body)
        new_employee_id = data.get('employee_id')
        
        loan = get_object_or_404(LoanApplication, id=loan_id)
        new_employee = get_object_or_404(User, id=new_employee_id, role='employee')
        
        loan.assigned_employee = new_employee
        loan.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Loan reassigned to {new_employee.get_full_name()}'
        })
    
    except Exception as e:
        logger.error(f"Error reassigning loan: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_loan_stats(request):
    """
    Get statistics for all loans
    """
    try:
        total_loans = LoanApplication.objects.filter(is_deleted=False).count()
        approved = LoanApplication.objects.filter(status='Approved', is_deleted=False).count()
        rejected = LoanApplication.objects.filter(status='Rejected', is_deleted=False).count()
        disbursed = LoanApplication.objects.filter(status='Disbursed', is_deleted=False).count()
        
        return JsonResponse({
            'success': True,
            'stats': {
                'total_loans': total_loans,
                'approved': approved,
                'rejected': rejected,
                'disbursed': disbursed,
                'pending': total_loans - approved - rejected - disbursed,
            }
        })
    
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_admin_all_loans(request):
    """
    API endpoint returning all loans for admin all-loans page
    """
    try:
        status_filter = request.GET.get('status', '').strip()
        search = request.GET.get('search', '').strip()
        
        query = Loan.objects.all().select_related(
            'assigned_employee',
            'assigned_agent',
        )
        
        # Filter by status if specified
        if status_filter:
            query = query.filter(status=status_filter)
        
        # Filter by search term
        if search:
            query = query.filter(
                Q(full_name__icontains=search) |
                Q(mobile_number__icontains=search) |
                Q(email__icontains=search) |
                Q(id__icontains=search)
            )
        
        # Get loans data
        loans_data = []
        for loan in query.order_by('-created_at')[:100]:
            loans_data.append({
                'id': loan.id,
                'applicant_name': loan.full_name or 'N/A',
                'phone': loan.mobile_number or 'N/A',
                'email': loan.email or 'N/A',
                'loan_amount': float(loan.loan_amount) if loan.loan_amount else 0,
                'status': loan.status,
                'agent': loan.assigned_agent.user.get_full_name() if loan.assigned_agent else '-',
                'employee': loan.assigned_employee.get_full_name() if loan.assigned_employee else '-',
                'date_applied': loan.created_at.strftime('%Y-%m-%d') if loan.created_at else '-',
            })
        
        return JsonResponse({
            'success': True,
            'loans': loans_data
        })
    
    except Exception as e:
        logger.error(f"Error in api_admin_all_loans: {str(e)}")
        return JsonResponse({
            'success': False,
            'loans': [],
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
def admin_subadmin_management(request):
    """Admin page to manage SubAdmins"""
    try:
        subadmins = User.objects.filter(role='subadmin').order_by('-date_joined')
        subadmin_list = []
        for subadmin in subadmins:
            subadmin_list.append({
                'id': subadmin.id,
                'name': subadmin.get_full_name(),
                'email': subadmin.email,
                'is_active': subadmin.is_active,
                'date_joined': subadmin.date_joined
            })
        
        context = {
            'page_title': 'SubAdmin Management',
            'subadmins': subadmins,
            'subadmin_count': subadmins.count(),
        }
        return render(request, 'core/admin/subadmin_management_new.html', context)
    except Exception as e:
        logger.error(f"Error loading subadmin management: {str(e)}")
        return render(request, 'core/admin/subadmin_management_new.html', {'error': str(e)})


@login_required(login_url='admin_login')
@admin_required
@require_http_methods(['POST'])
def api_create_subadmin(request):
    """API to create new SubAdmin"""
    try:
        import json
        from django.core.files.base import ContentFile
        import base64
        
        data = json.loads(request.body)
        
        # Required fields
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        address = data.get('address', '').strip()
        pin = data.get('pin', '').strip()
        state = data.get('state', '').strip()
        photo_base64 = data.get('photo', '')
        
        # Validation
        if not all([username, email, password, name, phone]):
            return JsonResponse({
                'success': False,
                'error': 'Name, Email, Username, Phone, and Password are required'
            }, status=400)
        
        # Check if username exists
        if User.objects.filter(username=username).exists():
            return JsonResponse({
                'success': False,
                'error': 'Username already exists'
            }, status=400)
        
        # Check if email exists
        if User.objects.filter(email=email).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already exists'
            }, status=400)
        
        # Create SubAdmin user
        subadmin = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=name.split()[0] if name else '',
            last_name=' '.join(name.split()[1:]) if len(name.split()) > 1 else '',
            role='subadmin',
            phone=phone,
            address=address,
        )
        
        # Add state if field exists
        if hasattr(subadmin, 'state'):
            subadmin.state = state
        
        # Add pin if field exists
        if hasattr(subadmin, 'pin'):
            subadmin.pin = pin
        
        # Handle photo upload
        if photo_base64:
            try:
                format, imgstr = photo_base64.split(';base64,')
                ext = format.split('/')[-1]
                photo_data = ContentFile(base64.b64decode(imgstr), name=f'subadmin_{username}.{ext}')
                if hasattr(subadmin, 'photo'):
                    subadmin.photo = photo_data
            except:
                pass
        
        subadmin.save()
        
        return JsonResponse({
            'success': True,
            'message': 'SubAdmin created successfully',
            'subadmin': {
                'id': subadmin.id,
                'username': subadmin.username,
                'email': subadmin.email,
                'name': subadmin.get_full_name() or subadmin.username,
                'phone': getattr(subadmin, 'phone', ''),
                'address': getattr(subadmin, 'address', ''),
            }
        })
    
    except Exception as e:
        logger.error(f"Error creating SubAdmin: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_subadmins(request):
    """Get all SubAdmins"""
    try:
        subadmins = User.objects.filter(role='subadmin').values(
            'id', 'username', 'email', 'first_name', 'last_name', 
            'phone', 'address', 'created_at'
        )
        
        subadmin_list = []
        for sub in subadmins:
            subadmin_list.append({
                'id': sub['id'],
                'username': sub['username'],
                'email': sub['email'],
                'name': f"{sub['first_name']} {sub['last_name']}".strip() or sub['username'],
                'phone': sub['phone'] or '-',
                'address': sub['address'] or '-',
                'created': sub['created_at'].strftime('%Y-%m-%d') if sub['created_at'] else '-',
            })
        
        return JsonResponse({
            'success': True,
            'count': len(subadmin_list),
            'subadmins': subadmin_list
        })
    
    except Exception as e:
        logger.error(f"Error fetching SubAdmins: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required(login_url='admin_login')
@admin_required
def add_agent(request):
    """
    Admin page to add new agent/employee/subadmin
    GET: Show form
    POST: Create new agent/employee
    """
    if request.method == 'POST':
        try:
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()
            phone = request.POST.get('phone', '').strip()
            gender = request.POST.get('gender', '').strip()
            address = request.POST.get('address', '').strip()
            password = request.POST.get('password', '').strip()
            role = request.POST.get('role', 'agent').strip()  # agent, employee, subadmin
            photo = request.FILES.get('photo')
            
            # Validate required fields
            if not all([first_name, email, phone, password]):
                messages.error(request, 'Please fill all required fields')
                return render(request, 'core/admin/add_agent.html')
            
            # Validate email format
            if not email or '@' not in email:
                messages.error(request, 'Invalid email address')
                return render(request, 'core/admin/add_agent.html')
            
            # Check if email already exists
            if User.objects.filter(email=email).exists():
                messages.error(request, 'Email already exists')
                return render(request, 'core/admin/add_agent.html')
            
            # Check phone format
            if not phone.isdigit() or len(phone) < 10:
                messages.error(request, 'Invalid phone number. Must be at least 10 digits')
                return render(request, 'core/admin/add_agent.html')

            # Validate password length
            if len(password) < 6:
                messages.error(request, 'Password must be at least 6 characters')
                return render(request, 'core/admin/add_agent.html')
            
            # Generate username from email
            base_username = email.split('@')[0]
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
            
            # Create User account
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role=role,
                phone=phone,
                gender=gender or None,
                address=address
            )
            
            # Handle photo upload
            if photo:
                user.profile_photo = photo
                user.save()
            
            # If role is agent, create Agent profile
            if role == 'agent':
                agent = Agent.objects.create(
                    user=user,
                    name=f"{first_name} {last_name}".strip(),
                    email=email,
                    phone=phone,
                    status='active',
                    gender=gender or None,
                    address=address
                )
                if photo:
                    agent.profile_photo = photo
                    agent.save()
                success_msg = f'Agent {first_name} {last_name} created successfully with username: {username}'
            
            # If role is subadmin, mark as subadmin
            elif role == 'subadmin':
                user.is_subadmin = True
                user.save()
                success_msg = f'SubAdmin {first_name} {last_name} created successfully with username: {username}'
            
            else:  # employee
                success_msg = f'Employee {first_name} {last_name} created successfully with username: {username}'
            
            messages.success(request, success_msg)
            return redirect('admin_all_agents' if role == 'agent' else 'admin_all_employees')
        
        except Exception as e:
            logger.error(f"Error creating agent: {str(e)}")
            messages.error(request, f'Error creating user: {str(e)}')
            return render(request, 'core/admin/add_agent.html')
    
    context = {
        'page_title': 'Add New Agent/Employee',
    }
    return render(request, 'core/admin/add_agent.html', context)


@login_required(login_url='admin_login')
@admin_required
def team_management(request):
    """
    Team Management Overview - Shows employees, agents, and subadmins
    """
    try:
        employees = User.objects.filter(role='employee', is_active=True).order_by('-date_joined')
        agents = Agent.objects.filter(status='active').order_by('-created_at')
        subadmins = User.objects.filter(is_subadmin=True, is_active=True).order_by('-date_joined')
        
        context = {
            'page_title': 'Team Management',
            'employees': employees,
            'agents': agents,
            'subadmins': subadmins,
        }
        return render(request, 'core/admin/team_management.html', context)
    except Exception as e:
        logger.error(f"Error loading team management: {str(e)}")
        messages.error(request, 'Error loading team management')
        return redirect('admin_dashboard')


@login_required(login_url='admin_login')
@admin_required
@require_http_methods(['GET', 'POST'])
def admin_add_loan(request):
    """
    Admin Add New Loan - Create new loan applications
    Allows admin to manually create loan entries with all applicant details
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
                status='New Entry',
                created_by=request.user,
            )
            
            # Handle document uploads
            documents_names = request.POST.getlist('document_name[]')
            documents_files = request.FILES.getlist('document_file[]')
            
            for name, file in zip(documents_names, documents_files):
                if file:
                    ApplicantDocument.objects.create(
                        applicant=loan_application.applicant,
                        document_name=name,
                        document_file=file,
                    )
            
            # Create corresponding Loan entry for master database
            Loan.objects.create(
                full_name=applicant_name,
                email=applicant_email,
                mobile_number=applicant_mobile,
                loan_type=loan_type,
                loan_amount=float(loan_amount_required) if loan_amount_required else 0,
                status='new_entry',
                created_at=timezone.now(),
            )
            
            messages.success(request, f'Loan application for {applicant_name} created successfully!')
            return redirect('admin_all_loans')
        
        except Exception as e:
            logger.error(f"Error creating loan: {str(e)}")
            messages.error(request, f'Error creating loan application: {str(e)}')
            return render(request, 'core/admin/add_loan.html')
    
    context = {
        'page_title': 'Add New Loan Application',
    }
    return render(request, 'core/admin/add_loan.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_join_requests(request):
    """
    Admin Join Requests - Shows pending requests from users wanting to join as SubAdmins/Agents
    """
    try:
        # For now, show an empty list (no join requests table in models)
        # This can be extended with a JoinRequest model later
        join_requests = []
        
        context = {
            'page_title': 'Join Requests',
            'join_requests': join_requests,
            'request_count': len(join_requests),
        }
        return render(request, 'core/admin/join_requests.html', context)
    except Exception as e:
        logger.error(f"Error loading join requests: {str(e)}")
        messages.error(request, 'Error loading join requests')
        return redirect('admin_dashboard')


@login_required(login_url='admin_login')
@admin_required
def admin_new_entries(request):
    """View New Entry applications"""
    applications = LoanApplication.objects.filter(status='New Entry').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'New Entry Applications',
        'applications': applications,
        'status_name': 'New Entry',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_in_processing(request):
    """View In Processing applications"""
    applications = LoanApplication.objects.filter(status='Waiting for Processing').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'In Processing Applications',
        'applications': applications,
        'status_name': 'Waiting for Processing',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_follow_ups(request):
    """View Follow-up required applications"""
    applications = LoanApplication.objects.filter(status='Required Follow-up').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'Follow-up Required Applications',
        'applications': applications,
        'status_name': 'Required Follow-up',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_approved(request):
    """View Approved applications"""
    applications = LoanApplication.objects.filter(status='Approved').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'Approved Applications',
        'applications': applications,
        'status_name': 'Approved',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_rejected(request):
    """View Rejected applications"""
    applications = LoanApplication.objects.filter(status='Rejected').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'Rejected Applications',
        'applications': applications,
        'status_name': 'Rejected',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_disbursed(request):
    """View Disbursed applications"""
    applications = LoanApplication.objects.filter(status='Disbursed').select_related('applicant', 'assigned_employee', 'assigned_agent').order_by('-created_at')
    
    context = {
        'page_title': 'Disbursed Applications',
        'applications': applications,
        'status_name': 'Disbursed',
    }
    return render(request, 'core/admin/status_detail.html', context)


@login_required(login_url='admin_login')
@admin_required
def assign_application(request, app_id):
    """Assign an application to an employee"""
    try:
        application = LoanApplication.objects.get(id=app_id)
    except LoanApplication.DoesNotExist:
        return redirect('admin_new_entries')
    
    # Get all active agents/employees (excluding superusers and staff)
    agents = User.objects.filter(is_active=True, is_staff=False).exclude(is_superuser=True)
    
    if request.method == 'POST':
        agent_id = request.POST.get('agent_id')
        try:
            agent = User.objects.get(id=agent_id)
            application.assigned_employee = agent
            application.status = 'Waiting for Processing'
            application.save()
            return redirect('admin_in_processing')
        except User.DoesNotExist:
            pass
    
    applicant_name = request.GET.get('applicant', application.applicant.full_name)
    
    context = {
        'application': application,
        'applicant_name': applicant_name,
        'agents': agents,
        'page_title': 'Assign Application',
    }
    return render(request, 'core/admin/assign_application.html', context)


@login_required(login_url='admin_login')
@admin_required
def api_get_application_details(request, app_id):
    """API endpoint to fetch full application details"""
    try:
        application = LoanApplication.objects.select_related('applicant', 'assigned_employee').get(id=app_id)
        applicant = application.applicant
        
        # Get existing loans if available
        existing_loans = []
        try:
            # Try to get from applicant model if it has existing loan fields
            if hasattr(applicant, 'existing_loans'):
                existing_loans = applicant.existing_loans if applicant.existing_loans else []
        except:
            pass
        
        data = {
            'success': True,
            'application': {
                'id': application.id,
                'status': application.status,
                'created_at': application.created_at.strftime('%Y-%m-%d %H:%M'),
                'assigned_employee': application.assigned_employee.get_full_name() if application.assigned_employee else 'Not Assigned',
            },
            'applicant': {
                # Section 1: Name & Contact Details
                'full_name': applicant.full_name or '',
                'mobile': applicant.mobile or '',
                'alternate_mobile': getattr(applicant, 'alternate_mobile', '') or '',
                'email': applicant.email or '',
                'father_name': getattr(applicant, 'father_name', '') or '',
                'mother_name': getattr(applicant, 'mother_name', '') or '',
                'date_of_birth': applicant.date_of_birth.strftime('%Y-%m-%d') if hasattr(applicant, 'date_of_birth') and applicant.date_of_birth else '',
                'gender': getattr(applicant, 'gender', '') or '',
                'marital_status': getattr(applicant, 'marital_status', '') or '',
                
                # Permanent Address
                'permanent_address': getattr(applicant, 'permanent_address', '') or '',
                'permanent_landmark': getattr(applicant, 'permanent_landmark', '') or '',
                'permanent_city': getattr(applicant, 'permanent_city', '') or '',
                'permanent_pin': getattr(applicant, 'permanent_pin', '') or '',
                
                # Present Address
                'present_address': getattr(applicant, 'present_address', '') or '',
                'present_landmark': getattr(applicant, 'present_landmark', '') or '',
                'present_city': getattr(applicant, 'present_city', '') or '',
                'present_pin': getattr(applicant, 'present_pin', '') or '',
                
                # Section 2: Occupation & Income Details
                'occupation': getattr(applicant, 'occupation', '') or '',
                'date_of_joining': getattr(applicant, 'date_of_joining', None),
                'year_of_experience': getattr(applicant, 'year_of_experience', '') or '',
                'additional_income': getattr(applicant, 'additional_income', '') or '',
                'extra_income_details': getattr(applicant, 'extra_income_details', '') or '',
                
                # Section 4: Loan Request
                'loan_type': applicant.loan_type or '',
                'loan_amount': str(applicant.loan_amount) if applicant.loan_amount else '',
                'loan_tenure': getattr(applicant, 'loan_tenure', '') or '',
                'charges_fee': getattr(applicant, 'charges_fee', 'No') or 'No',
                
                # Section 6: Financial & Bank Details
                'cibil_score': getattr(applicant, 'cibil_score', '') or '',
                'aadhar_number': getattr(applicant, 'aadhar_number', '') or '',
                'pan_number': getattr(applicant, 'pan_number', '') or '',
                'bank_name': getattr(applicant, 'bank_name', '') or '',
                'account_number': getattr(applicant, 'account_number', '') or '',
                'remarks': getattr(applicant, 'remarks', '') or '',
                'declaration': getattr(applicant, 'declaration', 'No') or 'No',
            },
            'documents': []
        }
        
        # Get documents
        try:
            documents = ApplicantDocument.objects.filter(applicant=applicant)
            for doc in documents:
                data['documents'].append({
                    'name': doc.document_type or 'Document',
                    'url': doc.file.url if doc.file else '',
                    'uploaded': doc.uploaded_at.strftime('%Y-%m-%d') if doc.uploaded_at else ''
                })
        except:
            pass
        
        return JsonResponse(data)
    except LoanApplication.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Application not found'}, status=404)
