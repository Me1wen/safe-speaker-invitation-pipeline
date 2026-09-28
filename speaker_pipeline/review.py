"""Safe merges from human review workbooks into canonical ledgers."""

from __future__ import annotations

from collections.abc import Iterable

from .approvals import approval_is_valid, approve_row, clear_approval
from .common import clean, clean_cell
from .schema import (
    CANDIDATE_COLUMNS,
    CANDIDATE_STATUSES,
    DRAFT_COLUMNS,
    DRAFT_STATUSES,
    SCHEMA_VERSION,
)


class ReviewMergeError(ValueError):
    """Raised when a review file is stale, ambiguous, or modifies protected state."""


def _revision(row: dict[str, object]) -> int:
    value = clean(row.get("Revision"))
    if not value:
        return 0
    try:
        revision = int(value)
    except ValueError as exc:
        raise ReviewMergeError(f"Invalid Revision value: {value}") from exc
    if revision < 0:
        raise ReviewMergeError("Revision cannot be negative.")
    return revision


def _normalized(row: dict[str, object], columns: list[str]) -> dict[str, str]:
    return {column: clean_cell(column, row.get(column, "")) for column in columns}


def _content_changed(current: dict[str, str], reviewed: dict[str, str], *, kind: str) -> bool:
    ignored = {
        "Review Status" if kind == "candidates" else "Draft Status",
        "Revision",
        "Approval Hash",
        "Approved At",
        "Approved By",
        "Schema Version",
    }
    if kind == "drafts":
        ignored.update({"Created At", "Last Attempt At", "Sent At", "Message ID", "Error"})
    columns = CANDIDATE_COLUMNS if kind == "candidates" else DRAFT_COLUMNS
    return any(
        current.get(field, "") != reviewed.get(field, "")
        for field in columns
        if field not in ignored
    )


def merge_review_rows(
    canonical_rows: Iterable[dict[str, object]],
    reviewed_rows: Iterable[dict[str, object]],
    *,
    kind: str,
    approver: str = "",
) -> list[dict[str, str]]:
    """Merge a review table without allowing stale or protected-row overwrites.

    Rows omitted from the workbook are preserved. New identifiers, duplicate
    identifiers, stale revisions, and edits to Sending/Sent drafts fail the
    complete import before a caller writes anything.
    """

    if kind not in {"candidates", "drafts"}:
        raise ValueError("kind must be candidates or drafts")
    columns = CANDIDATE_COLUMNS if kind == "candidates" else DRAFT_COLUMNS
    identifier_field = "Candidate ID" if kind == "candidates" else "Draft ID"
    status_field = "Review Status" if kind == "candidates" else "Draft Status"
    record_type = "candidate" if kind == "candidates" else "draft"

    canonical = [_normalized(row, columns) for row in canonical_rows]
    reviewed = [_normalized(row, columns) for row in reviewed_rows]
    by_id: dict[str, dict[str, str]] = {}
    for row in canonical:
        identifier = clean(row.get(identifier_field))
        if not identifier or identifier in by_id:
            raise ReviewMergeError(f"Canonical ledger has a missing/duplicate {identifier_field}.")
        by_id[identifier] = row

    reviewed_by_id: dict[str, dict[str, str]] = {}
    for row in reviewed:
        identifier = clean(row.get(identifier_field))
        if not identifier or identifier in reviewed_by_id:
            raise ReviewMergeError(f"Review table has a missing/duplicate {identifier_field}.")
        if identifier not in by_id:
            raise ReviewMergeError(
                f"Review table contains unknown {identifier_field}: {identifier}"
            )
        reviewed_by_id[identifier] = row

    output: list[dict[str, str]] = []
    for current in canonical:
        identifier = current[identifier_field]
        incoming = reviewed_by_id.get(identifier)
        if incoming is None:
            output.append(current)
            continue
        if _revision(incoming) != _revision(current):
            raise ReviewMergeError(
                f"Stale review row for {identifier}: revision {incoming.get('Revision') or '0'} "
                f"does not match canonical revision {current.get('Revision') or '0'}."
            )
        if kind == "drafts" and current[status_field] in {"Sending", "Sent"}:
            if incoming != current:
                raise ReviewMergeError(
                    f"Protected {current[status_field]} row cannot be changed: {identifier}"
                )
            output.append(current)
            continue

        current_status = current[status_field]
        incoming_status = incoming[status_field]
        allowed_statuses = CANDIDATE_STATUSES if kind == "candidates" else DRAFT_STATUSES
        if incoming_status not in allowed_statuses:
            raise ReviewMergeError(f"Invalid {status_field} for {identifier}: {incoming_status!r}.")
        if kind == "drafts" and incoming_status in {"Sending", "Sent"}:
            raise ReviewMergeError(
                f"Review workbooks cannot create {incoming_status} delivery state: {identifier}."
            )
        if kind == "drafts" and incoming_status == "Failed" and current_status != "Failed":
            raise ReviewMergeError(
                f"Review workbooks cannot create Failed delivery state: {identifier}."
            )
        changed = _content_changed(current, incoming, kind=kind)
        if current_status == "Approved" and incoming_status == "Approved":
            if changed or incoming.get("Approval Hash") != current.get("Approval Hash"):
                raise ReviewMergeError(
                    f"Approved content changed for {identifier}; return it to Draft first."
                )
            if not approval_is_valid(current, record_type=record_type):
                raise ReviewMergeError(f"Canonical approval is stale for {identifier}.")
            output.append(current)
            continue

        merged = dict(current)
        protected_operational = (
            {"Created At", "Last Attempt At", "Sent At", "Message ID", "Error"}
            if kind == "drafts"
            else set()
        )
        for field in columns:
            if (
                field
                not in {identifier_field, "Approval Hash", "Approved At", "Approved By"}
                | protected_operational
            ):
                merged[field] = incoming[field]
        if changed or incoming_status != current_status:
            merged["Revision"] = str(_revision(current) + 1)
        else:
            merged["Revision"] = str(_revision(current))
        merged["Schema Version"] = SCHEMA_VERSION

        if incoming_status == "Approved":
            approve_row(merged, approver, record_type=record_type)
        else:
            clear_approval(merged, status=incoming_status or "Draft", record_type=record_type)
        output.append(merged)
    return output


__all__ = ["ReviewMergeError", "merge_review_rows"]
