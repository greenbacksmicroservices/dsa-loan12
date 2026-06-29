"""Shared helpers for loan fields, lead receive, and account number sync."""

from __future__ import annotations

import re

from django.db.models import Q

from .models import Agent, Applicant, Loan, LoanApplication, User

PASSWORD_PROTECTED_DOC_KEYWORDS = (
    'salary slip',
    'bank statement',
    'aadhaar',
    'aadhar',
)

ACCOUNT_NUMBER_LABELS = (
    'account number',
    'loan account number',
    'current loan account number',
    'bank account number',
)


def display_user_name(user_obj):
    if not user_obj:
        return ''
    full_name = (user_obj.get_full_name() or '').strip()
    if full_name:
        return full_name
    return (user_obj.username or user_obj.email or '').strip()


_ROLE_NAME_PREFIXES = (
    'channel partner - ',
    'sub channel partner - ',
    'employee - ',
    'partner - ',
)


def display_agent_name_only(agent=None, raw_name=''):
    """Return person/company name without role prefix for table display."""
    name = str(raw_name or '').strip()
    if agent is not None:
        name = (
            str(getattr(agent, 'name', '') or '').strip()
            or display_user_name(getattr(agent, 'user', None))
            or name
        )
    if not name:
        return '-'
    lowered = name.lower()
    for prefix in _ROLE_NAME_PREFIXES:
        if lowered.startswith(prefix):
            cleaned = name[len(prefix):].strip()
            return cleaned or name
    return name


