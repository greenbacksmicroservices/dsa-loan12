"""Helpers for admin panel list filtering and reports."""

from decimal import Decimal

from .models import User
from .id_utils import display_manual_loan_id


def _meta_created_by_admin(user_obj, admin_user):
    """True if onboarding _meta marks record as created by this admin."""
    if not user_obj or not admin_user:
        return False
    profile = getattr(user_obj, 'onboarding_profile', None)
    if not profile or not isinstance(profile.data, dict):
        return False
    meta = profile.data.get('_meta') or {}
    try:
        creator_id = int(meta.get('created_by_id') or 0)
    except (TypeError, ValueError):
        creator_id = 0
    if creator_id != admin_user.id:
        return False
    role = str(meta.get('created_by_role') or '').strip().lower()
    return role in ('admin', 'administrator', 'superuser') or 'admin' in role


def filter_employees_for_admin(employees_qs, admin_user, scope='all'):
    """scope: 'all' | 'mine'"""
    if scope != 'mine':
        return employees_qs
    matched_ids = []
    for employee in employees_qs:
        if _meta_created_by_admin(employee, admin_user):
            matched_ids.append(employee.id)
    return employees_qs.filter(id__in=matched_ids)


def filter_partners_for_admin(partners_qs, admin_user, scope='all'):
    """scope: 'all' | 'mine' - partners are User rows with role=subadmin."""
    if scope != 'mine':
        return partners_qs
    matched_ids = []
    for partner in partners_qs:
        if _meta_created_by_admin(partner, admin_user):
            matched_ids.append(partner.id)
    return partners_qs.filter(id__in=matched_ids)


def filter_agents_for_admin(agents_qs, admin_user, scope='all'):
    """scope: 'all' | 'mine'"""
    if scope != 'mine':
        return agents_qs
    matched_ids = []
    for agent in agents_qs.select_related('user', 'user__onboarding_profile', 'created_by'):
        if agent.created_by_id == admin_user.id:
            matched_ids.append(agent.id)
        elif agent.user and _meta_created_by_admin(agent.user, admin_user):
            matched_ids.append(agent.id)
    return agents_qs.filter(id__in=matched_ids)


def _status_label(raw_status):
    value = str(raw_status or '').strip().lower()
    mapping = {
        'draft': 'Draft',
        'new_entry': 'New Application',
        'waiting': 'Document Pending',
        'follow_up': 'Banking Processing',
        'approved': 'Approved',
        'rejected': 'Rejected',
        'disbursed': 'Disbursed',
        'forclose': 'For Close',
        'disputed': 'Disputed',
    }
    return mapping.get(value, raw_status or '-')


def _parse_detail_rows(raw_text):
    rows = []
    seen = set()
    for raw_line in str(raw_text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = raw_line.strip()
        if not line or ':' not in line:
            continue
        label, value = line.split(':', 1)
        clean_label = str(label or '').strip()
        clean_value = str(value or '').strip()
        if not clean_label or not clean_value:
            continue
        key = clean_label.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            'label': clean_label,
            'value': clean_value,
        })
    return rows


def _serialize_documents(loan_obj):
    docs = []
    for doc in getattr(loan_obj, 'documents', []).all():
        if not getattr(doc, 'file', None):
            continue
        docs.append({
            'name': doc.get_document_type_display() if hasattr(doc, 'get_document_type_display') else str(doc.document_type or 'Document'),
            'url': doc.file.url,
            'uploaded_at': doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else '',
        })
    return docs


def _decimal_to_float(value):
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def serialize_report_application(loan_obj):
    assigned_employee = getattr(loan_obj, 'assigned_employee', None)
    assigned_agent = getattr(loan_obj, 'assigned_agent', None)
    created_by = getattr(loan_obj, 'created_by', None)
    details = [
        {'label': 'Manual Loan ID', 'value': display_manual_loan_id(loan_obj)},
        {'label': 'Customer Name', 'value': loan_obj.full_name or '-'},
        {'label': 'Mobile', 'value': loan_obj.mobile_number or '-'},
        {'label': 'Email', 'value': loan_obj.email or '-'},
        {'label': 'City', 'value': loan_obj.city or '-'},
        {'label': 'State', 'value': loan_obj.state or '-'},
        {'label': 'PIN Code', 'value': loan_obj.pin_code or '-'},
        {'label': 'Loan Type', 'value': loan_obj.get_loan_type_display() if hasattr(loan_obj, 'get_loan_type_display') else (loan_obj.loan_type or '-')},
        {'label': 'Loan Amount', 'value': f"{_decimal_to_float(loan_obj.loan_amount):.2f}"},
        {'label': 'Tenure (Months)', 'value': loan_obj.tenure_months or '-'},
        {'label': 'Interest Rate', 'value': loan_obj.interest_rate or '-'},
        {'label': 'Loan Purpose', 'value': loan_obj.loan_purpose or '-'},
        {'label': 'Bank Name', 'value': loan_obj.bank_name or '-'},
        {'label': 'Account Number', 'value': loan_obj.bank_account_number or '-'},
        {'label': 'IFSC Code', 'value': loan_obj.bank_ifsc_code or '-'},
        {'label': 'Status', 'value': _status_label(loan_obj.status)},
        {'label': 'Created By', 'value': (created_by.get_full_name() or created_by.username) if created_by else 'System'},
        {'label': 'Assigned Employee', 'value': (assigned_employee.get_full_name() or assigned_employee.username) if assigned_employee else '-'},
        {'label': 'Assigned Channel Partner', 'value': assigned_agent.name if assigned_agent else '-'},
        {'label': 'Created At', 'value': loan_obj.created_at.strftime('%Y-%m-%d %H:%M') if loan_obj.created_at else '-'},
        {'label': 'Updated At', 'value': loan_obj.updated_at.strftime('%Y-%m-%d %H:%M') if loan_obj.updated_at else '-'},
    ]
    details.extend(_parse_detail_rows(getattr(loan_obj, 'remarks', '')))
    documents = _serialize_documents(loan_obj)
    status_key = str(getattr(loan_obj, 'status', '') or '').strip().lower()
    loan_amount = _decimal_to_float(getattr(loan_obj, 'loan_amount', 0))
    approved_amount = loan_amount if status_key in ['approved', 'disbursed'] else 0.0
    disbursed_amount = loan_amount if status_key == 'disbursed' else 0.0
    return {
        'id': loan_obj.id,
        'loan_id': display_manual_loan_id(loan_obj),
        'reference_id': f'REF-{loan_obj.id:06d}',
        'customer_name': loan_obj.full_name or '-',
        'mobile': loan_obj.mobile_number or '-',
        'email': loan_obj.email or '-',
        'city': loan_obj.city or '-',
        'state': loan_obj.state or '-',
        'loan_type': loan_obj.get_loan_type_display() if hasattr(loan_obj, 'get_loan_type_display') else (loan_obj.loan_type or '-'),
        'loan_amount': loan_amount,
        'approved_amount': approved_amount,
        'disbursed_amount': disbursed_amount,
        'status': status_key,
        'status_display': _status_label(loan_obj.status),
        'created_at': loan_obj.created_at.strftime('%Y-%m-%d %H:%M') if loan_obj.created_at else '',
        'updated_at': loan_obj.updated_at.strftime('%Y-%m-%d %H:%M') if loan_obj.updated_at else '',
        'bank_name': loan_obj.bank_name or '-',
        'remarks': loan_obj.remarks or '',
        'details': details,
        'documents': documents,
        'document_count': len(documents),
    }


