import csv
import re

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook


def _display_user_name(user_obj):
    if not user_obj:
        return ''
    return user_obj.get_full_name() or user_obj.username or user_obj.email or ''


def _display_agent_name(agent_obj):
    if not agent_obj:
        return ''
    return agent_obj.name or _display_user_name(getattr(agent_obj, 'user', None)) or ''


def _format_datetime(value):
    if not value:
        return ''
    try:
        return timezone.localtime(value).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return str(value)


def _safe_filename_part(value):
    cleaned = re.sub(r'[^a-zA-Z0-9_-]+', '_', str(value or '').strip())
    return cleaned.strip('_') or 'report'


def loan_report_headers():
    return [
        'Loan ID',
        'Applicant Name',
        'Phone',
        'Email',
        'Loan Type',
        'Loan Amount',
        'Disbursed Amount',
        'Status',
        'Partner',
        'Assigned Employee',
        'Channel Partner',
        'Created By',
        'Created Time',
        'Updated Time',
        'Assigned Time',
        'Action Time',
        'Bank Name',
        'Bank Account Number',
        'Bank IFSC',
        'SM / DSA Name',
        'Remarks',
    ]


def loan_report_row(loan, status_key_getter=None, status_label_getter=None):
    raw_status = str(getattr(loan, 'status', '') or '').strip()
    status_key = status_key_getter(loan) if status_key_getter else getattr(loan, 'report_status_key', raw_status)
    status_label = status_label_getter(status_key) if status_label_getter else (getattr(loan, 'report_status_label', None) or status_key or raw_status)
    loan_type = (
        loan.get_loan_type_display()
        if hasattr(loan, 'get_loan_type_display')
        else (getattr(loan, 'loan_type', '') or '')
    )
    disbursed_amount = getattr(loan, 'report_disbursed_amount', None)
    if disbursed_amount is None:
        disbursed_amount = getattr(loan, 'loan_amount', '') if status_key == 'disbursed' else 0
    legacy_loan = getattr(loan, '_legacy_loan', loan)
    return [
        getattr(loan, 'user_id', '') or getattr(loan, 'id', ''),
        getattr(loan, 'full_name', '') or '',
        getattr(loan, 'mobile_number', '') or '',
        getattr(loan, 'email', '') or '',
        loan_type,
        getattr(loan, 'loan_amount', '') or 0,
        disbursed_amount or 0,
        status_label,
        getattr(loan, 'report_partner_name', '-') or '-',
        getattr(loan, 'report_employee_name', '') or _display_user_name(getattr(loan, 'assigned_employee', None)),
        getattr(loan, 'report_channel_partner_name', '') or _display_agent_name(getattr(loan, 'assigned_agent', None)),
        _display_user_name(getattr(legacy_loan, 'created_by', None) if legacy_loan else getattr(loan, 'created_by', None)),
        _format_datetime(getattr(loan, 'created_at', None)),
        _format_datetime(getattr(loan, 'updated_at', None)),
        _format_datetime(getattr(legacy_loan, 'assigned_at', None) if legacy_loan else None),
        _format_datetime(getattr(legacy_loan, 'action_taken_at', None) if legacy_loan else None),
        (getattr(legacy_loan, 'bank_name', '') or '') if legacy_loan else '',
        (getattr(legacy_loan, 'bank_account_number', '') or '') if legacy_loan else '',
        (getattr(legacy_loan, 'bank_ifsc_code', '') or '') if legacy_loan else '',
        (getattr(legacy_loan, 'sm_name', '') or '') if legacy_loan else '',
        (getattr(legacy_loan, 'remarks', '') or '') if legacy_loan else '',
    ]


def export_loans_csv(loans, period, filename_prefix, status_key_getter=None, status_label_getter=None):
    response = HttpResponse(content_type='text/csv')
    filename = f"{_safe_filename_part(filename_prefix)}_{_safe_filename_part(period)}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(loan_report_headers())
    for loan in loans:
        writer.writerow(loan_report_row(loan, status_key_getter, status_label_getter))
    return response


def export_loans_excel(loans, period, filename_prefix, status_key_getter=None, status_label_getter=None):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Loans'
    worksheet.append(loan_report_headers())
    for loan in loans:
        worksheet.append(loan_report_row(loan, status_key_getter, status_label_getter))

    for column in worksheet.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    filename = f"{_safe_filename_part(filename_prefix)}_{_safe_filename_part(period)}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    workbook.save(response)
    return response
