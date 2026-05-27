"""
Helpers for "Document Pending -> Pending Document Cleared" workflow detection.

An item is considered "Pending Document Cleared" when all required buckets are present:
- PAN
- Aadhaar
- Bank proof (statement / passbook / cancel cheque)
"""

from __future__ import annotations

from typing import Iterable, Optional, Set

from .models import ApplicantDocument, LoanDocument

UPDATED_DOCUMENT_STATUS_KEY = "updated_document"
UPDATED_DOCUMENT_LABEL = "Pending Document Cleared"
UPDATED_DOCUMENT_MARKER = "Updated Document by"
DOCUMENT_PENDING_MARKER = "Document Pending by"

_REQUIRED_KEYS = {"pan", "aadhaar", "bank"}


def _normalize_text(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("-", " ").replace("_", " ")
    return " ".join(text.split())


def _doc_key_from_text(raw_text: object) -> Optional[str]:
    text = _normalize_text(raw_text)
    if not text:
        return None

    if "pan" in text:
        return "pan"
    if "aadhaar" in text or "aadhar" in text:
        return "aadhaar"

    bank_tokens = [
        "bank statement",
        "statement",
        "passbook",
        "cancel cheque",
        "cancel check",
        "cheque",
        "check",
    ]
    if any(token in text for token in bank_tokens):
        return "bank"
    return None


def updated_document_keys_from_types(document_types: Iterable[object]) -> Set[str]:
    keys: Set[str] = set()
    for raw in document_types or []:
        key = _doc_key_from_text(raw)
        if key:
            keys.add(key)
    return keys


def has_all_updated_document_keys(keys: Iterable[str]) -> bool:
    return _REQUIRED_KEYS.issubset(set(keys or []))


def has_updated_document_marker(*raw_values: object) -> bool:
    return latest_document_stage_marker(*raw_values) == "updated"


def latest_document_stage_marker(*raw_values: object) -> Optional[str]:
    """
    Returns the latest explicit workflow marker found in note lines:
    - "updated" when last marker is Updated Document by ...
    - "pending" when last marker is Document Pending by ...
    """
    stage = None
    updated_marker = UPDATED_DOCUMENT_MARKER.lower()
    pending_marker = DOCUMENT_PENDING_MARKER.lower()
    for raw in raw_values:
        for line in str(raw or "").splitlines():
            normalized = line.strip().lower()
            if not normalized:
                continue
            if updated_marker in normalized:
                stage = "updated"
            if pending_marker in normalized:
                stage = "pending"
    return stage


def _loan_document_types(loan_obj) -> list[str]:
    if not loan_obj:
        return []
    try:
        return list(
            LoanDocument.objects.filter(loan=loan_obj).values_list("document_type", flat=True)
        )
    except Exception:
        return []


def _application_document_types(loan_app) -> list[str]:
    if not loan_app:
        return []
    try:
        return list(
            ApplicantDocument.objects.filter(loan_application=loan_app).values_list(
                "document_type", flat=True
            )
        )
    except Exception:
        return []


def loan_has_updated_documents(loan_obj, related_app=None) -> bool:
    if not loan_obj:
        return False

    stage = latest_document_stage_marker(getattr(loan_obj, "remarks", ""))
    if stage == "pending":
        return False
    if stage == "updated":
        return True

    if related_app is None:
        try:
            from .loan_sync import find_related_loan_application

            related_app = find_related_loan_application(loan_obj)
        except Exception:
            related_app = None

    if related_app is not None:
        app_stage = latest_document_stage_marker(
            getattr(related_app, "approval_notes", ""),
            getattr(related_app, "rejection_reason", ""),
        )
        if app_stage == "pending":
            return False
        if app_stage == "updated":
            return True
    return False


def application_has_updated_documents(loan_app, related_loan=None) -> bool:
    if not loan_app:
        return False

    stage = latest_document_stage_marker(
        getattr(loan_app, "approval_notes", ""),
        getattr(loan_app, "rejection_reason", ""),
    )
    if stage == "pending":
        return False
    if stage == "updated":
        return True

    if related_loan is None:
        try:
            from .loan_sync import find_related_loan

            related_loan = find_related_loan(loan_app)
        except Exception:
            related_loan = None

    if related_loan is not None:
        loan_stage = latest_document_stage_marker(getattr(related_loan, "remarks", ""))
        if loan_stage == "pending":
            return False
        if loan_stage == "updated":
            return True
    return False


def waiting_status_to_updated_document(status_key: object, has_updated_documents: bool) -> str:
    key = _normalize_text(status_key)
    waiting_aliases = {"waiting", "waiting for processing", "in processing", "processing"}
    if has_updated_documents and key in waiting_aliases:
        return UPDATED_DOCUMENT_STATUS_KEY
    return str(status_key or "")
