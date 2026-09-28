"""Deterministic approval fingerprints for candidates and mail drafts.

An approval hash is an integrity check, not a cryptographic signature.  It binds
the reviewed record to the exact identity/contact or delivery fields which were
present when the record was approved.  Sending code must recompute the hash and
fail closed if an Approved draft was subsequently edited.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unicodedata
from datetime import datetime, timezone
from typing import Literal

RecordType = Literal["candidate", "draft"]

LEGACY_APPROVAL_HASH_PREFIX = "sha256-v1:"
APPROVAL_HASH_PREFIX = "sha256-v2:"

# Keep these lists explicit.  Operational delivery fields such as Message ID,
# Sent At, and Error must not invalidate the human approval after an attempt.
CANDIDATE_APPROVAL_FIELDS = (
    "Campaign ID",
    "Target ID",
    "Candidate ID",
    "Revision",
    "Schema Version",
    "Speaker Type",
    "Full Name",
    "Organization",
    "Title",
    "Expertise",
    "Topic Fit",
    "Preferred Salutation",
    "Email",
    "Contact Type",
    "Email Source URL",
    "Phone",
    "Profile URL",
    "Discovery Source URL",
    "Role Temporal Status",
    "Role As Of",
    "Identity Evidence ID",
    "Role Evidence ID",
    "Email Evidence Level",
    "Email Evidence ID",
    "Mailbox Status",
    "Preferred Route Type",
    "Preferred Route URL",
    "Notes",
    "Last Checked",
)

# Frozen v1 fields are retained solely so existing ledgers can be inspected and
# deliberately re-approved.  A v1 fingerprint is never sufficient for live
# delivery because it did not cover the reviewer identity, approval time, or
# sender identity.
_CANDIDATE_APPROVAL_FIELDS_V1 = CANDIDATE_APPROVAL_FIELDS
_DRAFT_APPROVAL_FIELDS_V1 = (
    "Campaign ID",
    "Draft ID",
    "Candidate ID",
    "Revision",
    "Schema Version",
    "To Email",
    "To Name",
    "Contact Type",
    "Subject",
    "Body Text",
    "Profile URL",
)

DRAFT_APPROVAL_FIELDS = (
    *_DRAFT_APPROVAL_FIELDS_V1,
    "Candidate Approval Hash",
    "Campaign Policy Hash",
    "Sender Email",
    "Sender Name",
    "Reply-To",
)

APPROVAL_AUDIT_FIELDS = (
    "Approved By",
    "Approved At",
)


class ApprovalIntegrityError(ValueError):
    """Raised when an Approved row lacks its matching approval fingerprint."""


def utc_now_iso() -> str:
    """Return a stable, second-resolution UTC timestamp for approval audit fields."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def infer_record_type(row: dict[str, object]) -> RecordType:
    """Infer which approval schema applies to *row*."""

    if str(row.get("Draft ID", "") or "").strip():
        return "draft"
    if "Draft Status" in row or "To Email" in row:
        return "draft"
    return "candidate"


def _canonical_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def approval_payload(
    row: dict[str, object],
    *,
    record_type: RecordType | None = None,
    version: int = 2,
) -> dict[str, object]:
    """Return the canonical, serializable payload covered by an approval hash."""

    resolved_type = record_type or infer_record_type(row)
    if version not in {1, 2}:
        raise ValueError(f"Unsupported approval hash version: {version}")
    if version == 1:
        fields = (
            _DRAFT_APPROVAL_FIELDS_V1 if resolved_type == "draft" else _CANDIDATE_APPROVAL_FIELDS_V1
        )
    else:
        fields = DRAFT_APPROVAL_FIELDS if resolved_type == "draft" else CANDIDATE_APPROVAL_FIELDS
        fields = (*fields, *APPROVAL_AUDIT_FIELDS)
    return {
        "approval_schema": version,
        "record_type": resolved_type,
        "fields": [[field, _canonical_text(row.get(field, ""))] for field in fields],
    }


