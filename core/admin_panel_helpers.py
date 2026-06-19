"""Helpers for admin panel list filtering and reports."""

from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Q
from django.utils import timezone

from .loan_helpers import display_loan_id, display_user_name
from .loan_sync import extract_assignment_context, find_related_loan, find_related_loan_application
from .models import Agent, ApplicantDocument, Loan, LoanApplication, User
from .id_utils import display_manual_loan_id
from .remarks_utils import sanitize_display_remark
from .updated_document_utils import (
    UPDATED_DOCUMENT_STATUS_KEY,
    application_has_updated_documents,
    loan_has_updated_documents,
)
from .workflow_rows import application_effective_status_key, build_application_display_row, loan_type_display

NOT_ASSIGNED = 'Not Assigned'


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
        'follow_up': 'Bank Login Process',
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
    document_source = getattr(loan_obj, 'documents', None)
    if document_source is None:
        return docs
    document_iter = document_source.all() if hasattr(document_source, 'all') else document_source
    for doc in document_iter:
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


def _report_has_revert_marker(text):
    return 'revert remark' in str(text or '').lower()


def report_effective_status_key(loan_obj=None, loan_app=None):
    """Resolve the dashboard/report status key from legacy loan and/or application."""
    if loan_app:
        return application_effective_status_key(loan_app)

    if not loan_obj:
        return ''

    raw_status = str(getattr(loan_obj, 'status', '') or '').strip().lower()
    related_app = find_related_loan_application(loan_obj)

    if raw_status in ['new_entry', 'waiting']:
        if _report_has_revert_marker(getattr(loan_obj, 'remarks', '')):
            return 'follow_up_pending'
        if related_app and _report_has_revert_marker(getattr(related_app, 'approval_notes', '')):
            return 'follow_up_pending'
    if raw_status == 'waiting' and loan_has_updated_documents(loan_obj, related_app=related_app):
        return UPDATED_DOCUMENT_STATUS_KEY
    if related_app:
        return application_effective_status_key(related_app)
    return raw_status


def report_status_label(status_key):
    labels = {
        'draft': 'Draft',
        'new_entry': 'New Application',
        'waiting': 'Document Pending',
        UPDATED_DOCUMENT_STATUS_KEY: 'Pending Document Cleared',
        'follow_up': 'Bank Login Process',
        'follow_up_pending': 'Follow Up',
        'approved': 'Approved',
        'rejected': 'Rejected',
        'disbursed': 'Disbursed',
        'forclose': 'For Close',
        'disputed': 'Disputed',
    }
    return labels.get(str(status_key or '').strip().lower(), status_key or '-')


def _resolve_report_partner_user(loan_obj=None, loan_app=None):
    assignment_context = extract_assignment_context(loan_obj, loan_app) if loan_obj else extract_assignment_context(None, loan_app)
    assigned_by_user = assignment_context.get('assigned_by_user')

    if loan_app and getattr(loan_app, 'lead_received_by', None):
        receiver = loan_app.lead_received_by
        if str(getattr(receiver, 'role', '') or '').strip().lower() in {'subadmin', 'partner'}:
            return receiver

    if getattr(assigned_by_user, 'role', '') == 'subadmin':
        return assigned_by_user

    for source in (
        getattr(loan_app, 'assigned_by', None) if loan_app else None,
        getattr(loan_obj, 'created_by', None) if loan_obj else None,
    ):
        if getattr(source, 'role', '') == 'subadmin':
            return source

    for source in (
        getattr(loan_app, 'assigned_agent', None) if loan_app else None,
        getattr(loan_obj, 'assigned_agent', None) if loan_obj else None,
    ):
        created_by = getattr(source, 'created_by', None)
        if getattr(created_by, 'role', '') == 'subadmin':
            return created_by

    return None


def _resolve_report_employee_user(loan_obj=None, loan_app=None):
    if loan_app and loan_app.assigned_employee:
        return loan_app.assigned_employee
    if loan_obj and loan_obj.assigned_employee:
        return loan_obj.assigned_employee
    if loan_app and getattr(loan_app, 'lead_received_by', None):
        receiver = loan_app.lead_received_by
        if str(getattr(receiver, 'role', '') or '').strip().lower() == 'employee':
            return receiver
    return None


def _resolve_report_channel_partner(loan_obj=None, loan_app=None):
    if loan_app and loan_app.assigned_agent:
        return loan_app.assigned_agent
    if loan_obj and loan_obj.assigned_agent:
        return loan_obj.assigned_agent
    return None