def _extract_subadmin_id(notes):
    match = re.search(r'\[subadmin:(\d+)\]', str(notes or ''), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _first_active_admin(exclude_id=None):
    qs = get_active_admins()
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return qs.first()


def normalize_user_role(role):
    return str(role or '').strip().lower().replace(' ', '_')


def is_admin_role(role):
    return normalize_user_role(role) in {'admin'}


def is_partner_role(role):
    return normalize_user_role(role) in {'subadmin', 'partner'}


def is_employee_role(role):
    return normalize_user_role(role) in {'employee'}


def is_channel_partner_role(role):
    normalized = normalize_user_role(role)
    return normalized in CHANNEL_PARTNER_ROLE_ALIASES or normalized in {
        'agent',
        'channel_partner',
        'channelpartner',
        'cp',
        'sub_channel_partner',
        'subchannelpartner',
    }


def get_active_admins():
    return User.objects.filter(is_active=True, role__iexact='admin').order_by(
        'first_name',
        'last_name',
        'username',
    )


def get_employee_partner(user):
    profile = getattr(user, 'employee_profile', None)
    partner_id = _extract_subadmin_id(getattr(profile, 'notes', '')) if profile else None
    if not partner_id:
        return None
    return User.objects.filter(
        id=partner_id,
        is_active=True,
    ).filter(
        Q(role__iexact='subadmin') | Q(role__iexact='partner'),
    ).first()


def get_channel_partner_partner(user):
    agent_profile = Agent.objects.filter(user=user).select_related('created_by').first()
    created_by = getattr(agent_profile, 'created_by', None)
    if created_by and is_partner_role(getattr(created_by, 'role', '')) and created_by.is_active:
        return created_by
    return None


def get_agent_type_label(agent):
    """Distinguish Channel Partner vs Sub Channel Partner from agent profile metadata."""
    if not agent:
        return '-'
    agent_code = str(getattr(agent, 'agent_id', '') or '').upper()
    if agent_code.startswith('EDC-SCP-'):
        return 'Sub Channel Partner'
    creator = getattr(agent, 'created_by', None)
    if getattr(creator, 'role', None) == 'agent':
        return 'Sub Channel Partner'
    return 'Channel Partner'


def is_sub_channel_partner_agent(agent):
    return get_agent_type_label(agent) == 'Sub Channel Partner'


def get_user_role_display(user=None, agent=None):
    if agent:
        return get_agent_type_label(agent)
    if not user:
        return '-'
    role = normalize_user_role(getattr(user, 'role', ''))
    mapping = {
        'admin': 'Admin',
        'subadmin': 'Partner',
        'partner': 'Partner',
        'employee': 'Employee',
        'agent': 'Channel Partner',
    }
    return mapping.get(role, str(getattr(user, 'role', '') or 'User').title())


def _resolve_agent_employee(agent):
    if not agent:
        return None
    if getattr(agent, 'under_employee', None):
        return agent.under_employee
    from .models import AgentAssignment

    assignment = (
        AgentAssignment.objects.filter(agent=agent)
        .select_related('employee')
        .order_by('-assigned_at', '-id')
        .first()
    )
    if assignment and assignment.employee and is_employee_role(getattr(assignment.employee, 'role', '')):
        return assignment.employee
    return None


def get_leader_bdm_partner_user(user=None, agent=None):
    """
    Return the Partner (subadmin) user in the upper hierarchy for CP/SCP/Employee.
    Walks SCP -> parent CP -> Employee -> Partner when needed.
    """
    if agent is None and user is not None:
        agent = Agent.objects.filter(user=user).select_related('created_by', 'under_employee').first()

    if user and is_partner_role(getattr(user, 'role', '')) and user.is_active:
        return user

    if user and is_employee_role(getattr(user, 'role', '')):
        return get_employee_partner(user)

    agents_to_check = []
    if agent:
        agents_to_check.append(agent)
        if is_sub_channel_partner_agent(agent) and getattr(agent, 'created_by', None):
            parent_agent = (
                Agent.objects.filter(user=agent.created_by)
                .select_related('created_by', 'under_employee')
                .first()
            )
            if parent_agent and parent_agent not in agents_to_check:
                agents_to_check.append(parent_agent)

    for ag in agents_to_check:
        ag_user = getattr(ag, 'user', None)
        if ag_user:
            partner = get_channel_partner_partner(ag_user)
            if partner:
                return partner

        creator = getattr(ag, 'created_by', None)
        if creator and is_partner_role(getattr(creator, 'role', '')) and creator.is_active:
            return creator

        employee = _resolve_agent_employee(ag)
        if employee:
            partner = get_employee_partner(employee)
            if partner:
                return partner

    return None


def get_leader_bdm_name_for_user(user=None, agent=None):
    """Leader/BDM label: Partner name from upper hierarchy, otherwise Admin."""
    partner = get_leader_bdm_partner_user(user=user, agent=agent)
    if partner:
        return display_user_name(partner)
    return display_user_name(_first_active_admin()) or 'Admin'


def get_leader_name(user=None, agent=None):
    """Backward-compatible alias for leader/BDM display."""
    return get_leader_bdm_name_for_user(user=user, agent=agent)


def get_assigned_employee_for_submitter(user):
    """Auto-assign loan applications submitted by CP/SCP to their hierarchy employee."""
    if not user:
        return None
    role = normalize_user_role(getattr(user, 'role', ''))
    if is_employee_role(role):
        return user
    if not is_channel_partner_role(role):
        return None

    agent = Agent.objects.filter(user=user).select_related('under_employee', 'created_by').first()
    if not agent:
        return None

    employee = _resolve_agent_employee(agent)
    if employee:
        return employee

    if is_sub_channel_partner_agent(agent):
        parent_user = agent.created_by
        if parent_user:
            parent_agent = Agent.objects.filter(user=parent_user).select_related('under_employee').first()
            if parent_agent:
                return _resolve_agent_employee(parent_agent)
    return None


def get_sub_channel_partner_users_for_parent_agent(parent_agent):
    """Users for SCP profiles created directly under a parent channel partner."""
    if not parent_agent or not getattr(parent_agent, 'user', None):
        return User.objects.none()
    scp_user_ids = []
    for child_agent in Agent.objects.filter(created_by=parent_agent.user).select_related('user'):
        if child_agent.user_id and is_sub_channel_partner_agent(child_agent):
            scp_user_ids.append(child_agent.user_id)
    if not scp_user_ids:
        return User.objects.none()
    return User.objects.filter(id__in=scp_user_ids)


def get_agent_loan_visibility_filter(user, agent):
    """Q filter for loans visible to a channel partner (own + child SCP submissions)."""
    visibility = Q(created_by=user) | Q(assigned_agent=agent)
    scp_users = get_sub_channel_partner_users_for_parent_agent(agent)
    if scp_users.exists():
        visibility |= Q(created_by__in=scp_users)
    return visibility


def get_loan_submitted_by_display(loan):
    """Human-readable submitter label for parent CP visibility."""
    creator = getattr(loan, 'created_by', None)
    if not creator:
        return '-'
    if getattr(creator, 'role', '') != 'agent':
        return get_user_role_display(user=creator)

    creator_agent = Agent.objects.filter(user=creator).only('agent_id', 'name', 'created_by_id').first()
    if creator_agent and is_sub_channel_partner_agent(creator_agent):
        name = (
            str(getattr(creator_agent, 'name', '') or '').strip()
            or display_user_name(creator)
        )
        return f'Sub Channel Partner - {name}'
    return get_user_role_display(user=creator, agent=creator_agent)


def get_lead_receive_options(user):
    """
    Return lead-receiver dropdown options for the current user.

    Rules:
    - User under a Partner sees only that Partner.
    - User without a Partner above sees only one Admin.
    - Admin sees only themselves (or the primary active admin).
    Each option: {'id': int, 'name': str, 'role': str}
    """
    role = normalize_user_role(getattr(user, 'role', ''))

    def single_option(candidate):
        if not candidate or not candidate.is_active:
            return []
        return [{
            'id': candidate.id,
            'name': display_user_name(candidate),
            'role': normalize_user_role(candidate.role),
        }]

    if is_employee_role(role):
        partner = get_employee_partner(user)
        if partner:
            return single_option(partner)
        admin_user = _first_active_admin()
        return single_option(admin_user)

    if is_channel_partner_role(role):
        partner = get_channel_partner_partner(user)
        if partner:
            return single_option(partner)
        admin_user = _first_active_admin()
        return single_option(admin_user)

    if is_partner_role(role):
        admin_user = _first_active_admin()
        return single_option(admin_user)

    if is_admin_role(role):
        if user.is_active:
            return single_option(user)
        admin_user = _first_active_admin()
        return single_option(admin_user)

    admin_user = _first_active_admin()
    return single_option(admin_user)


def resolve_lead_receive_name(user_id, fallback_name=''):
    if not user_id:
        return (fallback_name or '').strip()
    try:
        user_obj = User.objects.filter(id=int(user_id), is_active=True).first()
    except (TypeError, ValueError):
        user_obj = None
    if user_obj:
        return display_user_name(user_obj)
    return (fallback_name or '').strip()


def normalize_account_number(value):
    return str(value or '').strip()


def resolve_account_number(*, applicant=None, legacy_loan=None, parsed_details=None):
    """Return the latest account number from database-first sources."""
    parsed_details = parsed_details or {}
    for key in ('account_number', 'loan_account_number', 'bank_account_number', 'current_loan_account_number'):
        parsed_value = normalize_account_number(parsed_details.get(key))
        if parsed_value:
            return parsed_value
    if applicant is not None:
        value = normalize_account_number(getattr(applicant, 'account_number', ''))
        if value:
            return value
    if legacy_loan is not None:
        return normalize_account_number(getattr(legacy_loan, 'bank_account_number', ''))
    return ''


def sync_account_number(*, applicant=None, legacy_loan=None, account_number=None):
    """Persist one account number across linked applicant/legacy loan rows."""
    value = normalize_account_number(account_number)
    if not value:
        return value

    if applicant is not None and getattr(applicant, 'account_number', None) != value:
        applicant.account_number = value
        applicant.save(update_fields=['account_number', 'updated_at'])

    if legacy_loan is not None and getattr(legacy_loan, 'bank_account_number', None) != value:
        legacy_loan.bank_account_number = value
        legacy_loan.save(update_fields=['bank_account_number', 'updated_at'])

    return value


def account_number_api_payload(applicant=None, legacy_loan=None, parsed_details=None):
    """Consistent API keys for account number (single source of truth)."""
    account_number = resolve_account_number(
        applicant=applicant,
        legacy_loan=legacy_loan,
        parsed_details=parsed_details,
    )
    return {
        'account_number': account_number,
        # Backward compatibility for existing JS consumers.
        'loan_account_number': account_number,
        'bank_account_number': account_number,
    }


def is_password_protected_document_name(name):
    normalized = str(name or '').strip().lower()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in PASSWORD_PROTECTED_DOC_KEYWORDS)


