"""
Agent-specific views for role-based loan management dashboard
Includes: New Entries, Add Loans, Sub-Agents, Reports, Complaints
"""
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Sum, Q
from django.utils import timezone
from django.urls import reverse
from datetime import datetime, timedelta
import csv
from openpyxl import Workbook

from .models import Loan, Agent, Complaint, User
from .role_decorators import agent_required


def get_agent_loan_queryset(user, agent):
    """
    Unified queryset for agent-owned data:
    - Loans created by this agent user
    - Loans currently assigned to this agent profile
    """
    return Loan.objects.filter(
        Q(created_by=user) | Q(assigned_agent=agent)
    ).distinct()


@agent_required
def agent_dashboard(request):
    """
    Main agent dashboard with real-time counts and status overview.
    Shows assigned loans, pending applications, and quick stats.
    """
    agent = Agent.objects.get(user=request.user)

    # Include both created and assigned loans for a reliable live dashboard view
    agent_loans = get_agent_loan_queryset(request.user, agent)

    # Real-time dashboard statistics
    dashboard_data = {
        'total_assigned': agent_loans.count(),
        'processing': agent_loans.filter(status__in=['new_entry', 'waiting', 'follow_up']).count(),
        'approved': agent_loans.filter(status='approved').count(),
        'rejected': agent_loans.filter(status='rejected').count(),
        'disbursed': agent_loans.filter(status='disbursed').count(),
        'total_amount': agent_loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
    }

    context = {
        'agent': agent,
        'dashboard': dashboard_data,
        'recent_loans': agent_loans.order_by('-created_at')[:10],
    }
    return render(request, 'core/agent/dashboard.html', context)


@agent_required
def agent_new_entries(request):
    """
    Display new entries assigned by admin to this agent.
    Shows clean table format without forms (admin-assigned loans only).
    Real-time status updates.
    """
    agent = Agent.objects.get(user=request.user)
    
    # Get new entries assigned to this agent by admin
    new_entries = Loan.objects.filter(
        assigned_agent=agent,
        status='new_entry'
    ).order_by('-created_at')
    
    context = {
        'new_entries': new_entries,
        'total_new': new_entries.count(),
        'agent': agent,
    }
    return render(request, 'core/agent/new_entries.html', context)


