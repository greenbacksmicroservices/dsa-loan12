"""Latest Admin Panel relationship resolution for Partner / Employee / Channel Partner views."""

from __future__ import annotations

from .loan_helpers import display_user_name, get_employee_partner, get_active_admins, get_leader_name
from .models import Agent, AgentAssignment


def _primary_admin_user():
    return get_active_admins().first()


def _unique_names(names):
    seen = set()
    ordered = []
    for raw in names or []:
        clean = str(raw or '').strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(clean)
    return ordered


def _agent_display_name(agent):
    if not agent:
        return ''
    return (
        str(agent.name or '').strip()
        or display_user_name(getattr(agent, 'user', None))
        or ''
    )


def get_employees_under_partner(partner_user):
    from .subadmin_views import _subadmin_managed_employees_qs

    if not partner_user:
        return []
    return list(
        _subadmin_managed_employees_qs(partner_user)
        .order_by('first_name', 'last_name', 'username')
    )


def get_channel_partners_under_partner(partner_user):
    from .subadmin_views import _subadmin_managed_agents_qs

    if not partner_user:
        return []
    return list(
        _subadmin_managed_agents_qs(partner_user)
        .select_related('user', 'under_employee', 'created_by')
        .order_by('name', 'id')
    )


def get_channel_partners_under_employee(employee_user):
    if not employee_user:
        return []

    agents = {}
    for agent in Agent.objects.filter(under_employee=employee_user).select_related('user'):
        agents[agent.id] = agent

    for link in AgentAssignment.objects.filter(employee=employee_user).select_related('agent', 'agent__user'):
        if link.agent_id and link.agent:
            agents[link.agent_id] = link.agent

    partner = get_employee_partner(employee_user)
    if partner:
        for agent in Agent.objects.filter(created_by=partner, under_employee=employee_user).select_related('user'):
            agents[agent.id] = agent

    return sorted(agents.values(), key=lambda item: (_agent_display_name(item).lower(), item.id))


def get_partner_for_agent(agent):
    created_by = getattr(agent, 'created_by', None)
    if created_by and str(getattr(created_by, 'role', '') or '').lower() in {'subadmin', 'partner'}:
        return created_by
    return None


def get_employee_for_agent(agent):
    if getattr(agent, 'under_employee', None):
        return agent.under_employee
    latest_assignment = (
        AgentAssignment.objects.filter(agent=agent)
        .select_related('employee')
        .order_by('-assigned_at', '-id')
        .first()
    )
    return latest_assignment.employee if latest_assignment else None


def build_partner_relationship_view(partner_user):
    employee_names = _unique_names(
        display_user_name(employee) for employee in get_employees_under_partner(partner_user)
    )
    channel_partner_names = _unique_names(
        _agent_display_name(agent) for agent in get_channel_partners_under_partner(partner_user)
    )

    employee_text = (
        f"Employee: {', '.join(employee_names)}"
        if employee_names
        else 'Your Employee: Not Assigned'
    )
    channel_partner_text = (
        f"Channel Partner: {', '.join(channel_partner_names)}"
        if channel_partner_names
        else 'Your Channel Partner: Not Assigned'
    )

    return {
        'employee_names': employee_names,
        'channel_partner_names': channel_partner_names,
        'lines': [
            {'key': 'employee', 'full_text': employee_text},
            {'key': 'channel_partner', 'full_text': channel_partner_text},
        ],
    }


def build_employee_relationship_view(employee_user):
    partner = get_employee_partner(employee_user)
    admin_user = _primary_admin_user()
    channel_partner_names = _unique_names(
        _agent_display_name(agent) for agent in get_channel_partners_under_employee(employee_user)
    )

    partner_text = (
        f"Partner: {display_user_name(partner)}"
        if partner
        else f"Leader: {display_user_name(admin_user) or 'Admin'}"
    )
    channel_partner_text = (
        f"Channel Partner: {', '.join(channel_partner_names)}"
        if channel_partner_names
        else 'Your Channel Partner: Not Assigned'
    )

    return {
        'partner': display_user_name(partner) if partner else '',
        'leader': get_leader_name(user=employee_user),
        'has_partner': bool(partner),
        'channel_partner_names': channel_partner_names,
        'lines': [
            {'key': 'partner', 'full_text': partner_text},
            {'key': 'channel_partner', 'full_text': channel_partner_text},
        ],
    }


def build_channel_partner_relationship_view(agent):
    partner = get_partner_for_agent(agent)
    admin_user = _primary_admin_user()
    employee = get_employee_for_agent(agent)
    employee_name = display_user_name(employee) if employee else ''

    partner_text = (
        f"Partner: {display_user_name(partner)}"
        if partner
        else f"Leader: {display_user_name(admin_user) or 'Admin'}"
    )
    employee_text = (
        f"Employee: {employee_name}"
        if employee_name
        else 'Your Employee: Not Assigned'
    )

    return {
        'partner': display_user_name(partner) if partner else '',
        'leader': get_leader_name(user=getattr(agent, 'user', None), agent=agent),
        'has_partner': bool(partner),
        'employee_name': employee_name,
        'lines': [
            {'key': 'partner', 'full_text': partner_text},
            {'key': 'employee', 'full_text': employee_text},
        ],
    }
