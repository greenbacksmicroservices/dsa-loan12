"""Utilities for separating user remarks from packed loan detail text."""

import re


KNOWN_DETAIL_LABELS = [
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
    'Company Name',
    'Official Email ID',
    'Designation',
    'Previous Company',
    'Company Address',
    'Company Landmark',
    'Salary',
    'Gross Salary',
    'Net Salary',
    'Business Address',
    'Business Landmark',
    'Business PIN',
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
    'CIBIL Score',
    'Aadhar Number',
    'Aadhaar Number',
    'PAN Number',
    'PAN',
    'Bank Name',
    'Account Number',
    'Bank Account No',
    'IFSC Code',
    'IFSC',
    'Bank Type',
    'Reference 1 Name',
    'Reference 1 Mobile',
    'Reference 1 Address',
    'Reference 2 Name',
    'Reference 2 Mobile',
    'Reference 2 Address',
    'Channel Partner Name',
    'Lead Receive Channel Partner Name',
    'Employee Name',
    'Leader Name',
    'Lead Source',
    'Lead Description',
    'Remarks/Suggestions',
    'Remarks / Suggestions',
    'Remarks Suggestions',
    'Remark',
    'Remarks',
    'Bank Remark',
    'Approval Notes',
    'Rejection Reason',
    'Disbursement Remark',
    'Disbursement Remarks',
    'Declaration',
    'Assigned By Admin',
    'Assigned By SubAdmin',
    'Assigned By Partner',
    'Assigned By',
]

for idx in range(1, 11):
    KNOWN_DETAIL_LABELS.extend([
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
        f'Document {idx}',
    ])

APPLICATION_DUMP_MARKERS = [
    'alternate mobile',
    'father name',
    'mother name',
    'date of birth',
    'marital status',
    'permanent address',
    'present address',
    'occupation',
    'aadhar number',
    'aadhaar number',
    'pan number',
    'reference 1 name',
    'reference 2 name',
    'loan 1 bank',
    'document 1',
]

MANUAL_REMARK_KEYS = [
    'remarks suggestions',
    'remarks/suggestions',
    'remarks / suggestions',
    'remark',
    'remarks',
]

PROCESSING_REMARK_KEYS = [
    'bank remark',
    'approval notes',
    'rejection reason',
    'disbursement remark',
    'disbursement remarks',
]


def normalize_detail_key(value):
    text = str(value or '').strip().lower()
    text = text.replace('_', ' ').replace('-', ' ').replace('/', ' ')
    return ' '.join(text.split())


def _label_matches(raw_text):
    scan_text = re.sub(r'\s+', ' ', str(raw_text or '').replace('\r', '\n')).strip()
    if not scan_text:
        return []

    candidates = {}
    for label in KNOWN_DETAIL_LABELS:
        pattern = re.compile(r'(?i)(?<![A-Za-z0-9])' + re.escape(label) + r'\s*:')
        for match in pattern.finditer(scan_text):
            current = candidates.get(match.start())
            if not current or match.end() > current[0]:
                candidates[match.start()] = (match.end(), label)

    return sorted(
        [(start, end, label) for start, (end, label) in candidates.items()],
        key=lambda item: item[0],
    )


def parse_colon_details(raw_text):
    details = {}
    text = str(raw_text or '')

    matches = _label_matches(text)
    scan_text = re.sub(r'\s+', ' ', text.replace('\r', '\n')).strip()
    for idx, (_, end, label) in enumerate(matches):
        next_start = matches[idx + 1][0] if idx + 1 < len(matches) else len(scan_text)
        value = scan_text[end:next_start].strip(' ;,')
        key = normalize_detail_key(label)
        if key and value:
            details[key] = value

    for raw_line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = raw_line.strip()
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        clean_key = normalize_detail_key(key)
        clean_value = str(value or '').strip(' ;,')
        if clean_key and clean_value:
            details[clean_key] = clean_value

    return details


def detail_value(raw_text, *labels, default=''):
    parsed = parse_colon_details(raw_text)
    for label in labels:
        value = parsed.get(normalize_detail_key(label))
        if value not in [None, '']:
            return value
    return default


def looks_like_application_dump(raw_text):
    payload = normalize_detail_key(raw_text)
    if not payload:
        return False
    marker_hits = sum(1 for marker in APPLICATION_DUMP_MARKERS if marker in payload)
    parsed = parse_colon_details(raw_text)
    return marker_hits >= 3 or (marker_hits >= 2 and len(parsed) >= 3) or str(raw_text or '').count('\n') >= 8


def remove_document_pending_lines(raw_text, show_document_pending=False):
    text = str(raw_text or '').strip()
    if not text or show_document_pending:
        return text
    kept = [
        line.strip()
        for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        if line.strip() and 'document pending by' not in line.lower()
    ]
    return '\n'.join(kept).strip()


def extract_manual_remark(raw_text, parsed_details=None):
    details = parsed_details or parse_colon_details(raw_text)
    for key in MANUAL_REMARK_KEYS:
        value = details.get(normalize_detail_key(key))
        if value:
            return value

    plain = str(raw_text or '').strip()
    if plain and ':' not in plain:
        return plain
    return ''


def sanitize_display_remark(raw_text, default='-'):
    text = remove_document_pending_lines(raw_text)
    if not text:
        return default

    parsed = parse_colon_details(text)
    manual = extract_manual_remark(text, parsed)
    if looks_like_application_dump(text):
        if manual:
            return manual
        for key in PROCESSING_REMARK_KEYS:
            value = parsed.get(normalize_detail_key(key))
            if value:
                return value
        return default

    return manual or text or default


def upsert_manual_remark(existing_text, remark_value, preferred_label='Remarks/Suggestions'):
    new_value = str(remark_value or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    existing = str(existing_text or '').replace('\r\n', '\n').replace('\r', '\n').strip()

    if not existing:
        return f'{preferred_label}: {new_value}' if new_value else None

    if ':' not in existing and not looks_like_application_dump(existing):
        return new_value or None

    alias_keys = {normalize_detail_key(key) for key in MANUAL_REMARK_KEYS}
    kept_lines = []
    for raw_line in existing.split('\n'):
        line = raw_line.strip()
        if not line:
            continue
        if ':' in line:
            label, _ = line.split(':', 1)
            if normalize_detail_key(label) in alias_keys:
                continue
        kept_lines.append(line)

    if new_value:
        kept_lines.append(f'{preferred_label}: {new_value}')

    return '\n'.join(kept_lines).strip() or None