def _member_row_base(*, member_id, code, name, email, phone, status, joined, applications):
    app_rows = [serialize_report_application(loan_obj) for loan_obj in applications]
    approved_count = sum(1 for row in app_rows if row['status'] in ['approved', 'disbursed'])
    disbursed_count = sum(1 for row in app_rows if row['status'] == 'disbursed')
    approved_amount = round(sum(row['approved_amount'] for row in app_rows), 2)
    disbursed_amount = round(sum(row['disbursed_amount'] for row in app_rows), 2)
    return {
        'id': member_id,
        'member_code': code,
        'name': name,
        'email': email,
        'phone': phone,
        'status': status,
        'joined': joined,
        'total_applications': len(app_rows),
        'approved_count': approved_count,
        'approved_amount': approved_amount,
        'disbursed_count': disbursed_count,
        'disbursed_amount': disbursed_amount,
        'applications': app_rows,
    }


def build_partner_report_rows(partners, partner_applications_map=None):
    partner_applications_map = partner_applications_map or {}
    rows = []
    for partner in partners:
        base = _member_row_base(
            member_id=partner.id,
            code=partner.employee_id or f'EDC-P-{partner.id:04d}',
            name=partner.get_full_name() or partner.username,
            email=partner.email or '',
            phone=partner.phone or '',
            status='Active' if partner.is_active else 'Inactive',
            joined=partner.date_joined.strftime('%Y-%m-%d') if partner.date_joined else '',
            applications=partner_applications_map.get(partner.id, []),
        )
        base.update({
            'partner_id': base['member_code'],
            'username': partner.username or '',
        })
        rows.append(base)
    return rows


def build_employee_report_rows(employees, employee_creator_display=None, employee_location_display=None, employee_applications_map=None):
    employee_creator_display = employee_creator_display or {}
    employee_location_display = employee_location_display or {}
    employee_applications_map = employee_applications_map or {}
    rows = []
    for employee in employees:
        base = _member_row_base(
            member_id=employee.id,
            code=employee.employee_id or f'EDC-EMP-{employee.id:04d}',
            name=employee.get_full_name() or employee.username,
            email=employee.email or '',
            phone=employee.phone or '',
            status='Active' if employee.is_active else 'Inactive',
            joined=employee.date_joined.strftime('%Y-%m-%d') if employee.date_joined else '',
            applications=employee_applications_map.get(employee.id, []),
        )
        base.update({
            'employee_id': base['member_code'],
            'location': employee_location_display.get(employee.id, '-'),
            'created_under': employee_creator_display.get(employee.id, 'Admin - System'),
        })
        rows.append(base)
    return rows


def build_agent_report_rows(agents, agent_location_display=None, agent_applications_map=None):
    agent_location_display = agent_location_display or {}
    agent_applications_map = agent_applications_map or {}
    rows = []
    for agent in agents:
        created_by = ''
        if agent.created_by:
            created_by = agent.created_by.get_full_name() or agent.created_by.username
        base = _member_row_base(
            member_id=agent.id,
            code=agent.agent_id or f'EDC-CP-{agent.id:04d}',
            name=agent.name or '',
            email=agent.email or '',
            phone=agent.phone or '',
            status='Active' if str(agent.status or '').lower() == 'active' else 'Inactive',
            joined=agent.created_at.strftime('%Y-%m-%d') if agent.created_at else '',
            applications=agent_applications_map.get(agent.id, []),
        )
        base.update({
            'agent_id': base['member_code'],
            'location': agent_location_display.get(agent.id, '-'),
            'created_by': created_by or 'Admin',
        })
        rows.append(base)
    return rows