CHANNEL_PARTNER_ROLE_ALIASES = frozenset({
    'agent',
    'channel_partner',
    'channelpartner',
    'cp',
    'sub_channel_partner',
    'subchannelpartner',
    'sub_channelpartner',
    'sub channel partner',
    'channel partner',
})

BANKER_HIDDEN_DETAIL_LABELS = frozenset({
    'banker name',
    'banker phone',
    'banker email',
})

BANKER_HIDDEN_PAYLOAD_KEYS = (
    'banker_name',
    'banker_phone',
    'banker_email',
    'banker_description',
)

LEAD_RECEIVE_HIDDEN_DETAIL_LABELS = frozenset({
    'channel partner name',
    'employee name',
    'leader name',
    'lead source',
    'lead description',
    'lead receive channel partner name',
    'lead receive employee name',
    'lead receive leader name',
    'lead receive source',
    'lead receive description',
    'lead receive',
})

LEAD_RECEIVE_HIDDEN_PAYLOAD_KEYS = (
    'lead_receive_channel_partner_name',
    'lead_receive_employee_name',
    'lead_receive_leader_name',
    'lead_receive_source',
    'lead_receive_description',
)

REJECTABLE_APPLICATION_STATUSES = frozenset({
    'New Entry',
    'Waiting for Processing',
    'Required Follow-up',
    'Approved',
})