def compute_approval_hash(
    row: dict[str, object],
    *,
    record_type: RecordType | None = None,
    version: int = 2,
) -> str:
    """Compute the versioned SHA-256 fingerprint for a reviewable row."""

    serialized = json.dumps(
        approval_payload(row, record_type=record_type, version=version),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    prefix = APPROVAL_HASH_PREFIX if version == 2 else LEGACY_APPROVAL_HASH_PREFIX
    return prefix + hashlib.sha256(serialized).hexdigest()


def approval_is_valid(
    row: dict[str, object],
    *,
    record_type: RecordType | None = None,
    allow_legacy: bool = True,
) -> bool:
    """Return whether approval audit data exists and its hash matches the row.

    Legacy v1 hashes remain readable by default so old ledgers can be reviewed
    and migrated.  Live delivery must pass ``allow_legacy=False``.
    """

    actual = _canonical_text(row.get("Approval Hash", "")).strip()
    approved_at = _canonical_text(row.get("Approved At", "")).strip()
    approved_by = _canonical_text(row.get("Approved By", "")).strip()
    if not actual or not approved_at or not approved_by:
        return False
    if actual.startswith(APPROVAL_HASH_PREFIX):
        version = 2
    elif allow_legacy and actual.startswith(LEGACY_APPROVAL_HASH_PREFIX):
        version = 1
    else:
        return False
    expected = compute_approval_hash(row, record_type=record_type, version=version)
    return hmac.compare_digest(actual, expected)


def require_valid_approval(
    row: dict[str, object],
    *,
    record_type: RecordType | None = None,
    allow_legacy: bool = True,
) -> None:
    """Fail closed unless *row* is Approved and its fingerprint still matches."""

    resolved_type = record_type or infer_record_type(row)
    status_field = "Draft Status" if resolved_type == "draft" else "Review Status"
    if _canonical_text(row.get(status_field, "")).strip() != "Approved":
        raise ApprovalIntegrityError(f"{status_field} must be Approved.")
    if not approval_is_valid(
        row,
        record_type=resolved_type,
        allow_legacy=allow_legacy,
    ):
        identifier_field = "Draft ID" if resolved_type == "draft" else "Candidate ID"
        identifier = _canonical_text(row.get(identifier_field, "")).strip() or "<unknown>"
        raise ApprovalIntegrityError(
            f"Approved {resolved_type} {identifier} has a missing, stale, or unsupported "
            "Approval Hash or approval audit metadata. "
            "Return it to Draft and approve the current content again."
        )


def approve_row(
    row: dict[str, object],
    approved_by: str,
    *,
    record_type: RecordType | None = None,
    approved_at: str | None = None,
) -> dict[str, object]:
    """Mark a row Approved and stamp its current fingerprint and audit identity."""

    approver = _canonical_text(approved_by).strip()
    if not approver:
        raise ValueError("Approved By must identify the human reviewer.")
    resolved_type = record_type or infer_record_type(row)
    status_field = "Draft Status" if resolved_type == "draft" else "Review Status"
    row[status_field] = "Approved"
    row["Approved By"] = approver
    row["Approved At"] = _canonical_text(approved_at).strip() if approved_at else utc_now_iso()
    row["Approval Hash"] = compute_approval_hash(row, record_type=resolved_type)
    return row


def clear_approval(
    row: dict[str, object], *, status: str = "Draft", record_type: RecordType | None = None
) -> dict[str, object]:
    """Return a row to an unapproved state and remove approval audit data."""

    resolved_type = record_type or infer_record_type(row)
    status_field = "Draft Status" if resolved_type == "draft" else "Review Status"
    row[status_field] = status
    row["Approval Hash"] = ""
    row["Approved At"] = ""
    row["Approved By"] = ""
    return row


__all__ = [
    "APPROVAL_HASH_PREFIX",
    "LEGACY_APPROVAL_HASH_PREFIX",
    "ApprovalIntegrityError",
    "approval_is_valid",
    "approval_payload",
    "approve_row",
    "clear_approval",
    "compute_approval_hash",
    "infer_record_type",
    "require_valid_approval",
]
