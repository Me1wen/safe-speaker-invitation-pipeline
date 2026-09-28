"""Fail-closed authorization policy for reviewed outreach delivery.

Research records, evidence, and approved drafts are deliberately separate.  A
live delivery is authorized only when all of those current records still agree
at the final preflight and no active suppression matches the recipient.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .approvals import require_valid_approval
from .common import EMAIL_RE, clean, read_csv
from .schema import (
    EMAIL_EVIDENCE_RANK,
    SUPPRESSION_COLUMNS,
    SUPPRESSION_SCOPES,
    SUPPRESSION_STATUSES,
)
from .targets import Campaign
from .validation import validate_candidates

POLICY_HASH_PREFIX = "sha256-policy-v1:"


class DeliveryPolicyError(ValueError):
    """Raised when current policy does not authorize a live delivery."""


def _normalized_scope_value(scope: str, value: str) -> str:
    normalized = clean(value).casefold()
    if scope == "Domain":
        return normalized.removeprefix("@").removeprefix("www.")
    return normalized


def _date_value(value: str, field: str) -> date | None:
    normalized = clean(value)
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized[:10])
    except ValueError as exc:
        raise DeliveryPolicyError(f"{field} must begin with an ISO date (YYYY-MM-DD).") from exc


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _record_field(record: object, field: str) -> str:
    if isinstance(record, dict):
        return clean(record.get(field))
    return clean(getattr(record, field.casefold().replace(" ", "_"), ""))


def campaign_policy_hash(campaign: Campaign) -> str:
    """Bind a draft approval to the exact campaign policy reviewed with it."""

    payload = {key: clean(value) for key, value in sorted(campaign.to_row().items())}
    serialized = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return POLICY_HASH_PREFIX + hashlib.sha256(serialized).hexdigest()


@dataclass(frozen=True)
class SuppressionRecord:
    suppression_id: str
    scope: str
    value: str
    reason: str
    status: str = "Active"
    created_at: str = ""
    created_by: str = ""
    expires_at: str = ""
    revoked_at: str = ""
    revoked_by: str = ""
    notes: str = ""
    schema_version: str = "1.1"

    @classmethod
    def from_row(cls, row: dict[str, str]) -> SuppressionRecord:
        scope = clean(row.get("Scope"))
        status = clean(row.get("Status")) or "Active"
        value = _normalized_scope_value(scope, row.get("Value", ""))
        if scope not in SUPPRESSION_SCOPES:
            raise ValueError(f"Invalid suppression Scope: {scope!r}.")
        if status not in SUPPRESSION_STATUSES:
            raise ValueError(f"Invalid suppression Status: {status!r}.")
        if not value:
            raise ValueError("Suppression Value must not be blank.")
        if scope == "Email" and not EMAIL_RE.fullmatch(value):
            raise ValueError(f"Invalid suppressed email address: {value!r}.")
        if scope == "Domain" and ("@" in value or "." not in value):
            raise ValueError(f"Invalid suppressed domain: {value!r}.")
        reason = clean(row.get("Reason"))
        if status == "Active" and not reason:
            raise ValueError("An active suppression must record a reason.")
        created_at = clean(row.get("Created At"))
        created_by = clean(row.get("Created By"))
        if not created_at or not created_by:
            raise ValueError("A suppression must record Created At and Created By.")
        revoked_at = clean(row.get("Revoked At"))
        revoked_by = clean(row.get("Revoked By"))
        if status == "Revoked" and (not revoked_at or not revoked_by):
            raise ValueError("A revoked suppression must record Revoked At and Revoked By.")
        identifier = clean(row.get("Suppression ID"))
        if not identifier:
            digest = hashlib.sha256(f"{scope.casefold()}|{value}".encode()).hexdigest()
            identifier = f"SUP-{digest[:16].upper()}"
        expires_at = clean(row.get("Expires At"))
        if expires_at:
            _date_value(expires_at, "Expires At")
        return cls(
            suppression_id=identifier,
            scope=scope,
            value=value,
            reason=reason,
            status=status,
            created_at=created_at,
            created_by=created_by,
            expires_at=expires_at,
            revoked_at=revoked_at,
            revoked_by=revoked_by,
            notes=clean(row.get("Notes")),
            schema_version=clean(row.get("Schema Version")) or "1.1",
        )

    def to_row(self) -> dict[str, str]:
        return {
            "Schema Version": self.schema_version,
            "Suppression ID": self.suppression_id,
            "Scope": self.scope,
            "Value": self.value,
            "Reason": self.reason,
            "Status": self.status,
            "Created At": self.created_at,
            "Created By": self.created_by,
            "Expires At": self.expires_at,
            "Revoked At": self.revoked_at,
            "Revoked By": self.revoked_by,
            "Notes": self.notes,
        }

    def active_on(self, as_of: date) -> bool:
        expiry = _date_value(self.expires_at, "Expires At")
        return self.status == "Active" and (expiry is None or as_of <= expiry)

    def matches(self, draft: dict[str, str]) -> bool:
        recipient = clean(draft.get("To Email")).casefold()
        scope_values = {
            "Email": recipient,
            "Domain": recipient.rsplit("@", 1)[-1] if "@" in recipient else "",
            "Target ID": clean(draft.get("Target ID")).casefold(),
            "Candidate ID": clean(draft.get("Candidate ID")).casefold(),
        }
        return scope_values.get(self.scope, "") == self.value


def load_suppressions(path: Path) -> list[SuppressionRecord]:
    rows = read_csv(path, SUPPRESSION_COLUMNS)
    records = [SuppressionRecord.from_row(row) for row in rows if any(row.values())]
    identifiers: set[str] = set()
    for record in records:
        if record.suppression_id in identifiers:
            raise ValueError(f"Duplicate Suppression ID: {record.suppression_id}")
        identifiers.add(record.suppression_id)
    return records


@dataclass(frozen=True)
class DeliveryAuthorization:
    campaign_id: str
    policy_hash: str
    selected: int
    attempted: int
    remaining_after_batch: int


def validate_delivery_policy(
    drafts: list[dict[str, str]],
    campaign: Campaign,
    candidates: list[dict[str, str]],
    evidence_records: Iterable[object],
    suppressions: Iterable[SuppressionRecord],
    *,
    campaign_id: str,
    max_messages: int = 0,
    as_of: date | None = None,
) -> DeliveryAuthorization:
    """Authorize the current Approved batch against all current ledgers.

    ``max_messages`` is an optional operator-side cap.  The campaign's positive
    ``Max Messages`` is always authoritative; zero authorizes no live delivery.
    """

    if max_messages < 0:
        raise DeliveryPolicyError("max_messages must not be negative.")
    requested_campaign = clean(campaign_id)
    if not requested_campaign or campaign.campaign_id != requested_campaign:
        raise DeliveryPolicyError("Exactly one matching Campaign ID is required.")
    if campaign.campaign_status != "Active":
        raise DeliveryPolicyError(
            f"Campaign {campaign.campaign_id} is {campaign.campaign_status}; only Active may send."
        )
    if campaign.max_messages <= 0:
        raise DeliveryPolicyError("Campaign Max Messages must be positive for live delivery.")
    today = as_of or _today_utc()
    research_as_of = _date_value(campaign.research_as_of, "Research As Of")
    if research_as_of is None:
        raise DeliveryPolicyError("Campaign Research As Of is required for live delivery.")
    if research_as_of > today:
        raise DeliveryPolicyError("Campaign Research As Of cannot be in the future.")
    not_before = _date_value(campaign.outreach_not_before, "Outreach Not Before")
    not_after = _date_value(campaign.outreach_not_after, "Outreach Not After")
    if not_before and not_after and not_before > not_after:
        raise DeliveryPolicyError("Campaign outreach window is inverted.")
    if not_before and today < not_before:
        raise DeliveryPolicyError("Campaign outreach window has not started.")
    if not_after and today > not_after:
        raise DeliveryPolicyError("Campaign outreach window has ended.")

    selected = [
        row
        for row in drafts
        if clean(row.get("Draft Status")) == "Approved"
        and clean(row.get("Campaign ID")) == requested_campaign
    ]
    if max_messages > 0:
        selected = selected[:max_messages]
    if not selected:
        raise DeliveryPolicyError("No Approved drafts are authorized for this campaign.")

    attempted = sum(
        1
        for row in drafts
        if clean(row.get("Campaign ID")) == requested_campaign
        and (
            clean(row.get("Draft Status")) in {"Sending", "Sent", "Failed"}
            or bool(clean(row.get("Last Attempt At")))
        )
    )
    if attempted + len(selected) > campaign.max_messages:
        raise DeliveryPolicyError(
            f"Campaign cap exceeded: {attempted} attempted + {len(selected)} selected "
            f"> {campaign.max_messages}."
        )

    by_candidate: dict[str, dict[str, str]] = {}
    for candidate in candidates:
        identifier = clean(candidate.get("Candidate ID"))
        if identifier in by_candidate:
            raise DeliveryPolicyError(f"Duplicate Candidate ID: {identifier or '<blank>'}.")
        if identifier:
            by_candidate[identifier] = candidate
    policy_hash = campaign_policy_hash(campaign)
    active_suppressions = [record for record in suppressions if record.active_on(today)]
    current_evidence = list(evidence_records)
    evidence_by_id: dict[str, list[object]] = {}
    for record in current_evidence:
        identifier = _record_field(record, "Evidence ID")
        if identifier:
            evidence_by_id.setdefault(identifier, []).append(record)

    for draft in selected:
        draft_id = clean(draft.get("Draft ID")) or "<unknown>"
        candidate_id = clean(draft.get("Candidate ID"))
        candidate = by_candidate.get(candidate_id)
        if candidate is None:
            raise DeliveryPolicyError(f"Draft {draft_id} has no current candidate record.")
        require_valid_approval(candidate, record_type="candidate", allow_legacy=False)
        if clean(candidate.get("Campaign ID")) != requested_campaign:
            raise DeliveryPolicyError(f"Draft {draft_id} candidate belongs to another campaign.")
        if clean(draft.get("Candidate Approval Hash")) != clean(candidate.get("Approval Hash")):
            raise DeliveryPolicyError(
                f"Draft {draft_id} is not bound to the candidate's current approval."
            )
        if clean(draft.get("Campaign Policy Hash")) != policy_hash:
            raise DeliveryPolicyError(
                f"Draft {draft_id} is not bound to the current campaign policy."
            )
        if clean(draft.get("To Email")).casefold() != clean(candidate.get("Email")).casefold():
            raise DeliveryPolicyError(f"Draft {draft_id} recipient differs from the candidate.")
        if clean(draft.get("Contact Type")) != clean(candidate.get("Contact Type")):
            raise DeliveryPolicyError(f"Draft {draft_id} route differs from the candidate.")

        role_as_of = _date_value(clean(candidate.get("Role As Of")), "Candidate Role As Of")
        if role_as_of is None or role_as_of < research_as_of or role_as_of > today:
            raise DeliveryPolicyError(
                f"Draft {draft_id} candidate role date is outside the current research window."
            )

        high_issues = [
            issue
            for issue in validate_candidates(
                [candidate],
                current_evidence,
                allow_historical_targets=campaign.allow_historical_targets,
            )
            if issue["Severity"] == "High"
        ]
        if high_issues:
            fields = ", ".join(sorted({issue["Field"] for issue in high_issues}))
            raise DeliveryPolicyError(
                f"Draft {draft_id} candidate no longer passes validation ({fields})."
            )
        for identifier_field in (
            "Identity Evidence ID",
            "Role Evidence ID",
            "Email Evidence ID",
        ):
            identifier = clean(candidate.get(identifier_field))
            records = evidence_by_id.get(identifier, [])
            if len(records) != 1:
                raise DeliveryPolicyError(
                    f"Draft {draft_id} has missing or ambiguous current evidence."
                )
            record = records[0]
            confirmed = _date_value(
                _record_field(record, "Last Confirmed At") or _record_field(record, "Retrieved At"),
                f"{identifier_field} confirmation time",
            )
            if confirmed is None or confirmed < research_as_of or confirmed > today:
                raise DeliveryPolicyError(
                    f"Draft {draft_id} evidence is stale for Campaign Research As Of."
                )
            effective_from = _date_value(
                _record_field(record, "Effective From"),
                f"{identifier_field} Effective From",
            )
            effective_to = _date_value(
                _record_field(record, "Effective To"),
                f"{identifier_field} Effective To",
            )
            if effective_from and today < effective_from:
                raise DeliveryPolicyError(f"Draft {draft_id} evidence is not yet effective.")
            if effective_to and today > effective_to:
                raise DeliveryPolicyError(f"Draft {draft_id} evidence has expired.")
        if clean(candidate.get("Role Temporal Status")) == "Historical Fact" and not (
            campaign.allow_historical_targets
        ):
            raise DeliveryPolicyError(f"Draft {draft_id} targets a disallowed historical role.")

        contact_type = clean(candidate.get("Contact Type"))
        if contact_type == "Direct":
            actual_rank = EMAIL_EVIDENCE_RANK.get(clean(candidate.get("Email Evidence Level")), -1)
            required_rank = EMAIL_EVIDENCE_RANK[campaign.minimum_direct_email_evidence]
            if actual_rank < required_rank:
                raise DeliveryPolicyError(
                    f"Draft {draft_id} email evidence is below campaign minimum."
                )
        elif not campaign.allow_department_routes:
            raise DeliveryPolicyError(f"Draft {draft_id} uses a disallowed routed contact.")

        for suppression in active_suppressions:
            # Target-scoped rules match through the current candidate because
            # Target ID is intentionally not duplicated in the legacy draft schema.
            match_row = dict(draft)
            match_row["Target ID"] = clean(candidate.get("Target ID"))
            if suppression.matches(match_row):
                raise DeliveryPolicyError(
                    f"Draft {draft_id} is blocked by active suppression "
                    f"{suppression.suppression_id}."
                )

    return DeliveryAuthorization(
        campaign_id=requested_campaign,
        policy_hash=policy_hash,
        selected=len(selected),
        attempted=attempted,
        remaining_after_batch=campaign.max_messages - attempted - len(selected),
    )


__all__ = [
    "DeliveryAuthorization",
    "DeliveryPolicyError",
    "POLICY_HASH_PREFIX",
    "SuppressionRecord",
    "campaign_policy_hash",
    "load_suppressions",
    "validate_delivery_policy",
]