REJECTABLE_LEGACY_STATUSES = frozenset({
    'new_entry',
    'waiting',
    'updated_document',
    'follow_up',
    'approved',
})


def normalize_role_value(role):
    return re.sub(r'[\s\-]+', '_', str(role or '').strip().lower())


def is_channel_partner(user_or_role):
    """True for channel partner / sub channel partner users regardless of role string variant."""
    if user_or_role is None:
        return False
    if hasattr(user_or_role, 'role'):
        role = getattr(user_or_role, 'role', '')
    else:
        role = user_or_role
    normalized = normalize_role_value(role)
    if normalized in CHANNEL_PARTNER_ROLE_ALIASES:
        return True
    compact = normalized.replace('_', '')
    return compact in {'agent', 'channelpartner', 'subchannelpartner', 'cp'}


def _normalize_detail_label(label):
    return re.sub(r'[^a-z0-9]+', ' ', str(label or '').strip().lower()).strip()


def _is_hidden_detail_label_for_channel_partner(label_key):
    if not label_key:
        return False
    if label_key in BANKER_HIDDEN_DETAIL_LABELS or label_key in LEAD_RECEIVE_HIDDEN_DETAIL_LABELS:
        return True
    if any(token in label_key for token in ('banker name', 'banker phone', 'banker email')):
        return True
    if 'lead receive' in label_key or label_key.startswith('lead '):
        return True
    return False


def resolve_latest_saved_bank_name(payload):
    """Return the saved bank name for channel partner latest-saved display."""
    if not isinstance(payload, dict):
        return ''
    direct = str(
        payload.get('bank_name')
        or payload.get('processing_bank_name')
        or ''
    ).strip()
    if direct:
        return direct
    for row in payload.get('full_application_details') or []:
        if not isinstance(row, dict):
            continue
        if _normalize_detail_label(row.get('label')) != 'bank name':
            continue
        value = str(row.get('value') or '').strip()
        if value and value != '-':
            return value
    return ''


def attach_channel_partner_latest_saved_fields(payload, user_or_role, bank_name=''):
    """Expose bank name for CP/SCP latest-saved UI while keeping other banker fields hidden."""
    if not is_channel_partner(user_or_role) or not isinstance(payload, dict):
        return payload
    cleaned = dict(payload)
    name = str(bank_name or '').strip()
    cleaned['latest_saved_bank_name'] = name
    cleaned['bank_name'] = name
    return cleaned


def filter_application_details_for_role(rows, user_or_role):
    """Remove banker/internal bank and lead-receive rows for channel partners."""
    if not is_channel_partner(user_or_role):
        return rows
    filtered = []
    for row in rows or []:
        label_key = _normalize_detail_label(row.get('label') if isinstance(row, dict) else '')
        if _is_hidden_detail_label_for_channel_partner(label_key):
            continue
        filtered.append(row)
    return filtered