@agent_required
@require_http_methods(["GET", "POST"])
def agent_add_loan(request):
    """
    Allow agents to add new comprehensive loan applications.
    Includes all applicant details, address, loan, bank, and additional information.
    """
    if request.method == 'POST':
        try:
            # Validate mobile number
            mobile = request.POST.get('mobile_no', '').strip()
            if not mobile:
                mobile = '9999999999'
            if len(mobile) < 9:
                messages.error(request, 'Please provide a valid mobile number')
                return redirect('agent_add_loan')
            
            # Validate email only if provided
            email = request.POST.get('email_id', '').strip()
            if email and '@' not in email:
                messages.error(request, 'Please provide a valid email address')
                return redirect('agent_add_loan')
            
            # Handle save as draft
            save_as_draft = request.POST.get('save_as_draft') == 'true'
            
            # Create loan with comprehensive details
            agent = Agent.objects.get(user=request.user)

            loan_type_map = {
                'personal': 'personal',
                'personal loan': 'personal',
                'home': 'home',
                'home loan': 'home',
                'lap': 'lap',
                'loan against property': 'lap',
                'business': 'business',
                'business loan': 'business',
                'education': 'education',
                'education loan': 'education',
                'car': 'car',
                'car loan': 'car',
                'credit card': 'other',
                'other': 'other',
            }
            raw_loan_type = request.POST.get('service_required', 'personal').strip().lower()
            mapped_loan_type = loan_type_map.get(raw_loan_type, 'other')
            
            # Extract city and pin code with fallback
            city = request.POST.get('permanent_city', '').strip() or request.POST.get('city', '').strip() or 'Unknown'
            pin_code = request.POST.get('permanent_pin', '').strip() or request.POST.get('pin_code', '').strip() or '000000'
            
            # Validate PIN code
            if pin_code and len(pin_code) != 6:
                try:
                    pin_int = int(pin_code)
                    pin_code = str(pin_int).zfill(6)
                except ValueError:
                    pin_code = '000000'
            
            loan = Loan.objects.create(
                # Applicant Information - CORRECTED FIELD NAMES FROM FORM
                full_name=request.POST.get('name', '').strip() or 'Unknown Applicant',
                mobile_number=mobile,  # CRITICAL: MUST NOT BE NULL!
                email=email,
                
                # Address Information
                permanent_address=request.POST.get('permanent_address', '').strip(),
                current_address=request.POST.get('present_address', '').strip(),
                city=city,
                state=request.POST.get('state', '').strip() or 'Unknown',
                pin_code=pin_code,
                
                # Loan Details
                loan_type=mapped_loan_type,
                loan_amount=float(request.POST.get('loan_amount_required', 0) or 0),
                tenure_months=int(request.POST.get('loan_tenure', 0) or 0),
                interest_rate=float(request.POST.get('interest_rate', 0) or 0),
                loan_purpose=request.POST.get('remarks_suggestions', '').strip(),
                
                # Bank Details
                bank_name=request.POST.get('bank_name', '').strip(),
                
                # Assignment
                assigned_agent=agent,
                assigned_employee=None,  # Agent creates, admin assigns employee
                
                # Status (draft or new entry)
                status='draft' if save_as_draft else 'new_entry',
                applicant_type='agent',
                created_by=request.user,
                
                # Additional Information
                remarks=request.POST.get('remarks_suggestions', '').strip(),
            )
            
            # Store additional info in remarks if needed
            extra_info = f"\n\nADDITIONAL INFO:\n"
            extra_info += f"PAN: {request.POST.get('pan_number')}\n"
            extra_info += f"Aadhar: {request.POST.get('aadhar_number')}\n"
            extra_info += f"DOB: {request.POST.get('dob')}\n"
            extra_info += f"Gender: {request.POST.get('gender')}\n"
            extra_info += f"Occupation: {request.POST.get('occupation')}\n"
            extra_info += f"Employer: {request.POST.get('company_name')}\n"
            extra_info += f"Annual Income: {request.POST.get('annual_income')}\n"
            extra_info += f"Bank Account No: {request.POST.get('account_number')}\n"
            extra_info += f"CIBIL Score: {request.POST.get('cibil_score')}\n"
            extra_info += f"Service Required: {request.POST.get('service_required')}"
            
            if loan.remarks:
                loan.remarks += extra_info
            else:
                loan.remarks = extra_info
            
            # Handle photo upload
            if 'applicant_photo' in request.FILES:
                try:
                    loan.applicant_photo = request.FILES['applicant_photo']
                except Exception as photo_error:
                    print(f"Photo upload error: {str(photo_error)}")
            
            loan.save()
            
            if save_as_draft:
                messages.success(request, f'Application saved as draft! You can continue later.')
            else:
                messages.success(request, f'Loan application submitted successfully! Application ID: {loan.id}')
            
            return redirect('agent_my_applications')
        except Exception as e:
            messages.error(request, f'Error creating loan: {str(e)}')
    
    context = {
        'page_title': 'Add New Loan Application',
    }
    return render(request, 'core/agent/add_loan.html', context)


@agent_required
@agent_required
def agent_sub_agents(request):
    """
    Allow agents to create and manage their sub-agents.
    Only agents created by this agent are shown.
    """
    agent = Agent.objects.get(user=request.user)
    
    # Get sub-agents created by this agent
    sub_agents = Agent.objects.filter(created_by=request.user)
    
    context = {
        'sub_agents': sub_agents,
        'agent': agent,
        'total_sub_agents': sub_agents.count(),
    }
    return render(request, 'core/agent/sub_agents.html', context)


@agent_required
def agent_add_employee(request):
    """
    Form page to add a new sub-agent/team member
    """
    agent = Agent.objects.get(user=request.user)
    context = {
        'agent': agent,
        'page_title': 'Add New Team Member',
    }
    return render(request, 'core/agent/agent_add_employee.html', context)


