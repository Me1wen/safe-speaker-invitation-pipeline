"""Invitation-template rendering and review-draft creation."""

from __future__ import annotations

import json
from pathlib import Path

from .common import clean, draft_id, utc_now_iso
from .schema import DRAFT_COLUMNS, DRAFT_STATUSES, GENERIC_CONTACT_TYPES
from .validation import approved_candidates

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
) -> list[dict[str, str]]:
    existing_drafts = existing_drafts or []
    existing_by_id = {
        clean(row.get("Draft ID")): row for row in existing_drafts if clean(row.get("Draft ID"))
    }
    protected = [
        {column: clean(row.get(column, "")) for column in DRAFT_COLUMNS}
        for row in existing_drafts
        if clean(row.get("Draft Status")) in {"Sending", "Sent"}
    ]
    protected_candidates = {row["Candidate ID"] for row in protected}
    output: list[dict[str, str]] = list(protected)
    for candidate in approved_candidates(candidates):
        if candidate["Candidate ID"] in protected_candidates:
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
        )
        old = existing_by_id.get(identifier, {})
        status = clean(old.get("Draft Status")) or "Draft"
        if status not in DRAFT_STATUSES:
            raise ValueError(f"Invalid Draft Status for {identifier}: {status}")
        output.append(
            {
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
            }
        )
    return output


__all__ = ["DRAFT_COLUMNS", "generate_drafts", "load_invitation_config"]