def _resolve_report_disbursement_amount(loan_obj=None, loan_app=None, status_key=''):
    status_key = str(status_key or '').strip().lower()
    if status_key != 'disbursed':
        return 0.0
    if loan_app and loan_app.disbursement_amount is not None:
        return _decimal_to_float(loan_app.disbursement_amount)
    if loan_obj and loan_obj.loan_amount is not None:
        return _decimal_to_float(loan_obj.loan_amount)
    if loan_app and getattr(getattr(loan_app, 'applicant', None), 'loan_amount', None) is not None:
        return _decimal_to_float(loan_app.applicant.loan_amount)
    return 0.0


def _report_document_count(loan_obj):
    document_source = getattr(loan_obj, 'documents', None)
    if document_source is None:
        return 0
    try:
        if hasattr(document_source, 'count'):
            return int(document_source.count())
    except (TypeError, ValueError):
        pass
    try:
        document_iter = document_source.all() if hasattr(document_source, 'all') else document_source
        return sum(1 for _ in document_iter)
    except Exception:
        return 0


def format_report_currency(amount):
    value = _decimal_to_float(amount)
    if value <= 0:
        return '-'
    return f'₹{value:,.0f}'


def enrich_admin_report_row(row, loan_obj=None, loan_app=None):
    """Attach latest report display fields to a legacy loan or workflow row."""
    if loan_obj and not loan_app:
        loan_app = find_related_loan_application(loan_obj)
    if loan_app and not loan_obj:
        loan_obj = find_related_loan(loan_app)

    status_key = report_effective_status_key(loan_obj=loan_obj, loan_app=loan_app)
    partner_user = _resolve_report_partner_user(loan_obj=loan_obj, loan_app=loan_app)
    employee_user = _resolve_report_employee_user(loan_obj=loan_obj, loan_app=loan_app)
    channel_partner = _resolve_report_channel_partner(loan_obj=loan_obj, loan_app=loan_app)
    disbursed_amount = _resolve_report_disbursement_amount(
        loan_obj=loan_obj,
        loan_app=loan_app,
        status_key=status_key,
    )

    row.report_status_key = status_key
    row.report_status_label = report_status_label(status_key)
    row.report_partner_name = display_user_name(partner_user) if partner_user else '-'
    row.report_employee_name = display_user_name(employee_user) if employee_user else NOT_ASSIGNED
    row.report_channel_partner_name = (
        channel_partner.name
        or display_user_name(getattr(channel_partner, 'user', None))
        if channel_partner else '-'
    )
    row.report_disbursed_amount = disbursed_amount
    row.report_disbursed_amount_display = format_report_currency(disbursed_amount)
    row.report_document_count = _report_document_count(loan_obj)
    row._related_app = loan_app
    row._legacy_loan = loan_obj
    return row


def _application_report_documents(loan_app):
    return ApplicantDocument.objects.filter(loan_application=loan_app)


class ApplicationReportRow(SimpleNamespace):
    def get_loan_type_display(self):
        return loan_type_display(getattr(self, 'loan_type', ''))


def application_to_report_row(loan_app):
    applicant = getattr(loan_app, 'applicant', None)
    row = ApplicationReportRow(
        id=loan_app.id,
        entity_type='application',
        user_id=display_loan_id(legacy_loan=find_related_loan(loan_app), loan_application=loan_app) or str(loan_app.id),
        full_name=getattr(applicant, 'full_name', '') or '-',
        email=getattr(applicant, 'email', '') or '',
        mobile_number=getattr(applicant, 'mobile', '') or '',
        loan_type=getattr(applicant, 'loan_type', '') or '',
        loan_amount=getattr(applicant, 'loan_amount', 0) or 0,
        created_at=loan_app.created_at,
        updated_at=loan_app.updated_at,
        assigned_employee=loan_app.assigned_employee,
        assigned_agent=loan_app.assigned_agent,
        created_by=loan_app.assigned_by,
        status=application_effective_status_key(loan_app),
        documents=_application_report_documents(loan_app),
    )
    return enrich_admin_report_row(row, loan_app=loan_app)


