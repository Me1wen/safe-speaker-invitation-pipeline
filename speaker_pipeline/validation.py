"""Validation gates that must pass before a candidate can become a mail draft."""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse

from .common import EMAIL_RE, candidate_key, clean, today_iso
from .schema import CANDIDATE_STATUSES, QA_COLUMNS

APPROVED_REQUIRED_FIELDS = (
    "Candidate ID",
    "Speaker Type",
    "Full Name",
    "Organization",
    "Title",
    "Topic Fit",
    "Email",
    "Contact Type",
    "Email Source URL",
    "Profile URL",
)


def _valid_url(value: str) -> bool:
    parsed = urlparse(clean(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_candidates(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    run_date = today_iso()

    def add(severity: str, row_number: int, row: dict[str, str], field: str, issue: str) -> None:
        issues.append(
            {
                "Run Date": run_date,
                "Severity": severity,
                "Row Number": str(row_number),
                "Candidate ID": clean(row.get("Candidate ID")),
                "Full Name": clean(row.get("Full Name")),
                "Field": field,
                "Issue": issue,
            }
        )

    duplicate_rows: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for row_number, row in enumerate(rows, start=2):
        status = clean(row.get("Review Status"))
        if status not in CANDIDATE_STATUSES:
            add(
                "High",
                row_number,
                row,
                "Review Status",
                f"Allowed values: {sorted(CANDIDATE_STATUSES)}",
            )
        speaker_type = clean(row.get("Speaker Type"))
        if speaker_type not in {"Academic", "Industry"}:
            add("High", row_number, row, "Speaker Type", "Must be Academic or Industry.")
        email = clean(row.get("Email"))
        if email and not EMAIL_RE.fullmatch(email):
            add("High", row_number, row, "Email", "Must contain exactly one plain email address.")
        for field in ("Profile URL", "Email Source URL"):
            value = clean(row.get(field))
            if value and not _valid_url(value):
                add("High", row_number, row, field, "Must be an HTTP or HTTPS URL.")
        if status == "Approved":
            for field in APPROVED_REQUIRED_FIELDS:
                if not clean(row.get(field)):
                    add("High", row_number, row, field, "Required before candidate approval.")
            if clean(row.get("Contact Type")) == "Direct" and not clean(
                row.get("Preferred Salutation")
            ):
                add(
                    "Medium",
                    row_number,
                    row,
                    "Preferred Salutation",
                    "Recommended for direct outreach.",
                )
        key = candidate_key(row)
        if all(key):
            duplicate_rows[key].append(row_number)

    for row_numbers in duplicate_rows.values():
        if len(row_numbers) < 2:
            continue
        for row_number in row_numbers:
            row = rows[row_number - 2]
            others = ", ".join(str(value) for value in row_numbers if value != row_number)
            add(
                "High",
                row_number,
                row,
                "Full Name + Organization",
                f"Duplicate candidate; also row(s) {others}.",
            )
    return issues


def approved_candidates(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    issues = validate_candidates(rows)
    blocked_ids = {
        issue["Candidate ID"]
        for issue in issues
        if issue["Severity"] == "High" and issue["Candidate ID"]
    }
    return [
        row
        for row in rows
        if clean(row.get("Review Status")) == "Approved"
        and clean(row.get("Candidate ID"))
        and clean(row.get("Candidate ID")) not in blocked_ids
    ]


__all__ = ["QA_COLUMNS", "approved_candidates", "validate_candidates"]
