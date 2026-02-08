# ============ ADMIN ASSIGN ROLE - AGENT TO EMPLOYEE MAPPING ============

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.db.models import Q, Count, Prefetch
import json
import logging

from .models import User, Agent, EmployeeProfile, AgentAssignment
from .decorators import admin_required

logger = logging.getLogger(__name__)


@login_required(login_url='admin_login')
@admin_required
def admin_assign_role(request):
    """
    Main page to assign agents to employees
    """
    context = {
        'page_title': 'Assign Agents to Employees - Role Management',
    }
    return render(request, 'core/admin/assign_role.html', context)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_employees_for_agent_assignment(request):
    """
    Get list of all employees with their assigned agents count
    """
    try:
        employees = User.objects.filter(
            role='employee'
        ).select_related(
            'employee_profile'
        ).annotate(
            assigned_agents_count=Count('agent_assignments', distinct=True)
        ).order_by('first_name')
        
        employees_data = []
        for emp in employees:
            employees_data.append({
                'id': emp.id,
                'full_name': emp.get_full_name() or emp.username,
                'email': emp.email,
                'username': emp.username,
                'assigned_agents_count': emp.assigned_agents_count,
            })
        
        return JsonResponse({
            'success': True,
            'employees': employees_data
        })
    
    except Exception as e:
        logger.error(f"Error fetching employees: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_get_employee_agents(request, employee_id):
    """
    Get assigned and available agents for an employee
    """
    try:
        employee = get_object_or_404(User, id=employee_id, role='employee')
        
        # Get assigned agents
        assigned_agent_ids = list(
            AgentAssignment.objects.filter(
                employee=employee
            ).values_list('agent_id', flat=True)
        )
        
        assigned_agents = Agent.objects.filter(
            id__in=assigned_agent_ids
        ).values('id', 'name', 'email', 'created_by').order_by('name')
        
        # Get available agents (not assigned to this employee)
        available_agents = Agent.objects.exclude(
            id__in=assigned_agent_ids
        ).values('id', 'name', 'email', 'created_by').order_by('name')
        
        # Format response
        assigned_data = []
        for agent in assigned_agents:
            # Check if created by admin (admin's id is typically 1 or created_by is superuser)
            created_by_admin = agent['created_by'] == 1 or (agent['created_by'] and User.objects.filter(id=agent['created_by'], is_superuser=True).exists())
            assigned_data.append({
                'id': agent['id'],
                'name': agent['name'],
                'email': agent['email'],
                'created_by_admin': created_by_admin
            })
        
        available_data = []
        for agent in available_agents:
            created_by_admin = agent['created_by'] == 1 or (agent['created_by'] and User.objects.filter(id=agent['created_by'], is_superuser=True).exists())
            available_data.append({
                'id': agent['id'],
                'name': agent['name'],
                'email': agent['email'],
                'created_by_admin': created_by_admin
            })
        
        return JsonResponse({
            'success': True,
            'assigned_agents': assigned_data,
            'available_agents': available_data
        })
    
    except Exception as e:
        logger.error(f"Error fetching employee agents: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_assign_agent_to_employee(request):
    """
    Assign an agent to an employee
    """
    try:
        data = json.loads(request.body)
        employee_id = data.get('employee_id')
        agent_id = data.get('agent_id')
        
        if not employee_id or not agent_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing required fields'
            }, status=400)
        
        # Get employee and agent
        employee = get_object_or_404(User, id=employee_id, role='employee')
        agent = get_object_or_404(Agent, id=agent_id)
        
        # Check if already assigned
        if AgentAssignment.objects.filter(employee=employee, agent=agent).exists():
            return JsonResponse({
                'success': False,
                'error': 'Agent is already assigned to this employee'
            }, status=400)
        
        # Create assignment
        AgentAssignment.objects.create(
            employee=employee,
            agent=agent,
            assigned_by=request.user
        )
        
        logger.info(f"Agent {agent.name} assigned to employee {employee.username} by {request.user.username}")
        
        return JsonResponse({
            'success': True,
            'message': f'{agent.name} has been assigned to {employee.get_full_name()}'
        })
    
    except Exception as e:
        logger.error(f"Error assigning agent: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_unassign_agent_from_employee(request):
    """
    Unassign an agent from an employee
    """
    try:
        data = json.loads(request.body)
        employee_id = data.get('employee_id')
        agent_id = data.get('agent_id')
        
        if not employee_id or not agent_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing required fields'
            }, status=400)
        
        # Get employee and agent
        employee = get_object_or_404(User, id=employee_id, role='employee')
        agent = get_object_or_404(Agent, id=agent_id)
        
        # Get and delete assignment
        assignment = get_object_or_404(
            AgentAssignment,
            employee=employee,
            agent=agent
        )
        
        agent_name = agent.name
        employee_name = employee.get_full_name()
        
        assignment.delete()
        
        logger.info(f"Agent {agent_name} unassigned from employee {employee.username} by {request.user.username}")
        
        return JsonResponse({
            'success': True,
            'message': f'{agent_name} has been unassigned from {employee_name}'
        })
    
    except Exception as e:
        logger.error(f"Error unassigning agent: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