@agent_required
@require_http_methods(["POST"])
def create_sub_agent(request):
    """
    Create a new sub-agent/team member under the current agent.
    Accepts FormData including photo upload
    """
    try:
        parent_agent = Agent.objects.get(user=request.user)
        
        # Get form data
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '').strip()
        gender = request.POST.get('gender', 'Other').strip()
        address = request.POST.get('address', '').strip()
        pin_code = request.POST.get('pin_code', '').strip()
        state = request.POST.get('state', '').strip()
        city = request.POST.get('city', '').strip()
        profile_photo = request.FILES.get('profile_photo', None)
        
        # Validation
        if not all([full_name, email, phone, password]):
            return JsonResponse({
                'success': False,
                'error': 'Full Name, Email, Phone, and Password are required'
            }, status=400)
        
        # Check email uniqueness
        if User.objects.filter(email=email).exists():
            return JsonResponse({
                'success': False,
                'error': 'Email already registered'
            }, status=400)
        
        # Check phone uniqueness  
        if User.objects.filter(phone=phone).exists():
            return JsonResponse({
                'success': False,
                'error': 'Phone number already registered'
            }, status=400)
        
        # Parse full name
        name_parts = full_name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        # Create user
        user = User.objects.create_user(
            username=email.split('@')[0],  # Username from email prefix
            email=email,
            password=password,
            role='agent',
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            gender=gender,
            address=address,
        )
        
        # Handle photo upload
        if profile_photo:
            # Validate file size (5MB max)
            if profile_photo.size > 5 * 1024 * 1024:
                user.delete()
                return JsonResponse({
                    'success': False,
                    'error': 'Profile photo must be less than 5MB'
                }, status=400)
            
            user.profile_photo = profile_photo
            user.save()
        
        # Create agent
        sub_agent = Agent.objects.create(
            user=user,
            name=f"{first_name} {last_name}",
            phone=phone,
            email=email,
            address=address if address else None,
            city=city if city else None,
            state=state if state else None,
            pin_code=pin_code if pin_code else None,
            gender=gender if gender else None,
            created_by=request.user,
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Team member {sub_agent.name} created successfully!',
            'agent_id': sub_agent.id,
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error: {str(e)}'
        }, status=500)


@agent_required
def agent_my_applications(request):
    """
    Show loans/applications created or managed by this agent.
    Shows all loans: approved, rejected, active, etc.
    """
    agent = Agent.objects.get(user=request.user)
    
    # Show both created and assigned applications
    all_loans = get_agent_loan_queryset(request.user, agent).order_by('-created_at')
    
    # Filter by status if provided
    status_filter = request.GET.get('status')
    status_alias_map = {
        'waiting_for_processing': 'waiting',
        'processing': 'waiting',
        'bank': 'follow_up',
    }
    normalized_status = status_alias_map.get(status_filter, status_filter) if status_filter else None
    if normalized_status:
        loans = all_loans.filter(status=normalized_status)
    else:
        loans = all_loans
    
    # Get counts by status
    total_count = all_loans.count()
    processing_count = all_loans.filter(status__in=['new_entry', 'waiting', 'follow_up']).count()
    approved_count = all_loans.filter(status='approved').count()
    rejected_count = all_loans.filter(status='rejected').count()
    disbursed_count = all_loans.filter(status='disbursed').count()
    active_count = all_loans.exclude(status__in=['rejected', 'disbursed']).count()
    focus_loan_id = request.GET.get('loan_id', '').strip()
    
    context = {
        'loans': loans,
        'total_count': total_count,
        'processing_count': processing_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'disbursed_count': disbursed_count,
        'active_count': active_count,
        'status_filter': normalized_status,
        'recent_submitted': all_loans[:10],
        'focus_loan_id': focus_loan_id,
        'statuses': [
            ('draft', 'Draft'),
            ('new_entry', 'New Entry'),
            ('waiting', 'Processing'),
            ('follow_up', 'Bank Stage'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('disbursed', 'Disbursed'),
        ]
    }
    return render(request, 'core/agent/my_applications.html', context)


@agent_required
def agent_reports(request):
    """
    Generate downloadable reports for agent's loans.
    Supports: 1 month, 6 months, 1 year.
    """
    agent = Agent.objects.get(user=request.user)
    
    period = request.GET.get('period', '1month')

    # Calculate date range
    today = timezone.now()
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    if from_date and to_date:
        try:
            start_date = timezone.make_aware(datetime.strptime(from_date, '%Y-%m-%d'))
            end_of_day = datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1)
            end_date = timezone.make_aware(end_of_day)
            period = 'custom'
        except ValueError:
            messages.error(request, 'Invalid custom date range. Showing last 1 month.')
            start_date = today - timedelta(days=30)
            end_date = today
            period = '1month'
    elif period == '1month':
        start_date = today - timedelta(days=30)
        end_date = today
    elif period == '6months':
        start_date = today - timedelta(days=180)
        end_date = today
    elif period == '1year':
        start_date = today - timedelta(days=365)
        end_date = today
    else:
        start_date = today - timedelta(days=30)
        end_date = today

    # Get loans in period
    loans = get_agent_loan_queryset(request.user, agent).filter(
        created_at__gte=start_date,
        created_at__lt=end_date
    ).order_by('-created_at')
    
    # Handle download
    if request.GET.get('download'):
        format_type = request.GET.get('format', 'csv')
        if format_type == 'csv':
            return export_loans_csv(loans, period)
        elif format_type == 'excel':
            return export_loans_excel(loans, period)
    
    context = {
        'loans': loans,
        'period': period,
        'from_date': from_date,
        'to_date': to_date,
        'total_loans': loans.count(),
        'total_amount': loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0,
        'approved_count': loans.filter(status='approved').count(),
        'approved_loans': loans.filter(status='approved').count(),
        'disbursed_loans': loans.filter(status='disbursed').count(),
        'rejected_loans': loans.filter(status='rejected').count(),
        'generated_reports': [],
    }
    return render(request, 'core/agent/reports.html', context)


