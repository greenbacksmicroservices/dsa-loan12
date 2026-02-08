from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def admin_required(view_func):
    """
    Decorator to check if user is authenticated and has ADMIN role.
    Redirects to admin login if not authenticated or not admin.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access this page.')
            return redirect('admin_login')
        
        if request.user.role != 'admin':
            messages.error(request, 'Unauthorized access. Admin privileges required.')
            return redirect('admin_login')
        
        return view_func(request, *args, **kwargs)
    
    return _wrapped_view


def employee_required(view_func):
    """
    Decorator to check if user is authenticated and has EMPLOYEE role.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access this page.')
            return redirect('login')
        
        if request.user.role != 'employee':
            messages.error(request, 'Unauthorized access. Employee privileges required.')
            return redirect('login')
        
        return view_func(request, *args, **kwargs)
    
    return _wrapped_view


def admin_or_employee_required(view_func):
    """
    Decorator to check if user is authenticated and has ADMIN or EMPLOYEE role.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access this page.')
            return redirect('admin_login')
        
        if request.user.role not in ['admin', 'employee']:
            messages.error(request, 'Unauthorized access.')
            return redirect('admin_login')
        
        return view_func(request, *args, **kwargs)
    
    return _wrapped_view


def subadmin_required(view_func):
    """
    Decorator to check if user is authenticated and has SUBADMIN role.
    Redirects to admin login if not authenticated or not subadmin.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access this page.')
            return redirect('admin_login')
        
        if request.user.role != 'subadmin':
            messages.error(request, 'Unauthorized access. SubAdmin privileges required.')
            return redirect('admin_login')
        
        return view_func(request, *args, **kwargs)
    
    return _wrapped_view


def processing_agent_or_admin_required(view_func):
    """
    Decorator for WAITING FOR PROCESSING view.
    Allows: Admin, or assigned employee/agent (via applicant_id parameter).
    """
    @wraps(view_func)
    def _wrapped_view(request, applicant_id, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login to access this page.')
            return redirect('admin_login')
        
        # Admin can view any application in Waiting state
        if request.user.role == 'admin':
            return view_func(request, applicant_id, *args, **kwargs)
        
        # Employee/Agent can only view if assigned to them
        from .models import Applicant
        try:
            applicant = Applicant.objects.get(id=applicant_id)
            loan_app = applicant.loan_application
            
            if request.user.role == 'employee':
                if loan_app.assigned_employee != request.user:
                    messages.error(request, 'You do not have access to this application.')
                    return redirect('my_applications')
            elif request.user.role == 'agent':
                agent = request.user.agent_profile
                if loan_app.assigned_agent != agent:
                    messages.error(request, 'You do not have access to this application.')
                    return redirect('my_applications')
            else:
                messages.error(request, 'Access denied.')
                return redirect('admin_login')
            
            return view_func(request, applicant_id, *args, **kwargs)
        except Applicant.DoesNotExist:
            messages.error(request, 'Application not found.')
            return redirect('my_applications')