def strip_banker_fields_for_role(payload, user_or_role):
    """Remove internal banking contact fields for channel partner users."""
    if not is_channel_partner(user_or_role):
        return payload
    if not isinstance(payload, dict):
        return payload
    cleaned = dict(payload)
    for key in BANKER_HIDDEN_PAYLOAD_KEYS + LEAD_RECEIVE_HIDDEN_PAYLOAD_KEYS:
        cleaned.pop(key, None)
    if 'full_application_details' in cleaned:
        cleaned['full_application_details'] = filter_application_details_for_role(
            cleaned.get('full_application_details'),
            user_or_role,
        )
    return cleaned


LOAN_ID_EMPTY_LABEL = 'Not Assigned Yet'

_AUTO_LOAN_ID_PATTERN = re.compile(r'^(APP|LOAN)-\d+$', re.IGNORECASE)


def normalize_loan_id(value):
    text = str(value or '').strip()
    if not text:
        return ''
    return re.sub(r'\s+', '', text).upper()


def is_auto_generated_loan_id(value):
    normalized = normalize_loan_id(value)
    return bool(normalized and _AUTO_LOAN_ID_PATTERN.match(normalized))


def resolve_stored_loan_id(*, legacy_loan=None, loan_application=None):
    """Return the official loan_id from database records only."""
    for obj in (legacy_loan, loan_application):
        if obj is None:
            continue
        stored = normalize_loan_id(getattr(obj, 'loan_id', None))
        if stored and not is_auto_generated_loan_id(stored):
            return stored
    if legacy_loan is not None:
        legacy_user_id = normalize_loan_id(getattr(legacy_loan, 'user_id', None))
        if legacy_user_id and not is_auto_generated_loan_id(legacy_user_id):
            return legacy_user_id
    return ''


def display_loan_id(*, legacy_loan=None, loan_application=None, empty_label=LOAN_ID_EMPTY_LABEL):
    value = resolve_stored_loan_id(legacy_loan=legacy_loan, loan_application=loan_application)
    return value or empty_label


def loan_id_taken(loan_id_value, *, exclude_legacy_id=None, exclude_application_id=None):
    normalized = normalize_loan_id(loan_id_value)
    if not normalized:
        return False
    loan_qs = Loan.objects.filter(
        Q(loan_id__iexact=normalized) | Q(user_id__iexact=normalized)
    )
    if exclude_legacy_id:
        loan_qs = loan_qs.exclude(id=exclude_legacy_id)
    if loan_qs.exists():
        return True
    app_qs = LoanApplication.objects.filter(loan_id__iexact=normalized)
    if exclude_application_id:
        app_qs = app_qs.exclude(id=exclude_application_id)
    return app_qs.exists()


def apply_official_loan_id(
    loan_id_value,
    *,
    legacy_loan=None,
    loan_application=None,
    required=False,
):
    """Persist one official Loan ID across linked legacy/application rows."""
    normalized = normalize_loan_id(loan_id_value)
    if not normalized:
        if required:
            raise ValueError('Loan ID is required.')
        return ''

    if loan_id_taken(
        normalized,
        exclude_legacy_id=getattr(legacy_loan, 'id', None),
        exclude_application_id=getattr(loan_application, 'id', None),
    ):
        raise ValueError('Loan ID already exists.')

    if legacy_loan is not None:
        legacy_fields = []
        if normalize_loan_id(getattr(legacy_loan, 'loan_id', None)) != normalized:
            legacy_loan.loan_id = normalized
            legacy_fields.append('loan_id')
        if normalize_loan_id(getattr(legacy_loan, 'user_id', None)) != normalized:
            legacy_loan.user_id = normalized
            legacy_fields.append('user_id')
        if legacy_fields:
            legacy_loan.save(update_fields=legacy_fields + ['updated_at'])

    if loan_application is not None:
        if normalize_loan_id(getattr(loan_application, 'loan_id', None)) != normalized:
            loan_application.loan_id = normalized
            loan_application.save(update_fields=['loan_id', 'updated_at'])

    return normalized