@agent_required
def agent_complaints(request):
    """
    Display complaints filed by this agent.
    Shows real-time updates and allows viewing complaint details.
    """
    agent = Agent.objects.get(user=request.user)

    base_complaints = Complaint.objects.filter(
        filed_by_agent=agent
    ).select_related('loan', 'assigned_admin').order_by('-created_at')
    
    user_loans = get_agent_loan_queryset(request.user, agent).order_by('-created_at')
    
    # Filter by status
    status_filter = request.GET.get('status')
    complaints = base_complaints
    if status_filter:
        complaints = complaints.filter(status=status_filter)

    complaints = list(complaints)

    # Subject is stored in description first line for compatibility with model fields
    for complaint in complaints:
        raw_description = (complaint.description or '').strip()
        if '\n\n' in raw_description:
            subject_line, body_text = raw_description.split('\n\n', 1)
        else:
            subject_line = raw_description.split('\n', 1)[0]
            body_text = raw_description

        fallback_subject = f"{complaint.get_complaint_type_display()} Issue"
        complaint.subject_text = (subject_line or fallback_subject)[:100]
        complaint.body_text = body_text
    
    context = {
        'complaints': complaints,
        'user_loans': user_loans,
        'total': base_complaints.count(),
        'open': base_complaints.filter(status__in=['open', 'in_progress']).count(),
        'resolved': base_complaints.filter(status='resolved').count(),
        'status_filter': status_filter,
    }
    return render(request, 'core/agent/complaints.html', context)


@agent_required
@require_http_methods(["POST"])
def file_complaint(request):
    """
    File a new complaint from agent.
    Automatically appears in admin panel in real-time.
    """
    try:
        agent = Agent.objects.get(user=request.user)
        loan_id = (request.POST.get('loan_id') or '').strip()
        subject = (request.POST.get('subject') or '').strip()
        description = (request.POST.get('description') or '').strip()
        priority = (request.POST.get('priority') or 'medium').strip().lower()
        raw_type = (request.POST.get('complaint_type') or 'other').strip().lower()

        if not loan_id:
            messages.error(request, 'Please select a loan first.')
            return redirect('agent_complaints')
        if not description:
            messages.error(request, 'Please enter complaint description.')
            return redirect('agent_complaints')

        loan = get_agent_loan_queryset(request.user, agent).filter(id=loan_id).first()
        if not loan:
            messages.error(request, 'Selected loan was not found in your scope.')
            return redirect('agent_complaints')

        complaint_type_map = {
            'processing_delay': 'service',
            'communication': 'service',
            'service_quality': 'service',
            'approval_issue': 'service',
            'disbursement': 'payment',
            'documentation': 'documentation',
            'other': 'other',
            'service': 'service',
            'payment': 'payment',
        }
        complaint_type = complaint_type_map.get(raw_type, 'other')
        if priority == 'normal':
            priority = 'medium'
        if priority not in {'low', 'medium', 'high', 'urgent'}:
            priority = 'medium'

        if subject:
            full_description = f"{subject}\n\n{description}"
        else:
            full_description = description

        Complaint.objects.create(
            customer_name=loan.full_name or 'Unknown',
            loan=loan,
            filed_by_agent=agent,
            complaint_type=complaint_type,
            priority=priority,
            description=full_description,
            status='open',
            created_by=request.user,
        )
        
        messages.success(request, 'Complaint filed successfully!')
        return redirect('agent_complaints')
        
    except Exception as e:
        messages.error(request, f'Error filing complaint: {str(e)}')
        return redirect('agent_complaints')


