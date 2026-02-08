"""
Role-based access control decorators to prevent login redirect loops
and enforce strict permission checks
"""
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.urls import reverse


def role_required(allowed_roles):
    """
    Decorator to enforce role-based access control.
    Prevents redirect loops by checking role before redirecting to login.
    
    Usage:
        @role_required(['agent', 'admin'])
        def my_view(request):
            pass
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Check if user is authenticated
            if not request.user.is_authenticated:
                messages.error(request, 'Please log in to access this page.')
                return redirect('login')
            
            # Check if user has required role
            user_role = getattr(request.user, 'role', None)
            if user_role not in allowed_roles:
                messages.error(
                    request, 
                    f'Access denied. This page is only available for {", ".join(allowed_roles)}.'
                )
                # Redirect to appropriate dashboard based on role
                if user_role == 'admin':
                    return redirect('admin_dashboard')
                elif user_role == 'agent':
                    return redirect('agent_dashboard')
                else:
                    return redirect('dashboard')
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def agent_required(view_func):
    """
    Decorator to restrict access to agent users only.
    Prevents redirect loops specific to agent views.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Please log in as an agent to access this page.')
            return redirect('login')
        
        if request.user.role != 'agent':
            messages.error(request, 'This page is only available for agents.')
            if request.user.role == 'admin':
                return redirect('admin_dashboard')
            else:
                return redirect('dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    """
    Decorator to restrict access to admin users only.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Please log in as an admin to access this page.')
            return redirect('login')
        
        if request.user.role != 'admin':
            messages.error(request, 'This page is only available for administrators.')
            if request.user.role == 'agent':
                return redirect('agent_dashboard')
            else:
                return redirect('dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper
