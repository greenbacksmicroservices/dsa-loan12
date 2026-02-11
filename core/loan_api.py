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

from .models import Loan, LoanStatusHistory
from .decorators import admin_required


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
        
        # Fetch related applicant data if available
        from .models import Applicant, ApplicantDocument
        applicant = None
        try:
            applicant = Applicant.objects.filter(email=loan.email).first()
        except:
            pass
        
        # Parse extra details from remarks (agent/employee forms often store fields here)
        def parse_extra_info(raw_text):
            data = {}
            if not raw_text:
                return data
            for line in raw_text.splitlines():
                if ':' not in line:
                    continue
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                if not key:
                    continue
                data[key] = value
            return data

        extra_info = parse_extra_info(getattr(loan, 'remarks', '') or '')

        # Build comprehensive response
        dob_value = '-'
        if applicant and getattr(applicant, 'date_of_birth', None):
            dob_value = applicant.date_of_birth
        else:
            dob_value = extra_info.get('dob', '-') or '-'

        details = {
            'id': loan.id,
            'user_id': loan.user_id,
            'status': loan.get_status_display(),
            
            # Section 1: Name & Contact Details
            'full_name': loan.full_name,
            'mobile_number': loan.mobile_number,
            'alternate_mobile': getattr(applicant, 'alternate_mobile', '-') if applicant else '-',
            'email': loan.email,
            'father_name': getattr(applicant, 'father_name', '-') if applicant else '-',
            'mother_name': getattr(applicant, 'mother_name', '-') if applicant else '-',
            'date_of_birth': str(dob_value) if dob_value else '-',
            'gender': getattr(applicant, 'get_gender_display', lambda: '-')() if applicant and hasattr(applicant, 'gender') else extra_info.get('gender', '-'),
            'marital_status': getattr(applicant, 'marital_status', '-') if applicant else '-',
            'permanent_address': loan.permanent_address or '-',
            'current_address': loan.current_address or '-',
            'city': loan.city or '-',
            'state': loan.state or '-',
            'pin_code': loan.pin_code or '-',
            
            'permanent_address_line1': getattr(applicant, 'permanent_address_line1', None) if applicant else None,
            'permanent_address_line2': getattr(applicant, 'permanent_address_line2', None) if applicant else None,
            'permanent_landmark': getattr(applicant, 'permanent_landmark', None) if applicant else None,
            'permanent_city': getattr(applicant, 'permanent_city', None) if applicant else None,
            'permanent_pincode': getattr(applicant, 'permanent_pincode', None) if applicant else None,
            
            'present_address_line1': getattr(applicant, 'present_address_line1', None) if applicant else None,
            'present_address_line2': getattr(applicant, 'present_address_line2', None) if applicant else None,
            'present_landmark': getattr(applicant, 'present_landmark', None) if applicant else None,
            'present_city': getattr(applicant, 'present_city', None) if applicant else None,
            'present_pincode': getattr(applicant, 'present_pincode', None) if applicant else None,
            
            # Section 2: Occupation & Income
            'occupation': getattr(applicant, 'occupation', '-') if applicant else extra_info.get('employment type', '-'),
            'employment_date': str(getattr(applicant, 'employment_date', '-')) if applicant else '-',
            'years_of_experience': getattr(applicant, 'years_of_experience', '-') if applicant else '-',
            'additional_income': getattr(applicant, 'additional_income', '-') if applicant else extra_info.get('annual income', '-'),
            'extra_income_details': extra_info.get('extra income details', '-'),
            
            # Section 3: Existing Loans (list)
            'existing_loans': [],
            
            # Section 4: Loan Request
            'loan_type': loan.get_loan_type_display(),
            'loan_amount': float(loan.loan_amount or 0),
            'tenure_months': loan.tenure_months,
            'charges_applicable': getattr(applicant, 'charges_applicable', 'No charges') if applicant else 'No charges',
            
            # Section 5: References (list)
            'references': [],
            
            # Section 6: Financial & Bank Details
            'cibil_score': getattr(applicant, 'cibil_score', '-') if applicant else (extra_info.get('cibil score') or extra_info.get('credit score') or '-'),
            'aadhar_number': getattr(applicant, 'aadhar_number', '-') if applicant else (extra_info.get('aadhar') or extra_info.get('aadhaar') or '-'),
            'pan_number': getattr(applicant, 'pan_number', '-') if applicant else extra_info.get('pan', '-'),
            'bank_name': loan.bank_name or '-',
            'bank_type': loan.bank_type or '-',
            'account_number': getattr(applicant, 'account_number', '-') if applicant else (loan.bank_account_number or '-'),
            'ifsc_code': getattr(applicant, 'ifsc_code', '-') if applicant else (loan.bank_ifsc_code or '-'),
            'remarks': getattr(applicant, 'remarks', '-') if applicant else (loan.remarks or '-'),
            
            # Section 7: Documents (list)
            'documents': [],
        }

        # Fallbacks for address fields from Loan model (if applicant fields missing)
        if not details.get('permanent_address_line1'):
            details['permanent_address_line1'] = loan.permanent_address or '-'
        if not details.get('permanent_city'):
            details['permanent_city'] = loan.city or '-'
        if not details.get('permanent_pincode'):
            details['permanent_pincode'] = loan.pin_code or '-'

        if not details.get('present_address_line1'):
            details['present_address_line1'] = loan.current_address or '-'
        if not details.get('present_city'):
            details['present_city'] = loan.city or '-'
        if not details.get('present_pincode'):
            details['present_pincode'] = loan.pin_code or '-'
        
        # Get existing loans if applicant exists
        if applicant:
            try:
                existing_loans = getattr(applicant, 'existing_loans', [])
                if existing_loans:
                    details['existing_loans'] = existing_loans
            except:
                pass
            
            # Get references
            try:
                references = getattr(applicant, 'references', [])
                if references:
                    details['references'] = references
            except:
                pass
            
            # Get documents
            try:
                from .models import ApplicantDocument
                loan_application = getattr(applicant, 'loan_application', None)
                if loan_application:
                    docs = ApplicantDocument.objects.filter(loan_application=loan_application)
                    details['documents'] = [
                        {
                            'document_type': doc.get_document_type_display() if hasattr(doc, 'get_document_type_display') else doc.document_type,
                            'file': doc.file.url if hasattr(doc, 'file') and doc.file else ''
                        }
                        for doc in docs
                    ]
            except:
                pass
        
        # Get loan documents as well
        try:
            from .models import LoanDocument
            loan_docs = LoanDocument.objects.filter(loan=loan)
            for doc in loan_docs:
                details['documents'].append({
                    'document_type': doc.get_document_type_display() if hasattr(doc, 'get_document_type_display') else (doc.document_type or 'Document'),
                    'file': doc.file.url if hasattr(doc, 'file') and doc.file else ''
                })
        except:
            pass
        
        return JsonResponse({
            'success': True,
            'data': details
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


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
        
        # Soft delete by marking as deleted
        try:
            if hasattr(loan, 'is_deleted'):
                loan.is_deleted = True
            if hasattr(loan, 'deleted_at'):
                loan.deleted_at = timezone.now()
            loan.save()
        except:
            # Hard delete if soft delete not available
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
