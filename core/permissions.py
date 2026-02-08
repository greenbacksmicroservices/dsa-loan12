"""
Role-Based Permission Classes for DRF API Endpoints
Ensures strict role separation with proper permission checking
"""

from rest_framework.permissions import BasePermission


class IsAdminUser(BasePermission):
    """
    Permission class to restrict access to admin users only.
    Admin users can: assign loans, manage employees, view all data
    """
    message = 'Admin access required.'
    
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == 'admin'
        )


class IsEmployeeUser(BasePermission):
    """
    Permission class to restrict access to employee users only.
    Employees can: approve, reject, disburse loans assigned to them
    """
    message = 'Employee access required.'
    
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == 'employee'
        )


class IsAgentUser(BasePermission):
    """
    Permission class to restrict access to agent users only.
    Agents can: submit applications, view own loans
    """
    message = 'Agent access required.'
    
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == 'agent'
        )


class IsLoanOwnerOrAdmin(BasePermission):
    """
    Permission to access object if user is the assigned employee or admin.
    """
    message = 'You do not have permission to access this loan.'
    
    def has_object_permission(self, request, view, obj):
        # Admin can access everything
        if request.user.role == 'admin':
            return True
        
        # Employee can access loans assigned to them
        if request.user.role == 'employee':
            return obj.assigned_employee_id == request.user.id
        
        # Agent can view their own submitted loans
        if request.user.role == 'agent':
            return obj.assigned_agent_id == request.user.id
        
        return False


class IsAdmin(BasePermission):
    """Alias for IsAdminUser"""
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'admin'


class IsEmployee(BasePermission):
    """Alias for IsEmployeeUser"""
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'employee'


class IsAgent(BasePermission):
    """Alias for IsAgentUser"""
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.role == 'agent'


class CanApproveLoans(IsEmployeeUser):
    """
    Employees can approve loans assigned to them.
    """
    message = 'Only assigned employees can approve loans.'
    
    def has_object_permission(self, request, view, obj):
        return (
            request.user.role == 'employee' and
            obj.assigned_employee_id == request.user.id and
            obj.status == 'Waiting for Processing'
        )


class CanRejectLoans(IsEmployeeUser):
    """
    Employees can reject loans assigned to them.
    """
    message = 'Only assigned employees can reject loans.'
    
    def has_object_permission(self, request, view, obj):
        return (
            request.user.role == 'employee' and
            obj.assigned_employee_id == request.user.id and
            obj.status == 'Waiting for Processing'
        )


class CanDisburseLoans(IsEmployeeUser):
    """
    Employees can disburse loans assigned to them.
    """
    message = 'Only assigned employees can disburse loans.'
    
    def has_object_permission(self, request, view, obj):
        return (
            request.user.role == 'employee' and
            obj.assigned_employee_id == request.user.id and
            obj.status == 'Waiting for Processing'
        )


class CanAssignLoans(IsAdminUser):
    """
    Only admins can assign loans to employees.
    """
    message = 'Only admins can assign loans.'
    
    def has_object_permission(self, request, view, obj):
        return (
            request.user.role == 'admin' and
            obj.status == 'New Entry'
        )