def apply_official_loan_id_from_payload(
    payload,
    *,
    legacy_loan=None,
    loan_application=None,
    required=False,
):
    """Update loan_id when payload includes loan_id or legacy manual_loan_id key."""
    if not isinstance(payload, dict):
        return resolve_stored_loan_id(legacy_loan=legacy_loan, loan_application=loan_application)
    if 'loan_id' in payload:
        raw = payload.get('loan_id')
    elif 'manual_loan_id' in payload:
        raw = payload.get('manual_loan_id')
    else:
        return resolve_stored_loan_id(legacy_loan=legacy_loan, loan_application=loan_application)
    return apply_official_loan_id(
        raw,
        legacy_loan=legacy_loan,
        loan_application=loan_application,
        required=required,
    )


def loan_id_api_fields(*, legacy_loan=None, loan_application=None):
    """Consistent API keys for Loan ID display across panels."""
    stored = resolve_stored_loan_id(legacy_loan=legacy_loan, loan_application=loan_application)
    return {
        'loan_id': stored,
        'loan_id_display': stored or LOAN_ID_EMPTY_LABEL,
    }


def _truthy_flag(value):
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def read_document_password_for_save(request, index=0):
    """
    Read document password from a multipart or JSON request.

    Returns:
        str | None: password to store (empty string clears password)
        sentinel omitted when password fields were not submitted (preserve on update)
    """
    post = getattr(request, 'POST', None) or {}
    data = getattr(request, 'data', None)
    data = data if isinstance(data, dict) else {}

    password_lists = (
        post.getlist('document_password[]')
        or post.getlist('document_password')
        or []
    )
    enabled_lists = (
        post.getlist('document_password_enabled[]')
        or post.getlist('document_password_enabled')
        or post.getlist('document_has_password[]')
        or post.getlist('document_has_password')
        or []
    )

    password_submitted = bool(
        password_lists
        or 'document_password' in post
        or 'document_password' in data
    )
    enabled_submitted = bool(
        enabled_lists
        or 'document_password_enabled' in post
        or 'document_password_enabled' in data
        or 'document_has_password' in post
        or 'document_has_password' in data
    )

    if not password_submitted and not enabled_submitted:
        return None

    password = ''
    if password_lists and index < len(password_lists):
        password = str(password_lists[index] or '').strip()
    else:
        password = str(
            data.get('document_password')
            or post.get('document_password')
            or ''
        ).strip()

    enabled = False
    if enabled_lists and index < len(enabled_lists):
        enabled = _truthy_flag(enabled_lists[index])
    else:
        enabled = _truthy_flag(
            data.get('document_password_enabled', post.get('document_password_enabled'))
            or data.get('document_has_password', post.get('document_has_password'))
        )

    if enabled or password:
        return password or None
    return None


def _sanitize_delete_error_message(error_text):
    """Return a user-safe delete error without raw ORM exceptions."""
    message = str(error_text or '').strip() or 'Failed to delete loan.'
    lowered = message.lower()
    if 'no loan matches' in lowered or 'doesnotexist' in lowered or 'does not exist' in lowered:
        return 'Loan already deleted or not found.'
    return message


