"""Validation gates that must pass before a candidate can become a mail draft."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from urllib.parse import urlparse

from .common import EMAIL_RE, candidate_key, clean, today_iso
from .schema import CANDIDATE_STATUSES, MAILBOX_STATUSES, QA_COLUMNS

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

BLOCKED_MAILBOX_STATUSES = frozenset({"Hard Bounce", "Suppressed"})


def _is_targeted_candidate(row: dict[str, str]) -> bool:
    """Return whether *row* opts into the evidence-bound targeted flow.

    ``Schema Version`` alone is not sufficient: legacy academic and general
    industry collectors are hydrated into the 1.1 table shape without target
    evidence.  Any targeting/evidence identifier, however, makes the stronger
    gate mandatory so a partially cleared row cannot fall back to legacy rules.
    """

    return any(
        clean(row.get(field))
        for field in (
            "Campaign ID",
            "Target ID",
            "Identity Evidence ID",
            "Role Evidence ID",
            "Email Evidence ID",
        )
    )


def _same_claim_value(left: str, right: str) -> bool:
    return clean(left).casefold() == clean(right).casefold()


def _valid_url(value: str) -> bool:
    parsed = urlparse(clean(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _evidence_field(record: object, field: str) -> str:
    if isinstance(record, dict):
        return clean(record.get(field))
    attribute = field.casefold().replace(" ", "_")
    return clean(getattr(record, attribute, ""))


def validate_candidates(
    rows: list[dict[str, str]],
    evidence_records: Iterable[object] | None = None,
    *,
    allow_historical_targets: bool = False,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    run_date = today_iso()
    evidence_supplied = evidence_records is not None
    evidence_by_id: dict[str, list[object]] = defaultdict(list)
    for record in evidence_records or []:
        identifier = _evidence_field(record, "Evidence ID")
        if identifier:
            evidence_by_id[identifier].append(record)

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
            # Targeted records have stronger, evidence-bound gates. Legacy
            # discovery records remain readable, but any targeting/evidence ID
            # opts the row into this fail-closed path.
            if _is_targeted_candidate(row):
                for field in (
                    "Campaign ID",
                    "Target ID",
                    "Identity Evidence ID",
                    "Role Evidence ID",
                ):
                    if not clean(row.get(field)):
                        add("High", row_number, row, field, "Required for a v1.1 approval.")
                role_status = clean(row.get("Role Temporal Status"))
                if role_status == "Historical Fact" and not allow_historical_targets:
                    add(
                        "High",
                        row_number,
                        row,
                        "Role Temporal Status",
                        "Historical targets require an explicit campaign-policy opt-in.",
                    )
                elif role_status not in {"Current", "Historical Fact"}:
                    add(
                        "High",
                        row_number,
                        row,
                        "Role Temporal Status",
                        "Must be Current, or Historical Fact when explicitly permitted.",
                    )
                evidence_level = clean(row.get("Email Evidence Level"))
                if clean(row.get("Contact Type")) == "Direct" and evidence_level not in {
                    "E3 Exact Current Authoritative",
                    "E4 Exact Current Official",
                }:
                    add(
                        "High",
                        row_number,
                        row,
                        "Email Evidence Level",
                        "Direct outreach requires E3 or E4 exact current-address evidence.",
                    )
                if not clean(row.get("Email Evidence ID")):
                    add(
                        "High",
                        row_number,
                        row,
                        "Email Evidence ID",
                        "A contact assertion must link to evidence before approval.",
                    )
                if clean(row.get("Mailbox Status")) in BLOCKED_MAILBOX_STATUSES:
                    add(
                        "High",
                        row_number,
                        row,
                        "Mailbox Status",
                        "A bounced or suppressed address cannot be approved.",
                    )
                elif clean(row.get("Mailbox Status")) not in MAILBOX_STATUSES:
                    add(
                        "High",
                        row_number,
                        row,
                        "Mailbox Status",
                        "Mailbox status is missing or unsupported.",
                    )
                if not evidence_supplied:
                    add(
                        "High",
                        row_number,
                        row,
                        "Evidence Ledger",
                        "The evidence ledger is required to validate a targeted approval.",
                    )
                else:
                    role_claim_types = (
                        {"Role", "Historical Role"}
                        if role_status == "Historical Fact"
                        else {"Role", "Current Role"}
                    )
                    role_temporal_statuses = (
                        {"Former", "Historical Fact"}
                        if role_status == "Historical Fact"
                        else {"Current"}
                    )
                    evidence_rules = (
                        (
                            "Identity Evidence ID",
                            {"Identity"},
                            clean(row.get("Full Name")),
                            # A person's identity is not itself a time-bounded
                            # role assertion. Collectors therefore emit Not
                            # Applicable; reviewed imports may use Current.
                            {"Current", "Not Applicable"},
                        ),
                        (
                            "Role Evidence ID",
                            role_claim_types,
                            clean(row.get("Title")),
                            role_temporal_statuses,
                        ),
                        (
                            "Email Evidence ID",
                            {"Email Address"},
                            clean(row.get("Email")),
                            {"Current"},
                        ),
                    )
                    resolved_evidence: dict[str, object] = {}
                    for (
                        identifier_field,
                        expected_claim_types,
                        expected_claim_value,
                        expected_temporal_statuses,
                    ) in evidence_rules:
                        identifier = clean(row.get(identifier_field))
                        matches = evidence_by_id.get(identifier, [])
                        if len(matches) > 1:
                            add(
                                "High",
                                row_number,
                                row,
                                identifier_field,
                                "Referenced Evidence ID is duplicated; binding is ambiguous.",
                            )
                            continue
                        evidence = matches[0] if matches else None
                        if evidence is None:
                            add(
                                "High",
                                row_number,
                                row,
                                identifier_field,
                                "Referenced evidence record was not found.",
                            )
                            continue
                        resolved_evidence[identifier_field] = evidence
                        if _evidence_field(evidence, "Target ID") != clean(row.get("Target ID")):
                            add(
                                "High",
                                row_number,
                                row,
                                identifier_field,
                                "Evidence belongs to a different target.",
                            )
                        if _evidence_field(evidence, "Campaign ID") != clean(
                            row.get("Campaign ID")
                        ):
                            add(
                                "High",
                                row_number,
                                row,
                                identifier_field,
                                "Evidence belongs to a different campaign.",
                            )
                        if _evidence_field(evidence, "Candidate ID") != clean(
                            row.get("Candidate ID")
                        ):
                            add(
                                "High",
                                row_number,
                                row,
                                identifier_field,
                                "Evidence must name this exact Candidate ID.",
                            )
                        if _evidence_field(evidence, "Claim Type") not in expected_claim_types:
                            add(
                                "High",
                                row_number,
                                row,
                                identifier_field,
                                "Evidence has the wrong claim type.",
                            )
                        if not _same_claim_value(
                            _evidence_field(evidence, "Claim Value"), expected_claim_value
                        ):
                            add(
                                "High",
                                row_number,
                                row,
                                identifier_field,
                                "Evidence does not contain the candidate's exact claim value.",
                            )
                        if _evidence_field(evidence, "Review Status") != "Accepted":
                            add(
                                "High",
                                row_number,
                                row,
                                identifier_field,
                                "Only Accepted evidence can support an approval.",
                            )
                        if _evidence_field(evidence, "Claim Polarity") != "Supports":
                            add(
                                "High",
                                row_number,
                                row,
                                identifier_field,
                                "Only supporting evidence can support an approval.",
                            )
                        if (
                            _evidence_field(evidence, "Temporal Status")
                            not in expected_temporal_statuses
                        ):
                            expected = ", ".join(sorted(expected_temporal_statuses))
                            add(
                                "High",
                                row_number,
                                row,
                                identifier_field,
                                f"Evidence temporal status must be: {expected}.",
                            )
                    email_evidence = resolved_evidence.get("Email Evidence ID")
                    if email_evidence is not None:
                        if (
                            _evidence_field(email_evidence, "Claim Value").casefold()
                            != clean(row.get("Email")).casefold()
                        ):
                            add(
                                "High",
                                row_number,
                                row,
                                "Email Evidence ID",
                                "Evidence does not contain the candidate's exact email address.",
                            )
                        if _evidence_field(email_evidence, "Email Evidence Level") != clean(
                            row.get("Email Evidence Level")
                        ):
                            add(
                                "High",
                                row_number,
                                row,
                                "Email Evidence Level",
                                "Candidate and evidence levels do not match.",
                            )
                        expected_ownership = (
                            "Direct Person"
                            if clean(row.get("Contact Type")) == "Direct"
                            else "Department Route"
                        )
                        if (
                            _evidence_field(email_evidence, "Contact Ownership")
                            != expected_ownership
                        ):
                            add(
                                "High",
                                row_number,
                                row,
                                "Contact Type",
                                f"Evidence ownership must be {expected_ownership}.",
                            )
                        evidence_mailbox_status = _evidence_field(email_evidence, "Mailbox Status")
                        candidate_mailbox_status = clean(row.get("Mailbox Status"))
                        if evidence_mailbox_status in BLOCKED_MAILBOX_STATUSES:
                            add(
                                "High",
                                row_number,
                                row,
                                "Mailbox Status",
                                "Email evidence marks the address bounced or suppressed.",
                            )
                        elif evidence_mailbox_status not in MAILBOX_STATUSES:
                            add(
                                "High",
                                row_number,
                                row,
                                "Mailbox Status",
                                "Email evidence has a missing or unsupported mailbox status.",
                            )
                        if evidence_mailbox_status != candidate_mailbox_status:
                            add(
                                "High",
                                row_number,
                                row,
                                "Mailbox Status",
                                "Candidate and email-evidence mailbox statuses do not match.",
                            )
            if clean(row.get("Schema Version")) == "1.1":
                from .approvals import approval_is_valid

                if not approval_is_valid(row, record_type="candidate"):
                    add(
                        "High",
                        row_number,
                        row,
                        "Approval Hash",
                        "Approval metadata is missing or no longer matches candidate content.",
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


def approved_candidates(
    rows: list[dict[str, str]],
    evidence_records: Iterable[object] | None = None,
    *,
    allow_historical_targets: bool = False,
) -> list[dict[str, str]]:
    issues = validate_candidates(
        rows,
        evidence_records,
        allow_historical_targets=allow_historical_targets,
    )
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
