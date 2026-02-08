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
    ADMIN DASHBOARD - Shows statistics and summary ONLY
    Separate from admin_all_loans view
    """
    context = {
        'page_title': 'Admin Dashboard',
    }
    return render(request, 'core/admin/admin_dashboard.html', context)


@login_required(login_url='admin_login')
@admin_required
def admin_all_loans(request):
    """
    ADMIN ALL LOANS - Shows listing table with server-side rendered data
    Separate from admin_dashboard view
    """
    # Get search and filter parameters
    search_query = request.GET.get('q', '').strip()
    
    # Start with all loans
    loans = Loan.objects.all().order_by('-created_at')
    
    # Apply search filter
    if search_query:
        from django.db.models import Q
        loans = loans.filter(
            Q(full_name__icontains=search_query) |
            Q(mobile_number__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    
    # Rename 'phone' to 'mobile_number' for template compatibility
    loans_list = []
    for loan in loans:
        loan.phone = loan.mobile_number  # Add phone alias
        loan.applicant_name = loan.full_name  # Add applicant_name alias
        loans_list.append(loan)
    
    context = {
        'page_title': 'All Loans - Master Database',
        'loans': loans_list,
        'status_filter': request.GET.get('status', 'all'),
        'search_query': search_query,
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
        total_loans = LoanApplication.objects.count()
        stats = {
            'total': total_loans,
            'new_entry': LoanApplication.objects.filter(status='New Entry').count(),
            'processing': LoanApplication.objects.filter(status__in=['Waiting for Processing', 'Required Follow-up']).count(),
            'approved': LoanApplication.objects.filter(status='Approved').count(),
            'rejected': LoanApplication.objects.filter(status='Rejected').count(),
            'disbursed': LoanApplication.objects.filter(status='Disbursed').count(),
            'total_value': LoanApplication.objects.aggregate(Sum('applicant__loan_amount'))['applicant__loan_amount__sum'] or 0,
            'approved_value': LoanApplication.objects.filter(status='Approved').aggregate(Sum('applicant__loan_amount'))['applicant__loan_amount__sum'] or 0,
            'disbursed_value': LoanApplication.objects.filter(status='Disbursed').aggregate(Sum('applicant__loan_amount'))['applicant__loan_amount__sum'] or 0,
            'pending_value': LoanApplication.objects.exclude(status='Disbursed').aggregate(Sum('applicant__loan_amount'))['applicant__loan_amount__sum'] or 0,
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
    subadmins = User.objects.filter(role='subadmin')
    context = {
        'page_title': 'SubAdmin Management',
        'subadmins': subadmins,
        'subadmin_count': subadmins.count(),
    }
    return render(request, 'core/admin/subadmin_management.html', context)


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