def export_loans_csv(loans, period):
    """Export loans data as CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="loans_{period}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Applicant Name', 'Phone', 'Email', 'Loan Amount', 'Status', 'Created Date'])
    
    for loan in loans:
        writer.writerow([
            loan.full_name,
            loan.mobile_number,
            loan.email,
            loan.loan_amount,
            loan.get_status_display(),
            loan.created_at.strftime('%Y-%m-%d'),
        ])
    
    return response


def export_loans_excel(loans, period):
    """Export loans data as Excel"""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Loans'
    
    # Headers
    headers = ['Applicant Name', 'Phone', 'Email', 'Loan Amount', 'Status', 'Created Date']
    worksheet.append(headers)
    
    # Data
    for loan in loans:
        worksheet.append([
            loan.full_name,
            loan.mobile_number,
            loan.email,
            loan.loan_amount,
            loan.get_status_display(),
            loan.created_at.strftime('%Y-%m-%d'),
        ])
    
    # Auto-adjust columns
    for column in worksheet.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)
    
    # Write to response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="loans_{period}.xlsx"'
    workbook.save(response)
    
    return response


# API endpoints for real-time updates
@agent_required
def api_agent_dashboard_stats(request):
    """
    API endpoint for real-time dashboard statistics.
    Returns JSON data for live count updates.
    """
    agent = Agent.objects.get(user=request.user)
    agent_loans = get_agent_loan_queryset(request.user, agent)
    
    data = {
        'total_assigned': agent_loans.count(),
        'processing': agent_loans.filter(status__in=['new_entry', 'waiting', 'follow_up']).count(),
        'approved': agent_loans.filter(status='approved').count(),
        'rejected': agent_loans.filter(status='rejected').count(),
        'disbursed': agent_loans.filter(status='disbursed').count(),
        'total_amount': float(agent_loans.aggregate(Sum('loan_amount'))['loan_amount__sum'] or 0),
        'new_entry': agent_loans.filter(status='new_entry').count(),
        'waiting': agent_loans.filter(status='waiting').count(),
        'bank_stage': agent_loans.filter(status='follow_up').count(),
        'timestamp': timezone.now().isoformat(),
    }
    
    return JsonResponse(data)


@agent_required
def agent_notifications(request):
    """
    Real-time notifications API for agent dashboard.
    Shows updates about loans and complaints from admin panel.
    """
    agent = Agent.objects.get(user=request.user)
    assigned_loans = Loan.objects.filter(assigned_agent=agent)

    notifications = []

    approved_loans = assigned_loans.filter(status='approved').order_by('-updated_at')[:3]
    for loan in approved_loans:
        notifications.append({
            'id': f'approved_{loan.id}',
            'title': 'Loan Approved',
            'message': f'{loan.full_name} - Rs {loan.loan_amount}',
            'created_at': loan.updated_at.isoformat(),
            'type': 'approved'
        })

    complaints = Complaint.objects.filter(filed_by_agent=agent).order_by('-created_at')[:2]
    for complaint in complaints:
        notifications.append({
            'id': f'complaint_{complaint.id}',
            'title': 'Complaint Update',
            'message': complaint.subject,
            'created_at': complaint.created_at.isoformat(),
            'type': 'complaint'
        })

    new_entries = assigned_loans.filter(status='new_entry').order_by('-created_at')[:2]
    for entry in new_entries:
        notifications.append({
            'id': f'new_entry_{entry.id}',
            'title': 'New Entry Assigned',
            'message': f'{entry.full_name} - Rs {entry.loan_amount}',
            'created_at': entry.created_at.isoformat(),
            'type': 'new_entry'
        })

    notifications.sort(key=lambda x: x['created_at'], reverse=True)

    return JsonResponse({
        'notifications': notifications[:5]
    })


@agent_required
def agent_profile(request):
    """Agent profile page - display all agent details"""
    try:
        agent = Agent.objects.get(user=request.user)
    except Agent.DoesNotExist:
        messages.error(request, "Agent profile not found!")
        return redirect('agent_dashboard')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'change_password':
            old_password = request.POST.get('old_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            if not request.user.check_password(old_password):
                messages.error(request, "Old password is incorrect.")
            elif new_password != confirm_password:
                messages.error(request, "New passwords do not match.")
            elif len(new_password) < 6:
                messages.error(request, "Password must be at least 6 characters.")
            else:
                request.user.set_password(new_password)
                request.user.save()
                messages.success(request, "Password changed successfully. Please log in again.")
                return redirect('login')

        elif action == 'notification_settings':
            messages.success(request, "Notification settings updated successfully.")
    
    context = {
        'agent': agent,
        'page_title': 'My Profile',
    }
    return render(request, 'core/agent/profile.html', context)


@agent_required
def agent_edit_profile(request):
    """Edit agent profile - phone, email, address, profile_photo"""
    try:
        agent = Agent.objects.get(user=request.user)
    except Agent.DoesNotExist:
        messages.error(request, "Agent profile not found!")
        return redirect('agent_dashboard')
    
    if request.method == 'POST':
        # Update only allowed fields
        phone = request.POST.get('phone', agent.phone)
        email = request.POST.get('email', agent.email)
        address = request.POST.get('address', agent.address)
        
        # Handle profile photo upload
        if 'profile_photo' in request.FILES:
            agent.profile_photo = request.FILES['profile_photo']
        
        # Update fields
        agent.phone = phone
        agent.email = email
        agent.address = address
        agent.save()
        
        # Update user email as well
        user = request.user
        user.email = email
        user.save()
        
        messages.success(request, "Profile updated successfully!")
        return redirect('agent_profile')
    
    context = {
        'agent': agent,
        'page_title': 'Edit Profile',
    }
    return render(request, 'core/agent/edit_profile.html', context)


@agent_required
def agent_settings(request):
    """Legacy settings route now merged into profile page."""
    return redirect('agent_profile')


@agent_required
def api_agent_recent_entries(request):
    """
    API endpoint for agent's recent loan entries (created by this agent).
    Returns recent applications in JSON format for real-time dashboard display.
    Includes all loans created by agent regardless of status.
    """
    try:
        agent = Agent.objects.get(user=request.user)
        
        # Get limit from query params
        limit = int(request.GET.get('limit', 10))
        
        # Use same scope as dashboard cards so table and cards always match
        recent_loans_qs = get_agent_loan_queryset(request.user, agent).select_related(
            'assigned_employee', 'assigned_agent'
        ).order_by('-created_at')
        recent_loans = recent_loans_qs[:limit]
        
        # Format response data
        loans_data = []
        for loan in recent_loans:
            loan_data = {
                'id': loan.id,
                'applicant_name': loan.full_name or 'N/A',
                'mobile_number': loan.mobile_number or 'N/A',
                'loan_type': loan.loan_type or 'N/A',
                'loan_amount': float(loan.loan_amount or 0),
                'status': loan.status,
                'status_label': get_status_label(loan.status),
                'stage': get_stage_label(loan.status),
                'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'assigned_date': loan.updated_at.strftime('%Y-%m-%d') if loan.updated_at else 'N/A',
                'assigned_employee': loan.assigned_employee.get_full_name() if loan.assigned_employee else 'Pending',
                'assigned_agent': (
                    loan.assigned_agent.user.get_full_name()
                    if loan.assigned_agent and loan.assigned_agent.user
                    else (loan.assigned_agent.name if loan.assigned_agent else 'N/A')
                ),
                'status_badge': get_status_badge(loan.status),
                # Open directly in My Applications to avoid applicant-id route mismatch
                'detail_url': f"{reverse('agent_my_applications')}?loan_id={loan.id}",
            }
            loans_data.append(loan_data)
        
        return JsonResponse({
            'success': True,
            'total': recent_loans_qs.count(),
            'recent_entries': loans_data,
        })
    
    except Agent.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Agent not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def get_status_badge(status):
    """Helper function to get Bootstrap badge class for status"""
    badges = {
        'draft': 'secondary',
        'new_entry': 'primary',
        'waiting_for_processing': 'warning',
        'waiting': 'warning',
        'processing': 'info',
        'approved': 'success',
        'rejected': 'danger',
        'disbursed': 'success',
        'follow_up': 'warning',
    }
    return badges.get(status, 'secondary')


def get_status_label(status):
    labels = {
        'draft': 'Draft',
        'new_entry': 'New Entry',
        'waiting': 'Processing',
        'waiting_for_processing': 'Processing',
        'follow_up': 'Bank Stage',
        'approved': 'Approved',
        'rejected': 'Rejected',
        'disbursed': 'Disbursed',
    }
    return labels.get(status, status.replace('_', ' ').title())


def get_stage_label(status):
    stage_map = {
        'draft': 'Draft',
        'new_entry': 'New Entry',
        'waiting': 'Processing',
        'waiting_for_processing': 'Processing',
        'follow_up': 'Bank Stage',
        'approved': 'Completed',
        'rejected': 'Closed',
        'disbursed': 'Disbursed',
    }
    return stage_map.get(status, 'Processing')