def delete_loan_by_primary_key(loan_id, entity_type=None, allow_disbursed=False):
    """
    Delete a workflow LoanApplication and/or legacy Loan by database primary key.

    Returns dict: success, message, error, status_code
    """
    from django.db import transaction
    from django.db.models import ProtectedError

    from .loan_sync import find_related_loan, find_related_loan_application

    try:
        loan_pk = int(loan_id)
    except (TypeError, ValueError):
        return {
            'success': False,
            'error': 'Invalid loan identifier.',
            'status_code': 400,
        }

    normalized = str(entity_type or '').strip().lower()
    prefer_application = normalized in {'application', 'app'}
    prefer_legacy = normalized in {'legacy', 'loan'}

    loan_app = LoanApplication.objects.select_related('applicant').filter(id=loan_pk).first()
    legacy_loan = Loan.objects.filter(id=loan_pk).first()

    if not loan_app and not legacy_loan:
        return {
            'success': False,
            'error': 'Loan already deleted or not found.',
            'status_code': 404,
        }

    def _is_disbursed_status(raw_status):
        return str(raw_status or '').strip().lower() == 'disbursed'

    def _delete_application(app_obj):
        if not allow_disbursed and _is_disbursed_status(app_obj.status):
            return {
                'success': False,
                'error': 'Cannot delete a disbursed loan.',
                'status_code': 400,
            }
        applicant = app_obj.applicant
        linked_legacy = app_obj.legacy_loan if getattr(app_obj, 'legacy_loan_id', None) else find_related_loan(app_obj, strict=True)
        with transaction.atomic():
            app_obj.delete()
            if linked_legacy:
                Loan.objects.filter(pk=linked_legacy.pk).delete()
            if applicant:
                Applicant.objects.filter(pk=applicant.pk).delete()
        return {
            'success': True,
            'message': 'Loan deleted successfully.',
            'status_code': 200,
        }

    def _delete_legacy(legacy_obj):
        if not allow_disbursed and _is_disbursed_status(legacy_obj.status):
            return {
                'success': False,
                'error': 'Cannot delete a disbursed loan.',
                'status_code': 400,
            }
        related_app = find_related_loan_application(legacy_obj)
        applicant = related_app.applicant if related_app else None
        with transaction.atomic():
            legacy_obj.delete()
            if related_app:
                LoanApplication.objects.filter(pk=related_app.pk).delete()
            if applicant:
                Applicant.objects.filter(pk=applicant.pk).delete()
        return {
            'success': True,
            'message': 'Loan deleted successfully.',
            'status_code': 200,
        }

    try:
        if prefer_application and loan_app:
            return _delete_application(loan_app)
        if prefer_legacy and legacy_loan:
            return _delete_legacy(legacy_loan)
        if loan_app:
            return _delete_application(loan_app)
        if legacy_loan:
            return _delete_legacy(legacy_loan)
    except ProtectedError:
        return {
            'success': False,
            'error': 'This record is linked to other data and cannot be deleted.',
            'status_code': 400,
        }
    except Exception as exc:
        return {
            'success': False,
            'error': _sanitize_delete_error_message(exc),
            'status_code': 400,
        }

    return {
        'success': False,
        'error': 'Loan already deleted or not found.',
        'status_code': 404,
    }


def mirror_legacy_documents_to_application(legacy_loan, loan_application=None):
    """Copy legacy LoanDocument rows onto the linked LoanApplication."""
    from .models import ApplicantDocument, LoanDocument
    from .loan_sync import find_related_loan_application

    if not legacy_loan:
        return
    loan_app = loan_application or find_related_loan_application(legacy_loan)
    if not loan_app:
        return

    for loan_doc in LoanDocument.objects.filter(loan=legacy_loan):
        ApplicantDocument.objects.update_or_create(
            loan_application=loan_app,
            document_type=str(loan_doc.document_type or 'other')[:50],
            defaults={
                'file': loan_doc.file,
                'is_required': loan_doc.is_required,
                'document_password': loan_doc.document_password,
            },
        )


def can_create_sub_channel_partner(user):
    """Only Channel Partners (not SCP) may create Sub Channel Partners in the agent panel."""
    if not user or not getattr(user, 'is_authenticated', False) or not user.is_authenticated:
        return False
    role = normalize_user_role(getattr(user, 'role', ''))
    if role == 'admin':
        return True
    if not is_channel_partner_role(role):
        return False
    agent = Agent.objects.filter(user=user).only('id', 'agent_id', 'created_by_id').first()
    if not agent:
        return False
    return not is_sub_channel_partner_agent(agent)


def can_admin_edit_loan(user, loan=None):
    return bool(user and getattr(user, 'role', '') == 'admin')


