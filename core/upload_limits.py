"""Upload size guardrails shared across loan entry views."""

MAX_DOCUMENT_FILE_BYTES = 3 * 1024 * 1024  # 3 MB per file
MAX_DOCUMENT_BATCH_BYTES = 50 * 1024 * 1024  # 50 MB total per form submit


def _format_mb(size_in_bytes):
    return f"{(size_in_bytes / (1024 * 1024)):.2f} MB"


def validate_loan_document_batch(
    files,
    max_file_bytes=MAX_DOCUMENT_FILE_BYTES,
    max_total_bytes=MAX_DOCUMENT_BATCH_BYTES,
):
    """
    Validate per-file and total upload size for the add-loan flow.
    Returns: (is_valid: bool, message: str)
    """
    selected_files = [f for f in (files or []) if f]
    if not selected_files:
        return True, ""

    total_size = 0
    for upload in selected_files:
        file_size = int(getattr(upload, "size", 0) or 0)
        total_size += file_size
        if file_size > max_file_bytes:
            return (
                False,
                f"'{upload.name}' is {_format_mb(file_size)}. "
                f"Maximum allowed per file is {_format_mb(max_file_bytes)}.",
            )

    if total_size > max_total_bytes:
        return (
            False,
            f"Total selected document size is {_format_mb(total_size)}. "
            f"Maximum allowed per application is {_format_mb(max_total_bytes)}.",
        )

    return True, ""
