"""
Loan Management API Endpoints
Handles all loan-related API requests for admin panel including details, reject, disburse, delete
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.utils import timezone
import json
import re

from .models import Loan, LoanStatusHistory, LoanApplication, LoanDocument, ApplicantDocument
from .decorators import admin_required
from .loan_sync import extract_assignment_context, find_related_loan_application


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

        def parse_extra_info(raw_text):
            parsed = {}
            if not raw_text:
                return parsed
            text = str(raw_text).replace('\r', '\n')
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
                'IFSC Code',
                'IFSC',
                'Bank Type',
                'Remarks/Suggestions',
                'Remarks Suggestions',
                'Remark',
                'Declaration',
                'Assigned By Admin',
                'Assigned By SubAdmin',
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
        for idx in [1, 2, 3]:
            bank_name = get_extra(
                f'loan {idx} bank/finance name',
                f'loan {idx} bank',
                f'loan{idx}_bank',
                default=''
            )
            amount_taken = get_extra(
                f'loan {idx} amount taken',
                f'loan{idx}_amount_taken',
                default=''
            )
            emi_left = get_extra(
                f'loan {idx} emi left',
                f'loan{idx}_emi_left',
                default=''
            )
            amount_left = get_extra(
                f'loan {idx} amount left',
                f'loan{idx}_amount_left',
                default=''
            )
            tenure = get_extra(
                f'loan {idx} years/months',
                f'loan {idx} duration',
                f'loan{idx}_duration',
                default=''
            )
            emi_amount = get_extra(
                f'loan {idx} emi amount',
                f'loan{idx}_emi_over',
                default=''
            )
            any_bounce = get_extra(
                f'loan {idx} any bounce',
                f'loan{idx}_bounce',
                default=''
            )
            cleared = get_extra(
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
            'status': loan.get_status_display(),
            'status_key': loan.status,
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
            'loan_type': loan.get_loan_type_display() if hasattr(loan, 'get_loan_type_display') else loan.loan_type,
            'loan_amount': float(loan.loan_amount or 0),
            'tenure_months': loan.tenure_months or '-',
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
            'bank_type': loan.bank_type or '-',
            'account_number': first_non_empty(loan.bank_account_number, get_extra('account number', default='-'), default='-'),
            'ifsc_code': first_non_empty(loan.bank_ifsc_code, get_extra('ifsc code', 'ifsc', default='-'), default='-'),
            'remarks': remarks_suggestions,
            'processing_remarks': "\n".join(dedup_processing)[:3000] if dedup_processing else '-',

            # Section 7
            'documents': documents,
            'declaration': declaration_text,
        }

        # If LoanApplication/Applicant exists, enrich from it where Loan is empty
        if applicant:
            details['email'] = first_non_empty(applicant.email, details['email'])
            details['mobile_number'] = first_non_empty(applicant.mobile, details['mobile_number'])
            details['loan_type'] = first_non_empty(
                applicant.get_loan_type_display() if hasattr(applicant, 'get_loan_type_display') else applicant.loan_type,
                details['loan_type']
            )
            details['loan_amount'] = float(first_non_empty(applicant.loan_amount, details['loan_amount'], default=0) or 0)
            details['tenure_months'] = first_non_empty(applicant.tenure_months, details['tenure_months'])
            details['loan_purpose'] = first_non_empty(applicant.loan_purpose, details['loan_purpose'], get_extra('loan purpose', default='-'))
            details['bank_name'] = first_non_empty(applicant.bank_name, details['bank_name'])
            details['account_number'] = first_non_empty(applicant.account_number, details['account_number'])
            details['ifsc_code'] = first_non_empty(applicant.ifsc_code, details['ifsc_code'])
            details['bank_type'] = first_non_empty(applicant.bank_type, details['bank_type'])
            details['cibil_score'] = first_non_empty(getattr(applicant, 'cibil_score', None), details['cibil_score'])
            details['aadhar_number'] = first_non_empty(getattr(applicant, 'aadhar_number', None), details['aadhar_number'])
            details['pan_number'] = first_non_empty(getattr(applicant, 'pan_number', None), details['pan_number'])

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
        
        rejection_reason = data.get('rejection_reason', 'No reason provided')
        
        # Update loan status
        loan.status = 'rejected'
        if hasattr(loan, 'rejection_reason'):
            loan.rejection_reason = rejection_reason
        loan.save()
        
        # Record status history
        try:
            LoanStatusHistory.objects.create(
                loan=loan,
                old_status='waiting' if loan.status == 'waiting' else 'follow_up',
                new_status='rejected',
                changed_by=request.user,
                reason=rejection_reason
            )
        except:
            pass
        
        return JsonResponse({
            'success': True,
            'message': 'Loan rejected successfully',
            'new_status': loan.get_status_display()
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
        
        # Update loan status
        loan.status = 'disbursed'
        if hasattr(loan, 'disbursed_at'):
            loan.disbursed_at = timezone.now()
        if disbursement_notes and hasattr(loan, 'disbursement_notes'):
            loan.disbursement_notes = disbursement_notes
        loan.save()
        
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
            'new_status': loan.get_status_display(),
            'disbursed_at': timezone.now().isoformat()
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




