import re

from .models import Agent, AgentAssignment, User


def _clean_display_name(value):
    text = str(value or '').strip()
    if not text or text == '-':
        return ''
    return text


def _extract_subadmin_id(notes_text):
    match = re.search(r'\[subadmin:(\d+)\]', str(notes_text or ''), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _resolve_subadmin_name_for_employee(employee_user):
    if not employee_user:
        return ''

    profile = getattr(employee_user, 'employee_profile', None)
    subadmin_id = _extract_subadmin_id(getattr(profile, 'notes', '')) if profile else None
    if subadmin_id:
        subadmin = User.objects.filter(id=subadmin_id, role='subadmin').only('first_name', 'last_name', 'username').first()
        if subadmin:
            return _clean_display_name(subadmin.get_full_name() or subadmin.username)

    onboarding = getattr(employee_user, 'onboarding_profile', None)
    payload = onboarding.data if onboarding and isinstance(onboarding.data, dict) else {}
    meta = payload.get('_meta')
    if not isinstance(meta, dict):
        meta = {}
    role_text = str(meta.get('created_by_role') or '').strip().lower()
    if role_text in ['partner', 'subadmin']:
        creator_name = str(meta.get('created_by_name') or '').strip()
        if creator_name:
            return _clean_display_name(creator_name)

    created_by = getattr(employee_user, 'created_by', None)
    if created_by and getattr(created_by, 'role', '') == 'subadmin':
        return _clean_display_name(created_by.get_full_name() or created_by.username)
    return ''


def _resolve_agent_hierarchy(agent_obj):
    if not agent_obj:
        return {'employee_name': '', 'subadmin_name': ''}

    employee_user = None
    latest_assignment = (
        AgentAssignment.objects.filter(agent=agent_obj)
        .select_related('employee')
        .order_by('-assigned_at')
        .first()
    )
    if latest_assignment and latest_assignment.employee:
        employee_user = latest_assignment.employee
    elif agent_obj.created_by and getattr(agent_obj.created_by, 'role', '') == 'employee':
        employee_user = agent_obj.created_by

    employee_name = _clean_display_name(
        (employee_user.get_full_name() or employee_user.username)
        if employee_user else ''
    )

    subadmin_name = ''
    if employee_user:
        subadmin_name = _resolve_subadmin_name_for_employee(employee_user)
    elif agent_obj.created_by and getattr(agent_obj.created_by, 'role', '') == 'subadmin':
        subadmin_name = _clean_display_name(agent_obj.created_by.get_full_name() or agent_obj.created_by.username)

    return {
        'employee_name': employee_name,
        'subadmin_name': subadmin_name,
    }


def agent_profile_context(request):
    """
    Shared profile/sidebar context for all role panels.
    """
    context = {
        'agent_profile': None,
        'sidebar_brand_text': 'DREAM CAPITAL',
        'sidebar_profile_label': 'DREAM CAPITAL',
        'panel_hierarchy_line': '',
    }

    if not request.user.is_authenticated:
        return context

    role = getattr(request.user, 'role', '')

    if role == 'agent':
        try:
            agent = Agent.objects.get(user=request.user)
            context['agent_profile'] = agent
            hierarchy = _resolve_agent_hierarchy(agent)
            parts = []
            if hierarchy['subadmin_name']:
                parts.append(f"Partner: {hierarchy['subadmin_name']}")
            if hierarchy['employee_name']:
                parts.append(f"Employee: {hierarchy['employee_name']}")
            context['panel_hierarchy_line'] = " | ".join(parts)
            context['sidebar_profile_label'] = 'Channel Partner'
        except Agent.DoesNotExist:
            context['panel_hierarchy_line'] = ""
            context['sidebar_profile_label'] = 'Channel Partner'

    elif role == 'employee':
        subadmin_name = _resolve_subadmin_name_for_employee(request.user)
        context['panel_hierarchy_line'] = f"Partner: {subadmin_name}" if subadmin_name else ""
        context['sidebar_profile_label'] = 'Employee'
    elif role == 'subadmin':
        context['sidebar_profile_label'] = 'Partner'

    return context
