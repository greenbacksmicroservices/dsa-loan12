import re

from .models import Agent, AgentAssignment, User


def _clean_display_name(value):
    text = str(value or '').strip()
    if not text or text == '-':
        return ''
    return text


def _contact_payload(user_obj=None, fallback_name='', fallback_role='BDM'):
    name = _clean_display_name(
        (user_obj.get_full_name() or user_obj.username) if user_obj else fallback_name
    )
    if not name:
        return {}
    return {
        'name': name,
        'phone': (getattr(user_obj, 'phone', '') or '-') if user_obj else '-',
        'email': (getattr(user_obj, 'email', '') or '-') if user_obj else '-',
        'role': fallback_role,
    }


def _default_admin_user(preferred_user=None):
    if preferred_user and getattr(preferred_user, 'role', '') == 'admin':
        return preferred_user
    return (
        User.objects.filter(role='admin', is_active=True)
        .only('first_name', 'last_name', 'username', 'email', 'phone')
        .order_by('id')
        .first()
        or User.objects.filter(role='admin')
        .only('first_name', 'last_name', 'username', 'email', 'phone')
        .order_by('id')
        .first()
    )


def _format_contact_line(label, info):
    if not info:
        return ''
    return (
        f"{label}: {info.get('name') or '-'} | "
        f"Phone: {info.get('phone') or '-'} | "
        f"Mail ID: {info.get('email') or '-'}"
    )


def _extract_subadmin_id(notes_text):
    match = re.search(r'\[subadmin:(\d+)\]', str(notes_text or ''), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _resolve_subadmin_user_for_employee(employee_user):
    if not employee_user:
        return None

    profile = getattr(employee_user, 'employee_profile', None)
    subadmin_id = _extract_subadmin_id(getattr(profile, 'notes', '')) if profile else None
    if subadmin_id:
        subadmin = User.objects.filter(id=subadmin_id, role='subadmin').only(
            'first_name',
            'last_name',
            'username',
            'email',
            'phone',
        ).first()
        if subadmin:
            return subadmin

    onboarding = getattr(employee_user, 'onboarding_profile', None)
    payload = onboarding.data if onboarding and isinstance(onboarding.data, dict) else {}
    meta = payload.get('_meta')
    if isinstance(meta, dict):
        role_text = str(meta.get('created_by_role') or '').strip().lower()
        creator_id = meta.get('created_by_id')
        if role_text in ['partner', 'subadmin'] and creator_id:
            try:
                subadmin = User.objects.filter(id=int(creator_id), role='subadmin').only(
                    'first_name',
                    'last_name',
                    'username',
                    'email',
                    'phone',
                ).first()
                if subadmin:
                    return subadmin
            except (TypeError, ValueError):
                pass

    created_by = getattr(employee_user, 'created_by', None)
    if created_by and getattr(created_by, 'role', '') == 'subadmin':
        return created_by

    return None


def _resolve_bdm_contact_for_employee(employee_user):
    subadmin = _resolve_subadmin_user_for_employee(employee_user)
    if subadmin:
        return _contact_payload(subadmin, fallback_role='BDM')

    onboarding = getattr(employee_user, 'onboarding_profile', None)
    payload = onboarding.data if onboarding and isinstance(onboarding.data, dict) else {}
    meta = payload.get('_meta')
    if isinstance(meta, dict):
        role_text = str(meta.get('created_by_role') or '').strip().lower()
        creator_name = str(meta.get('created_by_name') or '').strip()
        if role_text in ['partner', 'subadmin'] and creator_name:
            return _contact_payload(fallback_name=creator_name, fallback_role='BDM')

    return _contact_payload(_default_admin_user(), fallback_role='BDM')


def _resolve_subadmin_name_for_employee(employee_user):
    if not employee_user:
        return ''

    subadmin = _resolve_subadmin_user_for_employee(employee_user)
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
        return {'employee_name': '', 'subadmin_name': '', 'bdm': {}, 'employee': {}}

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

    subadmin_user = None
    if employee_user:
        subadmin_user = _resolve_subadmin_user_for_employee(employee_user)
        if not subadmin_user and agent_obj.created_by and getattr(agent_obj.created_by, 'role', '') == 'subadmin':
            subadmin_user = agent_obj.created_by
    elif agent_obj.created_by and getattr(agent_obj.created_by, 'role', '') == 'subadmin':
        subadmin_user = agent_obj.created_by

    bdm_info = _contact_payload(subadmin_user, fallback_role='BDM') if subadmin_user else _contact_payload(
        _default_admin_user(agent_obj.created_by),
        fallback_role='BDM',
    )
    employee_info = _contact_payload(employee_user, fallback_role='Employee') if employee_user else {}

    return {
        'employee_name': employee_name,
        'subadmin_name': bdm_info.get('name', ''),
        'bdm': bdm_info,
        'employee': employee_info,
    }


def agent_profile_context(request):
    """
    Shared profile/sidebar context for all role panels.
    """
    context = {
        'agent_profile': None,
        'sidebar_brand_text': 'DREAM CAPITAL',
        'sidebar_profile_label': 'DREAM CAPITAL',
        'sidebar_user_code': '',
        'sidebar_user_code_label': 'ID',
        'panel_hierarchy_line': '',
        'panel_hierarchy_items': [],
    }

    if not request.user.is_authenticated:
        return context

    role = getattr(request.user, 'role', '')

    if role == 'agent':
        try:
            agent = Agent.objects.get(user=request.user)
            context['agent_profile'] = agent
            hierarchy = _resolve_agent_hierarchy(agent)
            items = []
            if hierarchy.get('bdm'):
                items.append({'label': 'BDM', **hierarchy['bdm']})
            if hierarchy.get('employee'):
                items.append({'label': 'Employee', **hierarchy['employee']})
            context['panel_hierarchy_items'] = items
            context['panel_hierarchy_line'] = "  ".join(
                _format_contact_line(item['label'], item) for item in items if item
            )
            context['sidebar_profile_label'] = 'Channel Partner'
            context['sidebar_user_code'] = agent.agent_id or f"EDC-CP-{agent.id:04d}"
        except Agent.DoesNotExist:
            context['panel_hierarchy_line'] = ""
            context['sidebar_profile_label'] = 'Channel Partner'
            context['sidebar_user_code'] = getattr(request.user, 'employee_id', '') or ''

    elif role == 'employee':
        bdm_info = _resolve_bdm_contact_for_employee(request.user)
        if bdm_info:
            context['panel_hierarchy_items'] = [{'label': 'BDM', **bdm_info}]
            context['panel_hierarchy_line'] = _format_contact_line('BDM', bdm_info)
        context['sidebar_profile_label'] = 'Employee'
        context['sidebar_user_code'] = request.user.employee_id or f"EDC-EMP-{request.user.id:04d}"
    elif role == 'subadmin':
        context['sidebar_profile_label'] = 'Partner'
        context['sidebar_user_code'] = request.user.employee_id or f"EDC-P-{request.user.id:04d}"

    return context