def get_submitted_processed_display(loan=None, loan_application=None):
    """
    Structured Submitted / Processed hierarchy lines for loan tables.
    Returns dict with lines: [{label, value}, ...]
    """
    from .loan_sync import find_related_loan, find_related_loan_application

    legacy = loan
    app = loan_application
    if legacy and not app:
        app = find_related_loan_application(legacy)
    if app and not legacy:
        if getattr(app, 'legacy_loan_id', None):
            legacy = app.legacy_loan
        else:
            legacy = find_related_loan(app)

    creator = None
    if legacy and getattr(legacy, 'created_by_id', None):
        creator = legacy.created_by
    elif app and getattr(app, 'assigned_by_id', None):
        creator = app.assigned_by

    def _clean(value):
        text = str(value or '').strip()
        if not text or text in {'-', 'N/A', 'Not available', 'Not Added'}:
            return ''
        return text

    def _partner_for_employee(employee_user):
        if not employee_user:
            return ''
        return _clean(display_user_name(get_employee_partner(employee_user)))

    scp_name = ''
    cp_name = ''
    employee_name = ''
    partner_name = ''

    creator_agent = None
    if creator and normalize_user_role(getattr(creator, 'role', '')) in {'agent', 'channel_partner', 'cp'}:
        creator_agent = Agent.objects.filter(user=creator).select_related(
            'created_by', 'under_employee'
        ).first()

    if creator_agent and is_sub_channel_partner_agent(creator_agent):
        scp_name = _clean(creator_agent.name) or _clean(display_user_name(creator))
        parent_user = getattr(creator_agent, 'created_by', None)
        parent_agent = None
        if parent_user:
            parent_agent = Agent.objects.filter(user=parent_user).select_related('under_employee').first()
            if parent_agent:
                cp_name = _clean(parent_agent.name) or _clean(display_user_name(parent_user))

        employee = _resolve_agent_employee(creator_agent)
        if not employee and parent_agent:
            employee = _resolve_agent_employee(parent_agent)
        if not employee and legacy and getattr(legacy, 'assigned_employee', None):
            employee = legacy.assigned_employee
        if not employee and app and getattr(app, 'assigned_employee', None):
            employee = app.assigned_employee
        if employee:
            employee_name = _clean(display_user_name(employee))
            partner_name = _partner_for_employee(employee)
        if not partner_name and parent_user:
            partner_name = _clean(display_user_name(get_channel_partner_partner(parent_user)))

    elif creator_agent:
        cp_name = _clean(creator_agent.name) or _clean(display_user_name(creator))
        employee = _resolve_agent_employee(creator_agent)
        if not employee and legacy and getattr(legacy, 'assigned_employee', None):
            employee = legacy.assigned_employee
        if not employee and app and getattr(app, 'assigned_employee', None):
            employee = app.assigned_employee
        if employee:
            employee_name = _clean(display_user_name(employee))
            partner_name = _partner_for_employee(employee)

    elif creator and is_employee_role(getattr(creator, 'role', '')):
        employee_name = _clean(display_user_name(creator))
        partner_name = _partner_for_employee(creator)

    elif creator and is_partner_role(getattr(creator, 'role', '')):
        partner_name = _clean(display_user_name(creator))

    elif creator and is_admin_role(getattr(creator, 'role', '')):
        partner_name = _clean(display_user_name(creator)) or 'Admin'

    # Fallbacks from assignment when creator chain is incomplete
    if not cp_name and legacy and getattr(legacy, 'assigned_agent', None):
        assigned = legacy.assigned_agent
        if assigned and not is_sub_channel_partner_agent(assigned):
            cp_name = _clean(assigned.name)
    if not employee_name:
        emp = None
        if legacy and getattr(legacy, 'assigned_employee', None):
            emp = legacy.assigned_employee
        elif app and getattr(app, 'assigned_employee', None):
            emp = app.assigned_employee
        if emp:
            employee_name = _clean(display_user_name(emp))
            if not partner_name:
                partner_name = _partner_for_employee(emp)

    lines = []
    if scp_name:
        lines.append({'label': 'Sub Channel Partner', 'value': scp_name})
    if cp_name:
        lines.append({'label': 'Channel Partner', 'value': cp_name})
    if employee_name:
        lines.append({'label': 'Employee', 'value': employee_name})
    if partner_name or not lines:
        lines.append({'label': 'Partner', 'value': partner_name or '-'})

    return {
        'lines': lines,
        'scp_name': scp_name,
        'channel_partner_name': cp_name,
        'employee_name': employee_name,
        'partner_name': partner_name or '-',
    }


def get_workflow_submitted_by_label(loan=None, loan_application=None):
    """Single-line submitted-by label distinguishing CP vs SCP applications."""
    meta = get_submitted_processed_display(loan=loan, loan_application=loan_application)
    scp_name = str(meta.get('scp_name') or '').strip()
    cp_name = str(meta.get('channel_partner_name') or '').strip()
    if scp_name:
        parent = f" (Parent CP: {cp_name})" if cp_name else ''
        return f"Sub Channel Partner - {scp_name}{parent}"
    if cp_name:
        return f"Channel Partner - {cp_name}"
    if loan and getattr(loan, 'created_by', None):
        return get_loan_submitted_by_display(loan)
    return '-'

