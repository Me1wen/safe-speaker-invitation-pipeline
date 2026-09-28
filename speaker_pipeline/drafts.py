"""Invitation-template rendering and review-draft creation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .approvals import approval_is_valid
from .common import clean, draft_id, utc_now_iso
from .schema import DRAFT_COLUMNS, DRAFT_STATUSES, GENERIC_CONTACT_TYPES, SCHEMA_VERSION
from .validation import approved_candidates

CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

ATTEMPTED_DRAFT_STATUSES = frozenset({"Sending", "Sent", "Failed"})
ATTEMPT_AUDIT_FIELDS = (
    "Last Attempt At",
    "Sent At",
    "Message ID",
    "Error",
)

REQUIRED_CONFIG_KEYS = {
    "event_name",
    "event_host",
    "event_date",
    "event_location",
    "event_description",
    "sender_name",
    "sender_title",
    "sender_organization",
    "sender_email",
    "subject_template",
    "direct_body_template",
    "routed_body_template",
}


class StrictValues(dict[str, str]):
    def __missing__(self, key: str) -> str:
        raise ValueError(f"Unknown template placeholder: {key}")


def load_invitation_config(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invitation config must be a JSON object.")
    config = {str(key): str(value) for key, value in data.items()}
    missing = sorted(REQUIRED_CONFIG_KEYS - set(config))
    if missing:
        raise ValueError(f"Invitation config is missing: {', '.join(missing)}")
    return config


def campaign_id_from_config(config: dict[str, str]) -> str:
    """Return an explicit campaign ID or a stable ID derived from event identity."""

    explicit = clean(config.get("campaign_id") or config.get("Campaign ID"))
    if explicit:
        if not CAMPAIGN_ID_RE.fullmatch(explicit):
            raise ValueError(
                "campaign_id must start with a letter or number and contain only "
                "letters, numbers, dots, underscores, or hyphens (maximum 64 characters)."
            )
        return explicit
    identity = {
        key: clean(config.get(key))
        for key in ("event_name", "event_host", "event_date", "event_location")
    }
    serialized = json.dumps(
        identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return f"CAMPAIGN-{hashlib.sha256(serialized).hexdigest()[:12].upper()}"


def _draft_value(row: dict[str, str], column: str) -> str:
    """Normalize structural fields without destroying body paragraph breaks."""

    value = row.get(column, "")
    if column == "Body Text":
        return str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return clean(value)


def _normalize_existing_draft(row: dict[str, str]) -> dict[str, str]:
    """Normalize declared fields while retaining forward-compatible audit data."""

    normalized = dict(row)
    normalized.update({column: _draft_value(row, column) for column in DRAFT_COLUMNS})
    return normalized


def _has_delivery_attempt(row: dict[str, str]) -> bool:
    return clean(row.get("Draft Status")) in ATTEMPTED_DRAFT_STATUSES or any(
        clean(row.get(field)) for field in ATTEMPT_AUDIT_FIELDS
    )


def _legacy_candidate_is_unscoped(candidate: dict[str, str]) -> bool:
    """Identify a genuine pre-target-ledger candidate for review-only migration."""

    return clean(candidate.get("Schema Version")) in {"", "1.0"} and not any(
        clean(candidate.get(field))
        for field in (
            "Campaign ID",
            "Target ID",
            "Identity Evidence ID",
            "Role Evidence ID",
            "Email Evidence ID",
        )
    )


def _render(template: str, values: dict[str, str]) -> str:
    try:
        return template.format_map(StrictValues(values)).strip()
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Could not render invitation template: {exc}") from exc


def _template_values(candidate: dict[str, str], config: dict[str, str]) -> dict[str, str]:
    name = clean(candidate.get("Full Name"))
    contact_type = clean(candidate.get("Contact Type"))
    values = dict(config)
    values.update(
        {
            "candidate_id": clean(candidate.get("Candidate ID")),
            "full_name": name,
            "organization": clean(candidate.get("Organization")),
            "title": clean(candidate.get("Title")),
            "expertise": clean(candidate.get("Expertise")),
            "topic_fit": clean(candidate.get("Topic Fit")),
            "profile_url": clean(candidate.get("Profile URL")),
            "contact_type": contact_type,
            "salutation": clean(candidate.get("Preferred Salutation")) or name,
            "route_greeting": f"{contact_type} Team"
            if contact_type in GENERIC_CONTACT_TYPES
            else name,
        }
    )
    return values


def generate_drafts(
    candidates: list[dict[str, str]],
    config: dict[str, str],
    existing_drafts: list[dict[str, str]] | None = None,
    evidence_records: list[object] | None = None,
    *,
    allow_historical_targets: bool = False,
    allow_legacy_unscoped_candidates: bool = True,
    campaign_policy_hash: str = "",
) -> list[dict[str, str]]:
    existing_drafts = existing_drafts or []
    campaign_id = campaign_id_from_config(config)
    existing_by_id: dict[str, dict[str, str]] = {}
    protected: list[dict[str, str]] = []
    protected_candidates: set[tuple[str, str]] = set()
    for source in existing_drafts:
        row = _normalize_existing_draft(source)
        identifier = clean(row.get("Draft ID"))
        if not identifier:
            raise ValueError("Every existing draft must have a Draft ID; refusing data loss.")
        if identifier in existing_by_id:
            raise ValueError(f"Duplicate existing Draft ID: {identifier}")
        status = clean(row.get("Draft Status"))
        if status not in DRAFT_STATUSES:
            raise ValueError(f"Invalid existing Draft Status for {identifier}: {status}")
        existing_by_id[identifier] = row
        if not _has_delivery_attempt(row):
            continue
        attempted_campaign = clean(row.get("Campaign ID"))
        attempted_candidate = clean(row.get("Candidate ID"))
        if not attempted_campaign or not attempted_candidate:
            raise ValueError(
                f"Attempted draft {identifier} lacks Campaign ID or Candidate ID; "
                "manual reconciliation is required before regeneration."
            )
        protected.append(row)
        protected_candidates.add((attempted_campaign, attempted_candidate))

    output: list[dict[str, str]] = list(protected)
    eligible_candidates = approved_candidates(
        candidates,
        evidence_records,
        allow_historical_targets=allow_historical_targets,
    )
    for candidate in eligible_candidates:
        candidate_campaign = clean(candidate.get("Campaign ID"))
        # Genuine v1.0/unversioned rows may still produce a review draft for
        # migration compatibility. They deliberately carry no candidate or
        # policy hash, so the v1.1 live-delivery gate cannot send them. Callers
        # may disable even this review-only compatibility path.
        legacy_opt_in = allow_legacy_unscoped_candidates and _legacy_candidate_is_unscoped(
            candidate
        )
        if candidate_campaign != campaign_id and not legacy_opt_in:
            candidate_identifier = clean(candidate.get("Candidate ID")) or "<unknown>"
            observed = candidate_campaign or "<blank>"
            raise ValueError(
                f"Approved candidate {candidate_identifier} belongs to campaign {observed}, "
                f"not invitation campaign {campaign_id}."
            )
        if (campaign_id, candidate["Candidate ID"]) in protected_candidates:
            continue
        values = _template_values(candidate, config)
        contact_type = clean(candidate.get("Contact Type"))
        body_template = (
            config["direct_body_template"]
            if contact_type == "Direct"
            else config["routed_body_template"]
        )
        subject = _render(config["subject_template"], values)
        if "\r" in subject or "\n" in subject:
            raise ValueError("Rendered Subject must be one line.")
        body = _render(body_template, values)
        identifier = draft_id(
            candidate["Candidate ID"],
            f"{candidate['Email']}|{contact_type}|{subject}",
            body,
            campaign_id,
        )
        old = existing_by_id.get(identifier, {})
        status = clean(old.get("Draft Status")) or "Draft"
        if status not in DRAFT_STATUSES:
            raise ValueError(f"Invalid Draft Status for {identifier}: {status}")
        row = {
            "Draft ID": identifier,
            "Candidate ID": candidate["Candidate ID"],
            "Draft Status": status,
            "To Email": candidate["Email"],
            "To Name": candidate["Full Name"],
            "Contact Type": contact_type,
            "Subject": subject,
            "Body Text": body,
            "Profile URL": candidate["Profile URL"],
            "Created At": clean(old.get("Created At")) or utc_now_iso(),
            "Last Attempt At": clean(old.get("Last Attempt At")),
            "Sent At": clean(old.get("Sent At")),
            "Message ID": clean(old.get("Message ID")),
            "Error": clean(old.get("Error")),
            "Campaign ID": campaign_id,
            "Candidate Approval Hash": clean(candidate.get("Approval Hash")),
            "Campaign Policy Hash": clean(campaign_policy_hash),
            "Sender Email": clean(config.get("sender_email")),
            "Sender Name": clean(config.get("sender_name")),
            "Reply-To": clean(config.get("reply_to")),
            "Revision": clean(old.get("Revision")) or "1",
            "Approval Hash": clean(old.get("Approval Hash")),
            "Approved At": clean(old.get("Approved At")),
            "Approved By": clean(old.get("Approved By")),
            "Schema Version": SCHEMA_VERSION,
        }
        # Preserve any forward-compatible schema fields which this generator does
        # not own, while still emitting every declared column.
        for column in DRAFT_COLUMNS:
            row.setdefault(column, _draft_value(old, column))

        if status in {"Approved", "Failed"} and approval_is_valid(row, record_type="draft"):
            # Keep the approval seal for an unchanged Approved row or an
            # explicitly retryable Failed row.
            pass
        elif status == "Approved":
            # A v1.0 approval has no integrity binding.  It remains available for
            # review but cannot silently become a sendable v1.1 draft.
            row["Draft Status"] = "Draft"
            row["Approval Hash"] = ""
            row["Approved At"] = ""
            row["Approved By"] = ""
        else:
            # A content fingerprint is not an approval.  Only approve_row() (or
            # the reviewed-workbook importer) may create the complete seal.
            row["Approval Hash"] = ""
            row["Approved At"] = ""
            row["Approved By"] = ""
        output.append(row)
    return output


__all__ = [
    "CAMPAIGN_ID_RE",
    "DRAFT_COLUMNS",
    "campaign_id_from_config",
    "generate_drafts",
    "load_invitation_config",
]
