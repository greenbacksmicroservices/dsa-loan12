from __future__ import annotations


def _clean(value):
    return (value or '').strip()


def _get(source, key, default=''):
    if hasattr(source, 'get'):
        return _clean(source.get(key, default))
    return _clean(default)


def _getlist(source, key):
    if hasattr(source, 'getlist'):
        values = source.getlist(key)
    else:
        raw = source.get(key, [])
        if isinstance(raw, list):
            values = raw
        elif raw:
            values = [raw]
        else:
            values = []
    return [_clean(v) for v in values if _clean(v)]


def collect_onboarding_payload_from_source(source):
    first_name = _get(source, 'first_name')
    last_name = _get(source, 'last_name')
    composed_name = " ".join([part for part in [first_name, last_name] if part]).strip()
    full_name = _get(source, 'onb_full_name') or _get(source, 'full_name') or _get(source, 'name') or composed_name
    mobile = _get(source, 'onb_mobile') or _get(source, 'phone')
    email = _get(source, 'onb_email') or _get(source, 'email')
    gender = _get(source, 'onb_gender') or _get(source, 'gender')
    base_address = _get(source, 'address')
    base_state = _get(source, 'state')
    base_city = _get(source, 'city')
    base_district = _get(source, 'district')
    base_pin = _get(source, 'pin_code') or _get(source, 'pin')

    perm_address = _get(source, 'onb_perm_address') or base_address
    perm_landmark = _get(source, 'onb_perm_landmark')
    perm_state = _get(source, 'onb_perm_state') or base_state
    perm_city = _get(source, 'onb_perm_city') or base_city
    perm_district = _get(source, 'onb_perm_district') or base_district
    perm_pin = _get(source, 'onb_perm_pin') or base_pin

    present_address_raw = _get(source, 'onb_present_address')
    present_landmark_raw = _get(source, 'onb_present_landmark')
    present_state_raw = _get(source, 'onb_present_state')
    present_city_raw = _get(source, 'onb_present_city')
    present_district_raw = _get(source, 'onb_present_district')
    present_pin_raw = _get(source, 'onb_present_pin')

    has_present_values = any([
        present_address_raw,
        present_landmark_raw,
        present_state_raw,
        present_city_raw,
        present_district_raw,
        present_pin_raw,
    ])
    same_as_permanent = bool(_get(source, 'onb_present_same')) or not has_present_values

    if same_as_permanent:
        present_address = present_address_raw or perm_address
        present_landmark = present_landmark_raw or perm_landmark
        present_state = present_state_raw or perm_state
        present_city = present_city_raw or perm_city
        present_district = present_district_raw or perm_district
        present_pin = present_pin_raw or perm_pin
    else:
        present_address = present_address_raw
        present_landmark = present_landmark_raw
        present_state = present_state_raw
        present_city = present_city_raw
        present_district = present_district_raw
        present_pin = present_pin_raw

    references = []
    ref_names = _getlist(source, 'ref_name')
    ref_phones = _getlist(source, 'ref_phone')
    ref_emails = _getlist(source, 'ref_email')
    ref_relations = _getlist(source, 'ref_relation')
    max_len = max(len(ref_names), len(ref_phones), len(ref_emails), len(ref_relations), 0)
    for idx in range(max_len):
        ref = {
            'name': ref_names[idx] if idx < len(ref_names) else '',
            'phone': ref_phones[idx] if idx < len(ref_phones) else '',
            'email': ref_emails[idx] if idx < len(ref_emails) else '',
            'relation': ref_relations[idx] if idx < len(ref_relations) else '',
        }
        if any(ref.values()):
            references.append(ref)

    payload = {
        'section1': {
            'full_name': full_name,
            'mobile': mobile,
            'alternate_mobile': _get(source, 'onb_alt_mobile'),
            'email': email,
            'father_name': _get(source, 'onb_father_name'),
            'mother_name': _get(source, 'onb_mother_name'),
            'date_of_birth': _get(source, 'onb_dob'),
            'gender': gender,
            'marital_status': _get(source, 'onb_marital_status'),
            'permanent_address': {
                'address': perm_address,
                'landmark': perm_landmark,
                'state': perm_state,
                'city': perm_city,
                'district': perm_district,
                'pin_code': perm_pin,
            },
            'present_address': {
                'same_as_permanent': same_as_permanent,
                'address': present_address,
                'landmark': present_landmark,
                'state': present_state,
                'city': present_city,
                'district': present_district,
                'pin_code': present_pin,
            },
        },
        'section2': {
            'occupation': _get(source, 'onb_occupation'),
            'date_of_joining': _get(source, 'onb_joining_date'),
            'years_experience': _get(source, 'onb_experience_years'),
            'additional_income': _get(source, 'onb_additional_income'),
            'extra_income_details': _get(source, 'onb_extra_income_details'),
        },
        'section3': {
            'existing_loan_details': _get(source, 'onb_existing_loans'),
        },
        'section4': {
            'service_required': _get(source, 'onb_service_required'),
            'loan_amount_required': _get(source, 'onb_loan_amount_required'),
            'loan_tenure_months': _get(source, 'onb_loan_tenure'),
            'charges_or_fee': _get(source, 'onb_charges_fee'),
            'loan_purpose': _get(source, 'onb_loan_purpose'),
        },
        'section5': {
            'references': references,
        },
        'section6': {
            'cibil_score': _get(source, 'onb_cibil'),
            'aadhar_number': _get(source, 'onb_aadhar'),
            'pan_number': _get(source, 'onb_pan'),
            'bank_name': _get(source, 'onb_bank_name'),
            'account_number': _get(source, 'onb_account_number'),
            'ifsc_code': _get(source, 'onb_ifsc'),
            'bank_type': _get(source, 'onb_bank_type'),
            'remarks': _get(source, 'onb_bank_remarks'),
            'declaration': bool(_get(source, 'onb_declaration')),
        },
    }

    return payload


def collect_onboarding_payload(request):
    return collect_onboarding_payload_from_source(request.POST)


def collect_onboarding_documents(request):
    types = request.POST.getlist('document_type')
    files = request.FILES.getlist('document_file')
    documents = []
    for idx, doc_file in enumerate(files):
        doc_type = types[idx] if idx < len(types) and types[idx] else 'other'
        documents.append((doc_type, doc_file))
    return documents