def build_admin_filtered_report_loans(
    *,
    start_date,
    end_date,
    search_query='',
    status_filter='',
    employee_filter='',
    partner_filter='',
    agent_filter='',
    loan_id_filter='',
):
    """Build enriched report rows from legacy loans and workflow-only applications."""
    import logging

    report_logger = logging.getLogger(__name__)
    related_app_ids = set()
    enriched_rows = []

    try:
        loans_qs = Loan.objects.select_related(
            'created_by',
            'assigned_employee',
            'assigned_agent',
            'assigned_agent__created_by',
            'assigned_agent__user',
        ).prefetch_related('documents').filter(
            created_at__gte=start_date,
            created_at__lt=end_date,
        )
    except Exception:
        report_logger.exception('Failed to query legacy loans for admin reports')
        loans_qs = Loan.objects.none()

    if loan_id_filter:
        try:
            loans_qs = loans_qs.filter(id=int(loan_id_filter))
        except (TypeError, ValueError):
            loans_qs = loans_qs.none()

    if search_query:
        search_filter = (
            Q(full_name__icontains=search_query)
            | Q(mobile_number__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(user_id__icontains=search_query)
        )
        if search_query.isdigit():
            search_filter |= Q(id=int(search_query))
        loans_qs = loans_qs.filter(search_filter)

    try:
        apps_qs = LoanApplication.objects.select_related(
            'applicant',
            'assigned_employee',
            'assigned_agent',
            'assigned_agent__created_by',
            'assigned_agent__user',
            'assigned_by',
            'lead_received_by',
        ).filter(
            created_at__gte=start_date,
            created_at__lt=end_date,
        )
    except Exception:
        report_logger.exception('Failed to query loan applications for admin reports')
        apps_qs = LoanApplication.objects.none()

    for loan in loans_qs.order_by('-created_at'):
        related_app = find_related_loan_application(loan)
        if related_app:
            related_app_ids.add(related_app.id)

        if not _matches_employee_filter(loan, related_app, employee_filter):
            continue
        if not _matches_partner_filter(loan, related_app, partner_filter):
            continue
        if not _matches_agent_filter(loan, related_app, agent_filter):
            continue

        status_key = report_effective_status_key(loan_obj=loan, loan_app=related_app)
        if status_filter and status_key != status_filter:
            continue

        try:
            enriched_rows.append(enrich_admin_report_row(loan, loan_obj=loan, loan_app=related_app))
        except Exception:
            report_logger.exception('Failed to enrich legacy loan %s for reports', getattr(loan, 'id', '?'))

    try:
        app_iterator = apps_qs.order_by('-created_at')
    except Exception:
        report_logger.exception('Failed to iterate loan applications for admin reports')
        app_iterator = []

    for loan_app in app_iterator:
        if loan_app.id in related_app_ids:
            continue

        if loan_id_filter:
            try:
                if loan_app.id != int(loan_id_filter):
                    continue
            except (TypeError, ValueError):
                continue

        applicant = getattr(loan_app, 'applicant', None)
        if search_query:
            haystack = ' '.join([
                str(getattr(applicant, 'full_name', '') or ''),
                str(getattr(applicant, 'mobile', '') or ''),
                str(getattr(applicant, 'email', '') or ''),
                str(loan_app.id),
            ]).lower()
            if search_query.lower() not in haystack:
                continue

        if not _matches_employee_filter(None, loan_app, employee_filter):
            continue
        if not _matches_partner_filter(None, loan_app, partner_filter):
            continue
        if not _matches_agent_filter(None, loan_app, agent_filter):
            continue

        status_key = report_effective_status_key(loan_app=loan_app)
        if status_filter and status_key != status_filter:
            continue

        try:
            enriched_rows.append(application_to_report_row(loan_app))
        except Exception:
            report_logger.exception('Failed to enrich application %s for reports', getattr(loan_app, 'id', '?'))

    enriched_rows.sort(
        key=lambda item: getattr(item, 'created_at', None) or start_date,
        reverse=True,
    )
    return enriched_rows


def _matches_employee_filter(loan_obj, loan_app, employee_filter):
    if not employee_filter:
        return True
    target = str(employee_filter)
    if loan_app and str(loan_app.assigned_employee_id or '') == target:
        return True
    if loan_obj and str(loan_obj.assigned_employee_id or '') == target:
        return True
    return False


def _matches_partner_filter(loan_obj, loan_app, partner_filter):
    if not partner_filter:
        return True
    partner_user = _resolve_report_partner_user(loan_obj=loan_obj, loan_app=loan_app)
    return str(getattr(partner_user, 'id', '') or '') == str(partner_filter)


def _matches_agent_filter(loan_obj, loan_app, agent_filter):
    if not agent_filter:
        return True
    channel_partner = _resolve_report_channel_partner(loan_obj=loan_obj, loan_app=loan_app)
    return str(getattr(channel_partner, 'id', '') or '') == str(agent_filter)


def serialize_report_application(loan_obj):
    related_app = getattr(loan_obj, '_related_app', None) or find_related_loan_application(loan_obj)
    legacy_loan = getattr(loan_obj, '_legacy_loan', None) or (
        loan_obj if isinstance(loan_obj, Loan) else find_related_loan(related_app)
    )
    enrich_admin_report_row(loan_obj, loan_obj=legacy_loan, loan_app=related_app)

    assigned_employee = _resolve_report_employee_user(loan_obj=legacy_loan, loan_app=related_app)
    assigned_agent = _resolve_report_channel_partner(loan_obj=legacy_loan, loan_app=related_app)
    partner_user = _resolve_report_partner_user(loan_obj=legacy_loan, loan_app=related_app)
    created_by = getattr(legacy_loan, 'created_by', None) if legacy_loan else getattr(related_app, 'assigned_by', None)
    status_key = getattr(loan_obj, 'report_status_key', None) or report_effective_status_key(
        loan_obj=legacy_loan,
        loan_app=related_app,
    )
    disbursed_amount = getattr(loan_obj, 'report_disbursed_amount', None)
    if disbursed_amount is None:
        disbursed_amount = _resolve_report_disbursement_amount(
            loan_obj=legacy_loan,
            loan_app=related_app,
            status_key=status_key,
        )

    loan_type_value = (
        loan_obj.get_loan_type_display()
        if hasattr(loan_obj, 'get_loan_type_display')
        else (getattr(loan_obj, 'loan_type', '') or '-')
    )
    details = [
        {'label': 'Loan ID', 'value': display_loan_id(legacy_loan=legacy_loan, loan_application=related_app) or '-'},
        {'label': 'Customer Name', 'value': getattr(loan_obj, 'full_name', '') or '-'},
        {'label': 'Mobile', 'value': getattr(loan_obj, 'mobile_number', '') or '-'},
        {'label': 'Email', 'value': getattr(loan_obj, 'email', '') or '-'},
        {'label': 'City', 'value': getattr(legacy_loan, 'city', '-') if legacy_loan else '-'},
        {'label': 'State', 'value': getattr(legacy_loan, 'state', '-') if legacy_loan else '-'},
        {'label': 'PIN Code', 'value': getattr(legacy_loan, 'pin_code', '-') if legacy_loan else '-'},
        {'label': 'Loan Type', 'value': loan_type_value},
        {'label': 'Loan Amount', 'value': f"{_decimal_to_float(getattr(loan_obj, 'loan_amount', 0)):.2f}"},
        {'label': 'Disbursed Amount', 'value': f"{_decimal_to_float(disbursed_amount):.2f}"},
        {'label': 'Tenure (Months)', 'value': getattr(legacy_loan, 'tenure_months', '-') if legacy_loan else '-'},
        {'label': 'Interest Rate', 'value': getattr(legacy_loan, 'interest_rate', '-') if legacy_loan else '-'},
        {'label': 'Loan Purpose', 'value': getattr(legacy_loan, 'loan_purpose', '-') if legacy_loan else '-'},
        {'label': 'Bank Name', 'value': getattr(legacy_loan, 'bank_name', '-') if legacy_loan else '-'},
        {'label': 'Account Number', 'value': getattr(legacy_loan, 'bank_account_number', '-') if legacy_loan else '-'},
        {'label': 'IFSC Code', 'value': getattr(legacy_loan, 'bank_ifsc_code', '-') if legacy_loan else '-'},
        {'label': 'Status', 'value': report_status_label(status_key)},
        {'label': 'Partner', 'value': display_user_name(partner_user) if partner_user else '-'},
        {'label': 'Created By', 'value': (created_by.get_full_name() or created_by.username) if created_by else 'System'},
        {'label': 'Assigned Employee', 'value': display_user_name(assigned_employee) if assigned_employee else NOT_ASSIGNED},
        {'label': 'Assigned Channel Partner', 'value': (
            assigned_agent.name or display_user_name(getattr(assigned_agent, 'user', None))
        ) if assigned_agent else '-'},
        {'label': 'Created At', 'value': loan_obj.created_at.strftime('%Y-%m-%d %H:%M') if getattr(loan_obj, 'created_at', None) else '-'},
        {'label': 'Updated At', 'value': loan_obj.updated_at.strftime('%Y-%m-%d %H:%M') if getattr(loan_obj, 'updated_at', None) else '-'},
    ]
    if legacy_loan:
        details.extend(_parse_detail_rows(getattr(legacy_loan, 'remarks', '')))
    documents = _serialize_documents(loan_obj)
    loan_amount = _decimal_to_float(getattr(loan_obj, 'loan_amount', 0))
    approved_amount = loan_amount if status_key in ['approved', 'disbursed'] else 0.0
    disbursed_total = _decimal_to_float(disbursed_amount) if status_key == 'disbursed' else 0.0
    return {
        'id': getattr(loan_obj, 'id', ''),
        'loan_id': display_loan_id(legacy_loan=legacy_loan, loan_application=related_app) or '-',
        'reference_id': f'REF-{getattr(loan_obj, "id", 0):06d}',
        'customer_name': getattr(loan_obj, 'full_name', '') or '-',
        'mobile': getattr(loan_obj, 'mobile_number', '') or '-',
        'email': getattr(loan_obj, 'email', '') or '-',
        'city': getattr(legacy_loan, 'city', '-') if legacy_loan else '-',
        'state': getattr(legacy_loan, 'state', '-') if legacy_loan else '-',
        'loan_type': loan_type_value,
        'loan_amount': loan_amount,
        'approved_amount': approved_amount,
        'disbursed_amount': disbursed_total,
        'status': status_key,
        'status_display': report_status_label(status_key),
        'partner_name': display_user_name(partner_user) if partner_user else '-',
        'employee_name': display_user_name(assigned_employee) if assigned_employee else NOT_ASSIGNED,
        'channel_partner_name': (
            assigned_agent.name or display_user_name(getattr(assigned_agent, 'user', None))
        ) if assigned_agent else '-',
        'created_at': loan_obj.created_at.strftime('%Y-%m-%d %H:%M') if getattr(loan_obj, 'created_at', None) else '',
        'updated_at': loan_obj.updated_at.strftime('%Y-%m-%d %H:%M') if getattr(loan_obj, 'updated_at', None) else '',
        'bank_name': getattr(legacy_loan, 'bank_name', '-') if legacy_loan else '-',
        'remarks': sanitize_display_remark(getattr(legacy_loan, 'remarks', ''), default='') if legacy_loan else '',
        'details': details,
        'documents': documents,
        'document_count': len(documents),
    }


def _member_row_base(*, member_id, code, name, email, phone, status, joined, applications):
    app_rows = []
    for loan_obj in applications or []:
        try:
            app_rows.append(serialize_report_application(loan_obj))
        except Exception:
            continue
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


def build_admin_reports_filter_options():
    """Load dropdown filter options for the admin reports page."""
    employees = User.objects.filter(role='employee').order_by('first_name', 'last_name', 'username')
    partners = User.objects.filter(role='subadmin').order_by('first_name', 'last_name', 'username')
    agents = Agent.objects.order_by('name', 'id')
    return employees, partners, agents


def build_admin_reports_empty_context(
    *,
    period='1year',
    from_date='',
    to_date='',
    search_query='',
    status_filter='',
    employee_filter='',
    partner_filter='',
    agent_filter='',
    report_error=None,
):
    """Safe defaults so the reports template always renders."""
    employees, partners, agents = build_admin_reports_filter_options()
    return {
        'page_title': 'Reports & Analytics',
        'report_partner_rows': [],
        'report_employee_rows': [],
        'report_agent_rows': [],
        'filtered_report_loans': [],
        'total_applications': 0,
        'new_count': 0,
        'processing_count': 0,
        'updated_document_count': 0,
        'followup_count': 0,
        'followup_pending_count': 0,
        'approved_count': 0,
        'rejected_count': 0,
        'disbursed_count': 0,
        'new_percent': 0,
        'processing_percent': 0,
        'followup_percent': 0,
        'approved_percent': 0,
        'rejected_percent': 0,
        'disbursed_percent': 0,
        'total_amount': 0,
        'approved_amount': 0,
        'disbursed_amount': 0,
        'pending_amount': 0,
        'avg_loan_value': 0,
        'total_employees': employees.count(),
        'active_employees': employees.filter(is_active=True).count(),
        'total_agents': agents.count(),
        'active_agents': agents.filter(status='active').count(),
        'total_subadmins': partners.count(),
        'download_people': [],
        'period': period,
        'from_date': from_date,
        'to_date': to_date,
        'search_query': search_query,
        'status_filter': status_filter,
        'employee_filter': employee_filter,
        'partner_filter': partner_filter,
        'agent_filter': agent_filter,
        'employee_options': employees,
        'partner_options': partners,
        'agent_options': agents,
        'report_refreshed_at': timezone.now(),
        'report_error': report_error,
    }
