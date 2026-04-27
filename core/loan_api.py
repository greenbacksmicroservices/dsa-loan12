"""
Loan Management API Endpoints
Handles all loan-related API requests for admin panel including details, reject, disburse, delete
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from datetime import datetime
import json
import re

from .models import Loan, LoanStatusHistory, LoanApplication, LoanDocument, ApplicantDocument
from .decorators import admin_required
from .loan_sync import extract_assignment_context, find_related_loan_application

FOLLOW_UP_PENDING_LABEL = 'Follow Up'


def _has_revert_marker(value):
    return 'revert remark' in str(value or '').lower()


def _is_follow_up_pending(loan_obj, loan_app_obj=None):
    if not loan_obj or (loan_obj.status or '').strip().lower() not in ['new_entry', 'waiting']:
        return False
    if _has_revert_marker(getattr(loan_obj, 'remarks', '')):
        return True
    return _has_revert_marker(getattr(loan_app_obj, 'approval_notes', '')) if loan_app_obj else False


def _ui_status_label(status_text):
    normalized = str(status_text or '').strip().lower()
    if normalized in ['new entry', 'new_entry', 'draft']:
        return 'New Application'
    if normalized in ['waiting for processing', 'in processing', 'waiting', 'processing']:
        return 'Document Pending'
    if normalized in ['required follow-up', 'required follow up']:
        return 'Banking Processing'
    return status_text


# ============= LOAN MANAGEMENT API ENDPOINTS =============

@login_required(login_url='admin_login')
@admin_required
@require_GET
def api_loan_details(request, loan_id):
    """
    API Endpoint: Get comprehensive loan details for the detail modal
    Returns: All applicant information across sections
    """
    try:
        loan = get_object_or_404(Loan, id=loan_id)

        def normalize_lookup_key(value):
            cleaned = re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower())
            return ' '.join(cleaned.split())

        def humanize_key(value):
            normalized = normalize_lookup_key(value)
            return ' '.join(part.capitalize() for part in normalized.split())

        def parse_extra_info(raw_text):
            parsed = {}
            if not raw_text:
                return parsed
            raw_value = str(raw_text).strip()

            # Handle JSON-like remarks payloads as a fallback.
            if raw_value.startswith('{') and raw_value.endswith('}'):
                try:
                    parsed_json = json.loads(raw_value)
                    if isinstance(parsed_json, dict):
                        for key, value in parsed_json.items():
                            norm_key = normalize_lookup_key(key)
                            if not norm_key:
                                continue
                            if isinstance(value, (list, dict)):
                                value_text = json.dumps(value, ensure_ascii=False)
                            else:
                                value_text = str(value or '').strip()
                            if value_text:
                                parsed[norm_key] = value_text
                except Exception:
                    pass

            text = raw_value.replace('\r', '\n')
            scan_text = re.sub(r'\s+', ' ', text).strip()
            known_labels = [
                'Alternate Mobile',
                'Father Name',
                "Father's Name",
                'Fathers Name',
                'Mother Name',
                "Mother's Name",
                'Mothers Name',
                'Date of Birth',
                'DOB',
                'Gender',
                'Marital Status',
                'Permanent Address',
                'Permanent Landmark',
                'Permanent City',
                'Permanent PIN',
                'Present Address',
                'Present Landmark',
                'Present City',
                'Present PIN',
                'Current Address',
                'Occupation',
                'Date of Joining',
                'Experience (Years)',
                'Year of Experience',
                'Additional Income',
                'Extra Income',
                'Extra Income Details',
                'Company Name',
                'Official Email ID',
                'Designation',
                'Previous Company',
                'Salary',
                'Gross Salary',
                'Net Salary',
                'Nature of Business',
                'Stock Value',
                'Number of Employees',
                'ITR Details',
                'Loan Purpose',
                'Purpose',
                'Service Required',
                'Charges/Fee',
                'Charges Or Fee',
                'Any Charges Or Fee',
                'Any Charges Or Fees',
                'Charges Applicable',
                'CIBIL Score',
                'Aadhar Number',
                'Aadhaar Number',
                'Aadhar',
                'Aadhaar',
                'PAN Number',
                'PAN',
                'Bank Name',
                'Account Number',
                'Bank Account No',
                'IFSC Code',
                'IFSC',
                'Bank Type',
                'Remarks/Suggestions',
                'Remarks Suggestions',
                'Remark',
                'Declaration',
                'Assigned By Admin',
                'Assigned By SubAdmin',
                'Assigned By Partner',
                'Assigned By',
            ]
            for idx in [1, 2, 3]:
                known_labels.extend([
                    f'Loan {idx} Bank/Finance Name',
                    f'Loan {idx} Bank',
                    f'Loan {idx} Amount Taken',
                    f'Loan {idx} EMI Left',
                    f'Loan {idx} Amount Left',
                    f'Loan {idx} Years/Months',
                    f'Loan {idx} Duration',
                    f'Loan {idx} EMI Amount',
                    f'Loan {idx} Any Bounce',
                    f'Loan {idx} Cleared',
                    f'Reference {idx} Name',
                    f'Reference {idx} Mobile',
                    f'Reference {idx} Address',
                ])
            for idx in range(1, 11):
                known_labels.append(f'Document {idx}')

            candidates = {}
            for label in known_labels:
                pattern = re.compile(r'(?i)(?<![A-Za-z0-9])' + re.escape(label) + r'\s*:')
                for match in pattern.finditer(scan_text):
                    start = match.start()
                    current = candidates.get(start)
                    if not current or (match.end() - match.start()) > (current[0] - start):
                        candidates[start] = (match.end(), label)

            ordered = sorted(
                [(start, end, label) for start, (end, label) in candidates.items()],
                key=lambda item: item[0]
            )

            for idx, (_, end, label) in enumerate(ordered):
                next_start = ordered[idx + 1][0] if idx + 1 < len(ordered) else len(scan_text)
                value = scan_text[end:next_start].strip(' ;,')
                key = normalize_lookup_key(label)
                if key and value:
                    parsed[key] = value

            for raw_line in text.split('\n'):
                line = raw_line.strip()
                if ':' not in line:
                    continue
                key, value = line.split(':', 1)
                key = normalize_lookup_key(key)
                value = value.strip(' ;,')
                if key and value and key not in parsed:
                    parsed[key] = value
            return parsed

        def first_non_empty(*values, default='-'):
            for value in values:
                if value not in [None, '']:
                    return value
            return default

        def parse_number(value, default=0):
            if value in [None, '', '-']:
                return default
            try:
                cleaned = str(value).replace(',', '').strip()
                cleaned = cleaned.replace('\u20B9', '').replace('Rs.', '').replace('Rs', '').strip()
                if cleaned == '':
                    return default
                return float(cleaned)
            except (TypeError, ValueError):
                return default

        extra_info = parse_extra_info(loan.remarks or '')

        def get_extra(*keys, default='-'):
            for key in keys:
                if not key:
                    continue
                value = extra_info.get(normalize_lookup_key(key))
                if value not in [None, '']:
                    return value
            return default
        # Best-effort mapping to LoanApplication + Applicant for complete details
        loan_app = find_related_loan_application(loan)

        applicant = loan_app.applicant if loan_app else None
        assignment_context = extract_assignment_context(loan, loan_app)
        follow_up_pending = _is_follow_up_pending(loan, loan_app)
        status_display = FOLLOW_UP_PENDING_LABEL if follow_up_pending else _ui_status_label(loan.get_status_display())
        status_key = 'follow_up_pending' if follow_up_pending else loan.status

        disbursed_at_dt = getattr(loan_app, 'disbursed_at', None) if loan_app else None
        if not disbursed_at_dt and loan.status == 'disbursed':
            disbursed_at_dt = getattr(loan, 'updated_at', None)

        if loan_app and getattr(loan_app, 'disbursement_amount', None) is not None:
            disbursement_amount_value = float(loan_app.disbursement_amount or 0)
        elif loan.status == 'disbursed' and loan.loan_amount is not None:
            disbursement_amount_value = float(loan.loan_amount or 0)
        else:
            disbursement_amount_value = 0

        disbursed_by_name = '-'
        if loan_app and getattr(loan_app, 'disbursed_by', None):
            disbursed_by_name = loan_app.disbursed_by.get_full_name() or loan_app.disbursed_by.username or '-'

        disbursement_notes = get_extra(
            'disbursement notes',
            'disbursement note',
            'disbursement remark',
            'disbursement remarks',
            default=''
        )
        if not disbursement_notes and loan_app and loan_app.approval_notes:
            disbursement_notes = str(loan_app.approval_notes).strip()
        if not disbursement_notes:
            disbursement_notes = '-'

        # Build references
        references = []
        for idx in [1, 2]:
            ref_name = get_extra(f'reference {idx} name', f'ref{idx}_name', default='')
            ref_mobile = get_extra(f'reference {idx} mobile', f'ref{idx}_mobile', default='')
            ref_address = get_extra(f'reference {idx} address', f'ref{idx}_address', default='')
            if ref_name or ref_mobile or ref_address:
                references.append({
                    'name': ref_name or '-',
                    'mobile_number': ref_mobile or '-',
                    'address': ref_address or '-',
                })

        # Existing loans (Section 3)
        existing_loans = []
        loan_index_pattern = re.compile(r'^(?:existing\s+)?loan\s+(\d+)\s+')
        dynamic_loan_indexes = sorted({
            int(match.group(1))
            for key in extra_info.keys()
            for match in [loan_index_pattern.match(str(key or ''))]
            if match
        })
        loan_indexes = dynamic_loan_indexes if dynamic_loan_indexes else [1, 2, 3]

        for idx in loan_indexes:
            bank_name = get_extra(
                f'existing loan {idx} bank/finance name',
                f'existing loan {idx} bank finance name',
                f'existing loan {idx} bank name',
                f'existing loan {idx} bank',
                f'loan {idx} bank/finance name',
                f'loan {idx} bank',
                f'loan{idx}_bank',
                default=''
            )
            amount_taken = get_extra(
                f'existing loan {idx} amount taken',
                f'loan {idx} amount taken',
                f'loan{idx}_amount_taken',
                default=''
            )
            emi_left = get_extra(
                f'existing loan {idx} emi left',
                f'loan {idx} emi left',
                f'loan{idx}_emi_left',
                default=''
            )
            amount_left = get_extra(
                f'existing loan {idx} amount left',
                f'loan {idx} amount left',
                f'loan{idx}_amount_left',
                default=''
            )
            tenure = get_extra(
                f'existing loan {idx} years/months',
                f'existing loan {idx} duration',
                f'existing loan {idx} tenure',
                f'loan {idx} years/months',
                f'loan {idx} duration',
                f'loan{idx}_duration',
                default=''
            )
            emi_amount = get_extra(
                f'existing loan {idx} emi amount',
                f'loan {idx} emi amount',
                f'loan{idx}_emi_over',
                default=''
            )
            any_bounce = get_extra(
                f'existing loan {idx} any bounce',
                f'existing loan {idx} bounce',
                f'existing loan {idx} emi cross',
                f'loan {idx} any bounce',
                f'loan{idx}_bounce',
                default=''
            )
            cleared = get_extra(
                f'existing loan {idx} cleared',
                f'loan {idx} cleared',
                f'loan{idx}_cleared',
                default=''
            )

            if any([bank_name, amount_taken, emi_left, amount_left, tenure, emi_amount, any_bounce, cleared]):
                existing_loans.append({
                    'bank_name': bank_name or '-',
                    'amount_taken': parse_number(amount_taken, 0),
                    'emi_left': emi_left or '-',
                    'amount_left': parse_number(amount_left, 0),
                    'tenure': tenure or '-',
                    'emi_amount': parse_number(emi_amount, 0),
                    'any_bounce': any_bounce or '-',
                    'cleared': str(cleared).strip().lower() in ['yes', 'true', '1'],
                })

        # Keep "Remarks / Suggestions" clean (manual input only).
        remarks_suggestions = get_extra(
            'remarks suggestions',
            'remarks_suggestions',
            'remark',
            default=''
        )
        raw_remarks = (loan.remarks or '').strip()
        if not remarks_suggestions and raw_remarks and raw_remarks.count(':') <= 1:
            remarks_suggestions = raw_remarks
        if not remarks_suggestions:
            remarks_suggestions = '-'

        # Processing-level remarks (approval/rejection/history) kept separately.
        processing_parts = []
        if loan_app:
            if loan_app.approval_notes:
                processing_parts.append(f"Approval Note: {loan_app.approval_notes}")
            if loan_app.rejection_reason:
                processing_parts.append(f"Rejection Reason: {loan_app.rejection_reason}")

            history_reasons = list(
                loan_app.status_history.exclude(reason__isnull=True)
                .exclude(reason__exact='')
                .values_list('reason', flat=True)[:10]
            )
            for reason in history_reasons:
                reason_text = str(reason).strip()
                if reason_text:
                    processing_parts.append(reason_text)

        dedup_processing = []
        seen_processing = set()
        for part in processing_parts:
            clean = (part or '').strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen_processing:
                continue
            seen_processing.add(key)
            dedup_processing.append(clean)

        # Build documents from both models
        documents = []
        seen_urls = set()

        if loan_app:
            for doc in loan_app.documents.all():
                url = doc.file.url if doc.file else ''
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                documents.append({
                    'document_type': doc.get_document_type_display() if hasattr(doc, 'get_document_type_display') else str(doc.document_type),
                    'file': url,
                })

        for doc in LoanDocument.objects.filter(loan=loan):
            url = doc.file.url if doc.file else ''
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            doc_type = doc.get_document_type_display() if hasattr(doc, 'get_document_type_display') else str(doc.document_type or 'Document')
            if str(doc.document_type).startswith('other'):
                suffix = str(doc.document_type).split('_')[-1]
                custom_name = get_extra(f'document {suffix}', default='')
                if not custom_name and str(doc.document_type) == 'other':
                    custom_name = get_extra('document 1', default='')
                if custom_name:
                    doc_type = custom_name
            documents.append({
                'document_type': doc_type,
                'file': url,
            })

        owner_role_map = {
            'admin': 'Admin',
            'subadmin': 'SubAdmin',
            'employee': 'Employee',
            'agent': 'Agent',
            'dsa': 'DSA',
        }
        owner_role = owner_role_map.get(getattr(loan.created_by, 'role', ''), 'System') if loan.created_by else 'System'
        owner_name = '-'
        if loan.created_by:
            owner_name = loan.created_by.get_full_name() or loan.created_by.username or '-'

        income_detail_parts = []
        for label, value in [
            ('Company', get_extra('company name', default='')),
            ('Official Email', get_extra('official email id', default='')),
            ('Designation', get_extra('designation', default='')),
            ('Previous Company', get_extra('previous company', default='')),
            ('Salary', get_extra('salary', default='')),
            ('Gross Salary', get_extra('gross salary', default='')),
            ('Net Salary', get_extra('net salary', default='')),
            ('Business Type', get_extra('nature of business', default='')),
            ('Stock Value', get_extra('stock value', default='')),
            ('Employees', get_extra('number of employees', default='')),
            ('ITR', get_extra('itr details', default='')),
        ]:
            if value:
                income_detail_parts.append(f"{label}: {value}")

        declaration_raw = get_extra('declaration', default='on')
        if str(declaration_raw).strip().lower() in ['on', 'yes', 'true', '1']:
            declaration_text = 'I hereby declare that the above information given by me is true and correct.'
        else:
            declaration_text = str(declaration_raw)

        details = {
            'id': loan.id,
            'user_id': loan.user_id,
            'status': status_display,
            'status_display': status_display,
            'status_key': status_key,
            'status_raw': loan.status,
            'follow_up_pending': follow_up_pending,
            'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else '',
            'updated_at': loan.updated_at.strftime('%Y-%m-%d %H:%M') if loan.updated_at else '',
            'created_by_role': owner_role,
            'created_by_name': owner_name,
            'created_by_display': f"{owner_role} - {owner_name}" if owner_name != '-' else owner_role,
            'assigned_employee_name': loan.assigned_employee.get_full_name() if loan.assigned_employee else '-',
            'assigned_agent_name': loan.assigned_agent.name if loan.assigned_agent else '-',
            'assigned_by_name': assignment_context.get('assigned_by_name') or '-',
            'assigned_by_display': assignment_context.get('assigned_by_display') or '-',
            'assigned_subadmin_name': assignment_context.get('assigned_by_name') if assignment_context.get('role') == 'subadmin' else '-',

            # Section 1
            'full_name': loan.full_name,
            'mobile_number': loan.mobile_number,
            'alternate_mobile': get_extra('alternate mobile', 'alternate_mobile', default='-'),
            'email': loan.email or '-',
            'father_name': get_extra('father name', "father's name", 'father s name', 'fathers name', 'fathers_name', default='-'),
            'mother_name': get_extra('mother name', "mother's name", 'mother s name', 'mothers name', 'mothers_name', default='-'),
            'date_of_birth': get_extra('date of birth', 'dob', default='-'),
            'gender': get_extra('gender', default='-'),
            'marital_status': get_extra('marital status', default='-'),
            'permanent_address': loan.permanent_address or '-',
            'current_address': loan.current_address or '-',
            'city': loan.city or '-',
            'state': loan.state or '-',
            'pin_code': loan.pin_code or '-',

            'permanent_address_line1': first_non_empty(loan.permanent_address, get_extra('permanent address', default='-'), default='-'),
            'permanent_landmark': get_extra('permanent landmark', default='-'),
            'permanent_city': first_non_empty(get_extra('permanent city', default=''), loan.city, default='-'),
            'permanent_pincode': first_non_empty(get_extra('permanent pin', default=''), loan.pin_code, default='-'),

            'present_address_line1': first_non_empty(loan.current_address, get_extra('present address', default='-'), default='-'),
            'present_landmark': get_extra('present landmark', default='-'),
            'present_city': first_non_empty(get_extra('present city', default=''), loan.city, default='-'),
            'present_pincode': first_non_empty(get_extra('present pin', default=''), loan.pin_code, default='-'),

            # Section 2
            'occupation': get_extra('occupation', default='-'),
            'employment_date': get_extra('date of joining', default='-'),
            'years_of_experience': get_extra('experience (years)', 'year of experience', default='-'),
            'additional_income': get_extra('additional income', 'extra income', default='-'),
            'extra_income_details': " | ".join(income_detail_parts) if income_detail_parts else get_extra('extra income details', default='-'),

            # Section 3
            'existing_loans': existing_loans,

            # Section 4
            'loan_type': first_non_empty(
                loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else loan.loan_type,
                get_extra('service required', 'loan type', default='-'),
                default='-'
            ),
            'loan_type_key': loan.loan_type,
            'loan_amount': float(loan.loan_amount or 0),
            'tenure_months': loan.tenure_months or '-',
            'interest_rate': float(loan.interest_rate or 0) if loan.interest_rate is not None else '-',
            'emi': float(loan.emi or 0) if loan.emi is not None else '-',
            'loan_purpose': first_non_empty(loan.loan_purpose, get_extra('loan purpose', 'purpose', default='-'), default='-'),
            'charges_applicable': get_extra(
                'charges/fee',
                'charges or fee',
                'any charges or fee',
                'any charges or fees',
                'charges applicable',
                default='No charges'
            ),

            # Section 5
            'references': references,

            # Section 6
            'cibil_score': get_extra('cibil score', default='-'),
            'aadhar_number': get_extra('aadhar number', 'aadhar', 'aadhaar', default='-'),
            'pan_number': get_extra('pan number', 'pan', default='-'),
            'bank_name': loan.bank_name or get_extra('bank name', default='-'),
            'bank_account_number': loan.bank_account_number or '-',
            'bank_ifsc_code': loan.bank_ifsc_code or '-',
            'bank_type': loan.bank_type or '-',
            'bank_type_key': loan.bank_type or '',
            'account_number': first_non_empty(
                loan.bank_account_number,
                get_extra('account number', 'bank account no', default='-'),
                default='-'
            ),
            'ifsc_code': first_non_empty(loan.bank_ifsc_code, get_extra('ifsc code', 'ifsc', default='-'), default='-'),
            'sm_name': first_non_empty(
                getattr(loan, 'sm_name', None),
                getattr(loan_app, 'sm_name', None) if loan_app else None,
                default='-'
            ),
            'sm_phone_number': first_non_empty(
                getattr(loan, 'sm_phone_number', None),
                getattr(loan_app, 'sm_phone_number', None) if loan_app else None,
                default='-'
            ),
            'sm_email': first_non_empty(
                getattr(loan, 'sm_email', None),
                getattr(loan_app, 'sm_email', None) if loan_app else None,
                default='-'
            ),
            'is_sm_signed': bool(
                getattr(loan, 'is_sm_signed', False) or (getattr(loan_app, 'is_sm_signed', False) if loan_app else False)
            ),
            'sm_signed_at': first_non_empty(
                getattr(loan, 'sm_signed_at', None).strftime('%Y-%m-%d %H:%M') if getattr(loan, 'sm_signed_at', None) else '',
                getattr(loan_app, 'sm_signed_at', None).strftime('%Y-%m-%d %H:%M') if loan_app and getattr(loan_app, 'sm_signed_at', None) else '',
                default='-'
            ),
            'disbursement_amount': disbursement_amount_value,
            'disbursed_at': disbursed_at_dt.strftime('%Y-%m-%d %H:%M') if disbursed_at_dt else '-',
            'disbursed_by_name': disbursed_by_name,
            'disbursement_notes': disbursement_notes,
            'remarks': remarks_suggestions,
            'remarks_raw': raw_remarks,
            'processing_remarks': "\n".join(dedup_processing)[:3000] if dedup_processing else '-',

            'has_co_applicant': bool(loan.has_co_applicant),
            'co_applicant_name': loan.co_applicant_name or '-',
            'co_applicant_phone': loan.co_applicant_phone or '-',
            'co_applicant_email': loan.co_applicant_email or '-',
            'has_guarantor': bool(loan.has_guarantor),
            'guarantor_name': loan.guarantor_name or '-',
            'guarantor_phone': loan.guarantor_phone or '-',
            'guarantor_email': loan.guarantor_email or '-',

            # Section 7
            'documents': documents,
            'declaration': declaration_text,
        }

        # If LoanApplication/Applicant exists, enrich from it where Loan is empty
        if applicant:
            details['full_name'] = first_non_empty(applicant.full_name, details['full_name'])
            details['email'] = first_non_empty(applicant.email, details['email'])
            details['mobile_number'] = first_non_empty(applicant.mobile, details['mobile_number'])
            details['gender'] = first_non_empty(
                applicant.get_gender_display() if hasattr(applicant, 'get_gender_display') else getattr(applicant, 'gender', None),
                details['gender']
            )
            details['city'] = first_non_empty(applicant.city, details['city'])
            details['state'] = first_non_empty(applicant.state, details['state'])
            details['pin_code'] = first_non_empty(applicant.pin_code, details['pin_code'])
            details['loan_type'] = first_non_empty(
                applicant.get_loan_type_display() if hasattr(applicant, 'get_loan_type_display') else applicant.loan_type,
                details['loan_type']
            )
            details['loan_amount'] = float(first_non_empty(applicant.loan_amount, details['loan_amount'], default=0) or 0)
            details['tenure_months'] = first_non_empty(applicant.tenure_months, details['tenure_months'])
            details['interest_rate'] = first_non_empty(getattr(applicant, 'interest_rate', None), details['interest_rate'])
            details['emi'] = first_non_empty(getattr(applicant, 'emi', None), details['emi'])
            details['loan_purpose'] = first_non_empty(applicant.loan_purpose, details['loan_purpose'], get_extra('loan purpose', default='-'))
            details['bank_name'] = first_non_empty(applicant.bank_name, details['bank_name'])
            details['account_number'] = first_non_empty(applicant.account_number, details['account_number'])
            details['ifsc_code'] = first_non_empty(applicant.ifsc_code, details['ifsc_code'])
            details['bank_type'] = first_non_empty(applicant.bank_type, details['bank_type'])
            details['bank_type_key'] = first_non_empty(applicant.bank_type, details.get('bank_type_key'))
            details['cibil_score'] = first_non_empty(getattr(applicant, 'cibil_score', None), details['cibil_score'])
            details['aadhar_number'] = first_non_empty(getattr(applicant, 'aadhar_number', None), details['aadhar_number'])
            details['pan_number'] = first_non_empty(getattr(applicant, 'pan_number', None), details['pan_number'])
            details['permanent_address_line1'] = first_non_empty(
                getattr(applicant, 'permanent_address', None),
                details['permanent_address_line1']
            )
            details['present_address_line1'] = first_non_empty(
                getattr(applicant, 'current_address', None),
                details['present_address_line1']
            )

        if details['assigned_employee_name'] == '-' and assignment_context.get('assigned_employee_name'):
            details['assigned_employee_name'] = assignment_context.get('assigned_employee_name')

        # Build an "all captured fields" list to show every available detail in modal.
        full_application_details = []
        seen_labels = set()

        def add_full_row(label, value):
            if isinstance(value, (list, dict)):
                return
            text = str(value or '').strip()
            if text in ['', '-']:
                return
            key = normalize_lookup_key(label)
            if key in seen_labels:
                return
            seen_labels.add(key)
            full_application_details.append({
                'label': label,
                'value': text,
            })

        ordered_rows = [
            ('Applicant Name', details.get('full_name')),
            ('Mobile Number', details.get('mobile_number')),
            ('Alternate Mobile', details.get('alternate_mobile')),
            ('Email', details.get('email')),
            ('Father Name', details.get('father_name')),
            ('Mother Name', details.get('mother_name')),
            ('Date Of Birth', details.get('date_of_birth')),
            ('Gender', details.get('gender')),
            ('Marital Status', details.get('marital_status')),
            ('Permanent Address', details.get('permanent_address_line1')),
            ('Present Address', details.get('present_address_line1')),
            ('City', details.get('city')),
            ('State', details.get('state')),
            ('PIN Code', details.get('pin_code')),
            ('Occupation', details.get('occupation')),
            ('Date Of Joining', details.get('employment_date')),
            ('Experience (Years)', details.get('years_of_experience')),
            ('Additional Income', details.get('additional_income')),
            ('Extra Income Details', details.get('extra_income_details')),
            ('Loan Type', details.get('loan_type')),
            ('Loan Amount', details.get('loan_amount')),
            ('Tenure Months', details.get('tenure_months')),
            ('Loan Purpose', details.get('loan_purpose')),
            ('Charges Applicable', details.get('charges_applicable')),
            ('CIBIL Score', details.get('cibil_score')),
            ('Aadhar Number', details.get('aadhar_number')),
            ('PAN Number', details.get('pan_number')),
            ('Bank Name', details.get('bank_name')),
            ('Account Number', details.get('account_number')),
            ('IFSC Code', details.get('ifsc_code')),
            ('Bank Type', details.get('bank_type')),
            ('SM Name', details.get('sm_name')),
            ('SM Phone Number', details.get('sm_phone_number')),
            ('SM Email', details.get('sm_email')),
            ('SM Sign', 'Signed' if details.get('is_sm_signed') else 'Pending'),
            ('Disbursed Amount', details.get('disbursement_amount')),
            ('Disbursed At', details.get('disbursed_at')),
            ('Disbursed By', details.get('disbursed_by_name')),
            ('Disbursement Notes', details.get('disbursement_notes')),
            ('Remarks', details.get('remarks')),
            ('Processing Remarks', details.get('processing_remarks')),
        ]
        for label, value in ordered_rows:
            add_full_row(label, value)

        for key, value in extra_info.items():
            if key.startswith('assigned by'):
                continue
            add_full_row(humanize_key(key), value)

        details['full_application_details'] = full_application_details

        return JsonResponse({'success': True, 'data': details})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_loan_reject(request, loan_id):
    """
    API Endpoint: Reject a loan application with reason
    Updates status to 'rejected' and records the rejection reason
    """
    try:
        loan = get_object_or_404(Loan, id=loan_id)
        data = json.loads(request.body)

        rejection_reason = str(data.get('rejection_reason', '')).strip() or 'No reason provided'
        now = timezone.now()
        previous_status = loan.status

        # Update loan status
        loan.status = 'rejected'
        if hasattr(loan, 'rejection_reason'):
            loan.rejection_reason = rejection_reason
        if hasattr(loan, 'is_sm_signed'):
            loan.is_sm_signed = False
        if hasattr(loan, 'sm_signed_at'):
            loan.sm_signed_at = None
        loan.save()

        # Keep related LoanApplication in sync when available.
        loan_app = find_related_loan_application(loan)
        if loan_app:
            app_update_fields = []
            if loan_app.status != 'Rejected':
                loan_app.status = 'Rejected'
                app_update_fields.append('status')
            if loan_app.rejected_by_id != request.user.id:
                loan_app.rejected_by = request.user
                app_update_fields.append('rejected_by')
            if loan_app.rejected_at != now:
                loan_app.rejected_at = now
                app_update_fields.append('rejected_at')
            if loan_app.rejection_reason != rejection_reason:
                loan_app.rejection_reason = rejection_reason
                app_update_fields.append('rejection_reason')
            if loan_app.is_sm_signed:
                loan_app.is_sm_signed = False
                app_update_fields.append('is_sm_signed')
            if loan_app.sm_signed_at is not None:
                loan_app.sm_signed_at = None
                app_update_fields.append('sm_signed_at')

            note_line = f"Rejection Reason: {rejection_reason}".strip()
            existing_notes = str(loan_app.approval_notes or '').strip()
            if note_line and note_line not in existing_notes:
                loan_app.approval_notes = f"{existing_notes}\n{note_line}".strip() if existing_notes else note_line
                app_update_fields.append('approval_notes')

            if app_update_fields:
                loan_app.save(update_fields=app_update_fields + ['updated_at'])
        
        # Record status history
        try:
            LoanStatusHistory.objects.create(
                loan=loan,
                old_status='waiting' if previous_status == 'waiting' else 'follow_up',
                new_status='rejected',
                changed_by=request.user,
                reason=rejection_reason
            )
        except:
            pass
        
        return JsonResponse({
            'success': True,
            'message': 'Loan rejected successfully',
            'new_status': _ui_status_label(loan.get_status_display())
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_loan_disburse(request, loan_id):
    """
    API Endpoint: Mark a loan as disbursed
    Updates status to 'disbursed' and records disbursement details
    Triggers real-time dashboard updates
    """
    try:
        loan = get_object_or_404(Loan, id=loan_id)
        data = json.loads(request.body)
        
        disbursement_notes = data.get('disbursement_notes', '')
        now = timezone.now()
        
        # Update loan status
        loan.status = 'disbursed'
        if hasattr(loan, 'disbursed_at'):
            loan.disbursed_at = now
        if disbursement_notes and hasattr(loan, 'disbursement_notes'):
            loan.disbursement_notes = disbursement_notes
        loan.save()

        # Keep related LoanApplication in sync when available.
        loan_app = find_related_loan_application(loan)
        if loan_app:
            app_update_fields = []
            if loan_app.status != 'Disbursed':
                loan_app.status = 'Disbursed'
                app_update_fields.append('status')
            if loan_app.disbursed_by_id != request.user.id:
                loan_app.disbursed_by = request.user
                app_update_fields.append('disbursed_by')
            if loan_app.disbursed_at != now:
                loan_app.disbursed_at = now
                app_update_fields.append('disbursed_at')
            if loan.loan_amount is not None and loan_app.disbursement_amount != loan.loan_amount:
                loan_app.disbursement_amount = loan.loan_amount
                app_update_fields.append('disbursement_amount')
            if disbursement_notes:
                note_line = f"Disbursement Note: {disbursement_notes}".strip()
                existing_notes = str(loan_app.approval_notes or '').strip()
                if note_line and note_line not in existing_notes:
                    loan_app.approval_notes = f"{existing_notes}\n{note_line}".strip() if existing_notes else note_line
                    app_update_fields.append('approval_notes')
            if app_update_fields:
                loan_app.save(update_fields=app_update_fields + ['updated_at'])
        
        # Record status history
        try:
            LoanStatusHistory.objects.create(
                loan=loan,
                old_status='approved',
                new_status='disbursed',
                changed_by=request.user,
                reason=f'Disbursed. Notes: {disbursement_notes}'
            )
        except:
            pass
        
        return JsonResponse({
            'success': True,
            'message': 'Loan disbursed successfully',
            'new_status': _ui_status_label(loan.get_status_display()),
            'disbursed_at': now.isoformat()
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_update_disbursed_details(request, loan_id):
    """
    API Endpoint: Update details for an already disbursed loan.
    Supports SM sign fields, remarks, processing notes, and disbursement date/amount.
    """
    try:
        loan = get_object_or_404(Loan, id=loan_id)
        loan_app = find_related_loan_application(loan)
        payload = json.loads(request.body or '{}')

        is_disbursed_context = (loan.status == 'disbursed') or (loan_app and loan_app.status == 'Disbursed')

        def parse_decimal_value(raw_value):
            if raw_value in [None, '', '-']:
                return None
            try:
                return Decimal(str(raw_value).strip())
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError('Invalid disbursement amount')

        def parse_date_value(raw_value):
            if raw_value in [None, '', '-']:
                return None
            try:
                return datetime.strptime(str(raw_value).strip(), '%Y-%m-%d').date()
            except ValueError:
                raise ValueError('Invalid disbursed date. Use YYYY-MM-DD')

        def parse_datetime_value(raw_value):
            if raw_value in [None, '', '-']:
                return None
            clean = str(raw_value).strip()
            for fmt in ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S']:
                try:
                    parsed = datetime.strptime(clean, fmt)
                    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
                except ValueError:
                    continue
            raise ValueError('Invalid signed datetime')

        def normalize_remarks_label(raw_label):
            cleaned = re.sub(r'[^a-z0-9]+', ' ', str(raw_label or '').lower())
            return ' '.join(cleaned.split()).strip()

        def upsert_remarks_line(existing_text, preferred_label, raw_value, aliases=None):
            """
            Update/insert a single "Label: Value" line in loan.remarks, preserving the rest.
            When raw_value is empty, remove the line (if it exists).
            """
            base = (existing_text or '').replace('\r\n', '\n').replace('\r', '\n')
            lines = base.split('\n') if base else []

            idx_by_key = {}
            for idx, line in enumerate(lines):
                if ':' not in line:
                    continue
                left, _ = line.split(':', 1)
                key = normalize_remarks_label(left)
                if key and key not in idx_by_key:
                    idx_by_key[key] = idx

            candidates = [preferred_label] + (aliases or [])
            candidate_keys = [normalize_remarks_label(label) for label in candidates if normalize_remarks_label(label)]

            existing_idx = None
            existing_label = None
            for key in candidate_keys:
                if key in idx_by_key:
                    existing_idx = idx_by_key[key]
                    existing_label = (lines[existing_idx].split(':', 1)[0] or '').strip() or preferred_label
                    break

            value_text = str(raw_value or '').strip()
            if value_text == '':
                if existing_idx is not None:
                    lines.pop(existing_idx)
                cleaned_lines = [ln for ln in lines if str(ln).strip() != '']
                return "\n".join(cleaned_lines).strip() or None

            label_to_use = existing_label or preferred_label
            new_line = f"{label_to_use}: {value_text}"
            if existing_idx is not None:
                lines[existing_idx] = new_line
            else:
                lines.append(new_line)

            cleaned_lines = [ln for ln in lines if str(ln).strip() != '']
            return "\n".join(cleaned_lines).strip() or None

        def normalize_loan_type(raw_value):
            if raw_value in [None, '', '-']:
                return None
            raw = str(raw_value).strip().lower()
            if not raw:
                return None
            mapping = {
                'personal loan': 'personal',
                'personal': 'personal',
                'lap': 'lap',
                'loan against property': 'lap',
                'home loan': 'home',
                'home': 'home',
                'business loan': 'business',
                'business': 'business',
                'auto loan': 'car',
                'auto': 'car',
                'education loan': 'education',
                'education': 'education',
                'car loan': 'car',
                'car': 'car',
                'security loan': 'other',
                'security': 'other',
                'other': 'other',
            }
            normalized = mapping.get(raw, raw)
            allowed = {choice[0] for choice in Loan.LOAN_TYPE_CHOICES}
            if normalized not in allowed:
                raise ValueError('Invalid loan type')
            return normalized

        def parse_int_value(raw_value, label):
            if raw_value in [None, '', '-']:
                return None
            try:
                return int(str(raw_value).strip())
            except (TypeError, ValueError):
                raise ValueError(f'Invalid {label}')

        def normalize_bank_type(raw_value):
            if raw_value in [None, '', '-']:
                return None
            raw = str(raw_value).strip().lower()
            mapping = {
                'private': 'private',
                'government': 'government',
                'cooperative': 'cooperative',
                'nbfc': 'nbfc',
            }
            normalized = mapping.get(raw, raw)
            allowed = {choice[0] for choice in Loan.BANK_TYPE_CHOICES}
            if normalized not in allowed:
                raise ValueError('Invalid bank type')
            return normalized

        def normalize_bool(raw_value):
            if raw_value in [None, '']:
                return None
            if isinstance(raw_value, bool):
                return raw_value
            text = str(raw_value).strip().lower()
            if text in ['true', '1', 'yes', 'on']:
                return True
            if text in ['false', '0', 'no', 'off']:
                return False
            return bool(raw_value)

        disbursement_amount = parse_decimal_value(payload.get('disbursement_amount'))
        if disbursement_amount is not None and disbursement_amount < 0:
            raise ValueError('Disbursement amount cannot be negative')
        disbursed_date = parse_date_value(payload.get('disbursed_date'))
        sm_signed_at = parse_datetime_value(payload.get('sm_signed_at'))
        loan_amount = parse_decimal_value(payload.get('loan_amount'))
        loan_type = normalize_loan_type(payload.get('loan_type'))
        tenure_months = parse_int_value(payload.get('tenure_months'), 'tenure months')
        interest_rate = parse_decimal_value(payload.get('interest_rate'))
        bank_type = normalize_bank_type(payload.get('bank_type'))
        has_co_applicant = normalize_bool(payload.get('has_co_applicant'))
        has_guarantor = normalize_bool(payload.get('has_guarantor'))

        loan_update_fields = []
        if is_disbursed_context and loan.status != 'disbursed':
            loan.status = 'disbursed'
            loan_update_fields.append('status')

        for field_name in ['sm_name', 'sm_phone_number', 'sm_email']:
            if field_name in payload:
                new_value = str(payload.get(field_name) or '').strip() or None
                if getattr(loan, field_name) != new_value:
                    setattr(loan, field_name, new_value)
                    loan_update_fields.append(field_name)

        for field_name in ['full_name', 'mobile_number', 'email', 'city', 'state', 'pin_code']:
            if field_name in payload:
                raw_value = str(payload.get(field_name) or '').strip()
                if not raw_value and field_name in ['email', 'state', 'pin_code']:
                    raw_value = None
                if raw_value and getattr(loan, field_name) != raw_value:
                    setattr(loan, field_name, raw_value)
                    loan_update_fields.append(field_name)
                elif raw_value is None and getattr(loan, field_name) is not None and field_name in ['email', 'state', 'pin_code']:
                    setattr(loan, field_name, None)
                    loan_update_fields.append(field_name)

        for field_name in ['permanent_address', 'current_address', 'loan_purpose', 'bank_name', 'bank_account_number', 'bank_ifsc_code']:
            if field_name in payload:
                raw_value = str(payload.get(field_name) or '').strip()
                if raw_value == '':
                    raw_value = None
                if getattr(loan, field_name) != raw_value:
                    setattr(loan, field_name, raw_value)
                    loan_update_fields.append(field_name)

        recalc_emi = False

        if loan_type and loan.loan_type != loan_type:
            loan.loan_type = loan_type
            loan_update_fields.append('loan_type')

        if loan_amount is not None and loan.loan_amount != loan_amount:
            loan.loan_amount = loan_amount
            loan_update_fields.append('loan_amount')
            recalc_emi = True

        if tenure_months is not None and loan.tenure_months != tenure_months:
            loan.tenure_months = tenure_months
            loan_update_fields.append('tenure_months')
            recalc_emi = True

        if interest_rate is not None and loan.interest_rate != interest_rate:
            loan.interest_rate = interest_rate
            loan_update_fields.append('interest_rate')
            recalc_emi = True

        if bank_type and loan.bank_type != bank_type:
            loan.bank_type = bank_type
            loan_update_fields.append('bank_type')

        if has_co_applicant is not None and loan.has_co_applicant != has_co_applicant:
            loan.has_co_applicant = has_co_applicant
            loan_update_fields.append('has_co_applicant')
            if not has_co_applicant:
                if loan.co_applicant_name:
                    loan.co_applicant_name = None
                    loan_update_fields.append('co_applicant_name')
                if loan.co_applicant_phone:
                    loan.co_applicant_phone = None
                    loan_update_fields.append('co_applicant_phone')
                if loan.co_applicant_email:
                    loan.co_applicant_email = None
                    loan_update_fields.append('co_applicant_email')

        if has_guarantor is not None and loan.has_guarantor != has_guarantor:
            loan.has_guarantor = has_guarantor
            loan_update_fields.append('has_guarantor')
            if not has_guarantor:
                if loan.guarantor_name:
                    loan.guarantor_name = None
                    loan_update_fields.append('guarantor_name')
                if loan.guarantor_phone:
                    loan.guarantor_phone = None
                    loan_update_fields.append('guarantor_phone')
                if loan.guarantor_email:
                    loan.guarantor_email = None
                    loan_update_fields.append('guarantor_email')

        for field_name in ['co_applicant_name', 'co_applicant_phone', 'co_applicant_email', 'guarantor_name', 'guarantor_phone', 'guarantor_email']:
            if field_name in payload:
                raw_value = str(payload.get(field_name) or '').strip()
                if raw_value == '':
                    raw_value = None
                if getattr(loan, field_name) != raw_value:
                    setattr(loan, field_name, raw_value)
                    loan_update_fields.append(field_name)

        if 'is_sm_signed' in payload:
            is_sm_signed = bool(payload.get('is_sm_signed'))
            if bool(loan.is_sm_signed) != is_sm_signed:
                loan.is_sm_signed = is_sm_signed
                loan_update_fields.append('is_sm_signed')
            if is_sm_signed:
                effective_signed_at = sm_signed_at or loan.sm_signed_at or timezone.now()
                if loan.sm_signed_at != effective_signed_at:
                    loan.sm_signed_at = effective_signed_at
                    loan_update_fields.append('sm_signed_at')
            elif loan.sm_signed_at is not None:
                loan.sm_signed_at = None
                loan_update_fields.append('sm_signed_at')
        elif sm_signed_at is not None and loan.sm_signed_at != sm_signed_at:
            loan.sm_signed_at = sm_signed_at
            loan_update_fields.append('sm_signed_at')

        if 'remarks_full' in payload:
            remarks_full_value = str(payload.get('remarks_full') or '').replace('\r\n', '\n').replace('\r', '\n').strip() or None
            if loan.remarks != remarks_full_value:
                loan.remarks = remarks_full_value
                loan_update_fields.append('remarks')
        elif 'remarks' in payload:
            remarks_suggestions_value = str(payload.get('remarks') or '')
            updated_remarks = upsert_remarks_line(
                loan.remarks,
                'Remarks/Suggestions',
                remarks_suggestions_value,
                aliases=['Remarks / Suggestions', 'Remarks Suggestions', 'Remark', 'Remarks']
            )
            if loan.remarks != updated_remarks:
                loan.remarks = updated_remarks
                loan_update_fields.append('remarks')

        if recalc_emi and 'emi' not in loan_update_fields:
            loan_update_fields.append('emi')

        if loan_update_fields:
            loan.save(update_fields=list(dict.fromkeys(loan_update_fields + ['updated_at'])))

        app_update_fields = []
        app_disbursed_at = None
        if loan_app:
            if is_disbursed_context:
                if loan_app.status != 'Disbursed':
                    loan_app.status = 'Disbursed'
                    app_update_fields.append('status')

                if loan_app.disbursed_by_id != request.user.id:
                    loan_app.disbursed_by = request.user
                    app_update_fields.append('disbursed_by')

                if disbursed_date:
                    base_dt = loan_app.disbursed_at or timezone.now()
                    app_disbursed_at = base_dt.replace(year=disbursed_date.year, month=disbursed_date.month, day=disbursed_date.day)
                    if loan_app.disbursed_at != app_disbursed_at:
                        loan_app.disbursed_at = app_disbursed_at
                        app_update_fields.append('disbursed_at')

                if disbursement_amount is not None and loan_app.disbursement_amount != disbursement_amount:
                    loan_app.disbursement_amount = disbursement_amount
                    app_update_fields.append('disbursement_amount')

            for field_name in ['sm_name', 'sm_phone_number', 'sm_email']:
                if field_name in payload:
                    new_value = str(payload.get(field_name) or '').strip() or None
                    if getattr(loan_app, field_name) != new_value:
                        setattr(loan_app, field_name, new_value)
                        app_update_fields.append(field_name)

            applicant = loan_app.applicant if getattr(loan_app, 'applicant', None) else None
            applicant_update_fields = []
            applicant_recalc_emi = False
            if applicant:
                if 'full_name' in payload:
                    new_value = str(payload.get('full_name') or '').strip()
                    if new_value and applicant.full_name != new_value:
                        applicant.full_name = new_value
                        applicant_update_fields.append('full_name')
                if 'mobile_number' in payload:
                    new_value = str(payload.get('mobile_number') or '').strip()
                    if new_value and applicant.mobile != new_value:
                        applicant.mobile = new_value
                        applicant_update_fields.append('mobile')
                if 'email' in payload:
                    new_value = str(payload.get('email') or '').strip()
                    if new_value and applicant.email != new_value:
                        applicant.email = new_value
                        applicant_update_fields.append('email')
                if 'city' in payload:
                    new_value = str(payload.get('city') or '').strip()
                    if new_value and applicant.city != new_value:
                        applicant.city = new_value
                        applicant_update_fields.append('city')
                if 'state' in payload:
                    new_value = str(payload.get('state') or '').strip()
                    if new_value and applicant.state != new_value:
                        applicant.state = new_value
                        applicant_update_fields.append('state')
                if 'pin_code' in payload:
                    new_value = str(payload.get('pin_code') or '').strip()
                    if new_value and applicant.pin_code != new_value:
                        applicant.pin_code = new_value
                        applicant_update_fields.append('pin_code')
                if loan_type and applicant.loan_type != loan_type:
                    applicant.loan_type = loan_type
                    applicant_update_fields.append('loan_type')
                if loan_amount is not None and applicant.loan_amount != loan_amount:
                    applicant.loan_amount = loan_amount
                    applicant_update_fields.append('loan_amount')
                    applicant_recalc_emi = True
                if tenure_months is not None and applicant.tenure_months != tenure_months:
                    applicant.tenure_months = tenure_months
                    applicant_update_fields.append('tenure_months')
                    applicant_recalc_emi = True
                if interest_rate is not None and applicant.interest_rate != interest_rate:
                    applicant.interest_rate = interest_rate
                    applicant_update_fields.append('interest_rate')
                    applicant_recalc_emi = True
                if 'loan_purpose' in payload:
                    new_value = str(payload.get('loan_purpose') or '').strip()
                    if new_value and applicant.loan_purpose != new_value:
                        applicant.loan_purpose = new_value
                        applicant_update_fields.append('loan_purpose')
                if 'bank_name' in payload:
                    new_value = str(payload.get('bank_name') or '').strip()
                    if new_value and applicant.bank_name != new_value:
                        applicant.bank_name = new_value
                        applicant_update_fields.append('bank_name')
                if 'bank_account_number' in payload:
                    new_value = str(payload.get('bank_account_number') or '').strip()
                    if new_value != '' and applicant.account_number != new_value:
                        applicant.account_number = new_value
                        applicant_update_fields.append('account_number')
                if 'bank_ifsc_code' in payload:
                    new_value = str(payload.get('bank_ifsc_code') or '').strip()
                    if new_value != '' and applicant.ifsc_code != new_value:
                        applicant.ifsc_code = new_value
                        applicant_update_fields.append('ifsc_code')
                if bank_type and applicant.bank_type != bank_type:
                    applicant.bank_type = bank_type
                    applicant_update_fields.append('bank_type')
                if applicant_recalc_emi and 'emi' not in applicant_update_fields:
                    applicant_update_fields.append('emi')

                if applicant_update_fields:
                    applicant.save(update_fields=list(dict.fromkeys(applicant_update_fields + ['updated_at'])))

            if 'is_sm_signed' in payload:
                app_signed = bool(payload.get('is_sm_signed'))
                if bool(loan_app.is_sm_signed) != app_signed:
                    loan_app.is_sm_signed = app_signed
                    app_update_fields.append('is_sm_signed')
                if app_signed:
                    app_signed_at = sm_signed_at or loan_app.sm_signed_at or timezone.now()
                    if loan_app.sm_signed_at != app_signed_at:
                        loan_app.sm_signed_at = app_signed_at
                        app_update_fields.append('sm_signed_at')
                elif loan_app.sm_signed_at is not None:
                    loan_app.sm_signed_at = None
                    app_update_fields.append('sm_signed_at')
            elif sm_signed_at is not None and loan_app.sm_signed_at != sm_signed_at:
                loan_app.sm_signed_at = sm_signed_at
                app_update_fields.append('sm_signed_at')

            if 'processing_remarks' in payload:
                notes_value = str(payload.get('processing_remarks') or '').strip() or None
                if loan_app.approval_notes != notes_value:
                    loan_app.approval_notes = notes_value
                    app_update_fields.append('approval_notes')

            if app_update_fields:
                loan_app.save(update_fields=list(dict.fromkeys(app_update_fields + ['updated_at'])))

        # Optional audit trail entry.
        if is_disbursed_context:
            try:
                LoanStatusHistory.objects.create(
                    loan=loan,
                    old_status='disbursed',
                    new_status='disbursed',
                    changed_by=request.user,
                    reason='Admin updated disbursed details'
                )
            except Exception:
                pass

        return JsonResponse({
            'success': True,
            'message': 'Disbursed details updated successfully' if is_disbursed_context else 'Loan details updated successfully',
            'data': {
                'status': _ui_status_label(loan_app.status if loan_app else loan.get_status_display()) if not is_disbursed_context else 'Disbursed',
                'disbursement_amount': (
                    float((loan_app.disbursement_amount if loan_app and loan_app.disbursement_amount is not None else (disbursement_amount or 0)))
                    if is_disbursed_context else 0
                ),
                'disbursed_at': (
                    (
                        (loan_app.disbursed_at.strftime('%Y-%m-%d %H:%M') if loan_app and loan_app.disbursed_at else '')
                        or (app_disbursed_at.strftime('%Y-%m-%d %H:%M') if app_disbursed_at else '')
                    ) if is_disbursed_context else ''
                ),
                'is_sm_signed': bool(loan.is_sm_signed) or bool(loan_app.is_sm_signed if loan_app else False),
                'sm_signed_at': (
                    (loan.sm_signed_at or (loan_app.sm_signed_at if loan_app else None)).strftime('%Y-%m-%d %H:%M')
                    if (loan.sm_signed_at or (loan_app.sm_signed_at if loan_app else None)) else ''
                ),
                'remarks': loan.remarks or '',
                'processing_remarks': loan_app.approval_notes if loan_app else '',
            }
        })

    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid request body'}, status=400)
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_http_methods(['DELETE'])
def api_loan_delete(request, loan_id):
    """
    API Endpoint: Delete a loan
    Soft delete or hard delete based on configuration
    """
    try:
        loan = get_object_or_404(Loan, id=loan_id)
        
        # Check if loan can be deleted (not disbursed)
        if loan.status == 'disbursed':
            return JsonResponse({
                'success': False,
                'error': 'Cannot delete a disbursed loan'
            }, status=400)
        
        loan_id_val = loan.id
        loan_name = loan.full_name

        # Hard delete if no soft-delete fields exist (current Loan model),
        # otherwise apply soft delete and verify that fields were updated.
        soft_fields = []
        if hasattr(loan, 'is_deleted'):
            loan.is_deleted = True
            soft_fields.append('is_deleted')
        if hasattr(loan, 'deleted_at'):
            loan.deleted_at = timezone.now()
            soft_fields.append('deleted_at')

        if soft_fields:
            if hasattr(loan, 'updated_at'):
                soft_fields.append('updated_at')
            loan.save(update_fields=soft_fields)
        else:
            loan.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Loan for {loan_name} deleted successfully',
            'deleted_id': loan_id_val
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required(login_url='admin_login')
@admin_required
@require_POST
def api_loan_forclose(request, loan_id):
    """
    API Endpoint: Mark a loan as ForClose
    Updates status to 'forclose' and records forclose details
    Triggers real-time dashboard updates
    """
    try:
        loan = get_object_or_404(Loan, id=loan_id)
        data = json.loads(request.body)
        
        forclose_notes = data.get('forclose_notes', '')
        
        # Update loan status
        loan.status = 'forclose'
        if hasattr(loan, 'forclose_at'):
            loan.forclose_at = timezone.now()
        if forclose_notes and hasattr(loan, 'forclose_notes'):
            loan.forclose_notes = forclose_notes
        loan.save()
        
        # Record status history
        try:
            LoanStatusHistory.objects.create(
                loan=loan,
                old_status=getattr(loan, 'prev_status', 'waiting'),
                new_status='forclose',
                changed_by=request.user,
                reason=f'Marked as ForClose. Notes: {forclose_notes}'
            )
        except:
            pass
        
        return JsonResponse({
            'success': True,
            'message': 'Loan marked as ForClose successfully',
            'new_status': 'For Close',
            'forclose_at': timezone.now().isoformat()
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)




