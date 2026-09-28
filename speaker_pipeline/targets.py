"""Campaign-scoped industry targets and claimed-contact records.

Targets preserve what a requester asked for.  A :class:`TargetReport` stores
the independently researched result so a changed or historical role never
silently rewrites the original request.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from .common import EMAIL_RE, clean, normalize_name
from .schema import (
    CAMPAIGN_COLUMNS,
    CAMPAIGN_STATUSES,
    CLAIM_STATUSES,
    EMAIL_CLAIM_COLUMNS,
    EMAIL_EVIDENCE_LEVELS,
    MAILBOX_STATUSES,
    SCHEMA_VERSION,
    TARGET_COLUMNS,
    TARGET_REPORT_COLUMNS,
    TARGET_STATUSES,
)

T = TypeVar("T")


def _stable_id(prefix: str, *parts: str, length: int = 16) -> str:
    normalized = "|".join(clean(part).casefold() for part in parts)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:length].upper()
    return f"{prefix}-{digest}"


def campaign_id(name: str, research_as_of: str = "") -> str:
    """Return a stable campaign ID for the same name and research date."""

    return _stable_id("CMP", name, research_as_of, length=12)


def target_id(campaign_id_value: str, full_name: str, organization: str) -> str:
    """Return a campaign-scoped target ID using normalized person/org names."""

    return _stable_id(
        "TGT",
        campaign_id_value,
        normalize_name(full_name),
        normalize_name(organization),
    )


def email_claim_id(target_id_value: str, email: str) -> str:
    """Return one stable ID per target and exact normalized email address."""

    return _stable_id("CLAIM", target_id_value, clean(email).casefold())


def target_report_id(campaign_id_value: str, target_id_value: str, role_as_of: str) -> str:
    return _stable_id("REPORT", campaign_id_value, target_id_value, role_as_of)


def _split_values(value: str) -> tuple[str, ...]:
    return tuple(item for item in (clean(part) for part in value.split(";")) if item)


def _join_values(values: tuple[str, ...]) -> str:
    return "; ".join(values)


def _parse_bool(value: str, field: str) -> bool:
    normalized = clean(value).casefold()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0", ""}:
        return False
    raise ValueError(f"{field} must be true or false, not {value!r}.")


def _parse_nonnegative_int(value: str, field: str) -> int:
    normalized = clean(value)
    try:
        result = int(normalized or "0")
    except ValueError as exc:
        raise ValueError(f"{field} must be an integer, not {value!r}.") from exc
    if result < 0:
        raise ValueError(f"{field} must not be negative.")
    return result


def _strict_rows(path: Path, columns: list[str]) -> list[dict[str, str]]:
    """Load only an exact known schema; never guess at missing/reordered fields."""

    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if headers != columns:
            raise ValueError(f"{path} columns do not match the required schema. Found: {headers}")
        rows: list[dict[str, str]] = []
        for source in reader:
            row = {column: clean(source.get(column, "")) for column in columns}
            if any(row.values()):
                rows.append(row)
        return rows


def _unique(records: list[T], attribute: str, label: str) -> list[T]:
    seen: set[str] = set()
    for record in records:
        value = clean(getattr(record, attribute))
        if not value:
            raise ValueError(f"{label} is blank.")
        if value in seen:
            raise ValueError(f"Duplicate {label}: {value}")
        seen.add(value)
    return records


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    campaign_name: str
    campaign_status: str = "Draft"
    purpose: str = ""
    owner: str = ""
    sender_organization: str = ""
    research_as_of: str = ""
    outreach_not_before: str = ""
    outreach_not_after: str = ""
    minimum_direct_email_evidence: str = "E4 Exact Current Official"
    allow_historical_targets: bool = False
    allow_department_routes: bool = True
    max_messages: int = 0
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def create(cls, campaign_name: str, *, research_as_of: str = "", **values: object) -> Campaign:
        return cls(
            campaign_id=campaign_id(campaign_name, research_as_of),
            campaign_name=clean(campaign_name),
            research_as_of=clean(research_as_of),
            **values,
        )

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Campaign:
        status = clean(row.get("Campaign Status")) or "Draft"
        evidence_level = (
            clean(row.get("Minimum Direct Email Evidence")) or "E4 Exact Current Official"
        )
        if status not in CAMPAIGN_STATUSES:
            raise ValueError(f"Invalid Campaign Status: {status}")
        if evidence_level not in EMAIL_EVIDENCE_LEVELS:
            raise ValueError(f"Invalid Minimum Direct Email Evidence: {evidence_level}")
        name = clean(row.get("Campaign Name"))
        research_as_of = clean(row.get("Research As Of"))
        identifier = clean(row.get("Campaign ID")) or campaign_id(name, research_as_of)
        return cls(
            campaign_id=identifier,
            campaign_name=name,
            campaign_status=status,
            purpose=clean(row.get("Purpose")),
            owner=clean(row.get("Owner")),
            sender_organization=clean(row.get("Sender Organization")),
            research_as_of=research_as_of,
            outreach_not_before=clean(row.get("Outreach Not Before")),
            outreach_not_after=clean(row.get("Outreach Not After")),
            minimum_direct_email_evidence=evidence_level,
            allow_historical_targets=_parse_bool(
                row.get("Allow Historical Targets", ""), "Allow Historical Targets"
            ),
            allow_department_routes=_parse_bool(
                row.get("Allow Department Routes", "") or "true", "Allow Department Routes"
            ),
            max_messages=_parse_nonnegative_int(row.get("Max Messages", ""), "Max Messages"),
            created_at=clean(row.get("Created At")),
            updated_at=clean(row.get("Updated At")),
            notes=clean(row.get("Notes")),
            schema_version=clean(row.get("Schema Version")) or SCHEMA_VERSION,
        )

    def to_row(self) -> dict[str, str]:
        return {
            "Schema Version": self.schema_version,
            "Campaign ID": self.campaign_id,
            "Campaign Name": self.campaign_name,
            "Campaign Status": self.campaign_status,
            "Purpose": self.purpose,
            "Owner": self.owner,
            "Sender Organization": self.sender_organization,
            "Research As Of": self.research_as_of,
            "Outreach Not Before": self.outreach_not_before,
            "Outreach Not After": self.outreach_not_after,
            "Minimum Direct Email Evidence": self.minimum_direct_email_evidence,
            "Allow Historical Targets": str(self.allow_historical_targets).lower(),
            "Allow Department Routes": str(self.allow_department_routes).lower(),
            "Max Messages": str(self.max_messages),
            "Created At": self.created_at,
            "Updated At": self.updated_at,
            "Notes": self.notes,
        }


@dataclass(frozen=True)
class IndustryTarget:
    target_id: str
    campaign_id: str
    full_name: str
    requested_organization: str
    requested_role: str
    priority: str = ""
    name_aliases: tuple[str, ...] = ()
    canonical_organization: str = ""
    organization_aliases: tuple[str, ...] = ()
    official_domain: str = ""
    allowed_domains: tuple[str, ...] = ()
    relationship_type: str = "Current Executive"
    profile_url_hint: str = ""
    created_at: str = ""
    notes: str = ""
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        campaign_id_value: str,
        full_name: str,
        requested_organization: str,
        requested_role: str,
        **values: object,
    ) -> IndustryTarget:
        canonical = clean(str(values.get("canonical_organization", "")))
        organization_for_id = canonical or clean(requested_organization)
        return cls(
            target_id=target_id(campaign_id_value, full_name, organization_for_id),
            campaign_id=clean(campaign_id_value),
            full_name=clean(full_name),
            requested_organization=clean(requested_organization),
            requested_role=clean(requested_role),
            **values,
        )

    @classmethod
    def from_row(cls, row: dict[str, str]) -> IndustryTarget:
        campaign = clean(row.get("Campaign ID"))
        name = clean(row.get("Full Name"))
        requested_org = clean(row.get("Requested Organization"))
        canonical_org = clean(row.get("Canonical Organization"))
        identifier = clean(row.get("Target ID")) or target_id(
            campaign, name, canonical_org or requested_org
        )
        return cls(
            target_id=identifier,
            campaign_id=campaign,
            priority=clean(row.get("Priority")),
            full_name=name,
            name_aliases=_split_values(row.get("Name Aliases", "")),
            requested_organization=requested_org,
            canonical_organization=canonical_org,
            organization_aliases=_split_values(row.get("Organization Aliases", "")),
            official_domain=clean(row.get("Official Domain")).casefold(),
            allowed_domains=tuple(
                domain.casefold() for domain in _split_values(row.get("Allowed Domains", ""))
            ),
            requested_role=clean(row.get("Requested Role")),
            relationship_type=clean(row.get("Relationship Type")) or "Current Executive",
            profile_url_hint=clean(row.get("Profile URL Hint")),
            created_at=clean(row.get("Created At")),
            notes=clean(row.get("Notes")),
            schema_version=clean(row.get("Schema Version")) or SCHEMA_VERSION,
        )

    @property
    def names(self) -> tuple[str, ...]:
        return (self.full_name, *self.name_aliases)

    @property
    def organizations(self) -> tuple[str, ...]:
        values = (
            self.canonical_organization,
            self.requested_organization,
            *self.organization_aliases,
        )
        return tuple(dict.fromkeys(value for value in values if value))

    def matches_name(self, value: str) -> bool:
        """Require a complete normalized name/alias; a surname alone never matches."""

        normalized = normalize_name(value)
        return bool(normalized) and normalized in {normalize_name(name) for name in self.names}

    def matches_organization(self, value: str) -> bool:
        normalized = normalize_name(value)
        return bool(normalized) and normalized in {
            normalize_name(organization) for organization in self.organizations
        }

    def to_row(self) -> dict[str, str]:
        return {
            "Schema Version": self.schema_version,
            "Target ID": self.target_id,
            "Campaign ID": self.campaign_id,
            "Priority": self.priority,
            "Full Name": self.full_name,
            "Name Aliases": _join_values(self.name_aliases),
            "Requested Organization": self.requested_organization,
            "Canonical Organization": self.canonical_organization,
            "Organization Aliases": _join_values(self.organization_aliases),
            "Official Domain": self.official_domain,
            "Allowed Domains": _join_values(self.allowed_domains),
            "Requested Role": self.requested_role,
            "Relationship Type": self.relationship_type,
            "Profile URL Hint": self.profile_url_hint,
            "Created At": self.created_at,
            "Notes": self.notes,
        }


@dataclass(frozen=True)
class EmailClaim:
    claim_id: str
    campaign_id: str
    target_id: str
    email: str
    claim_origin: str = "User Provided"
    claimed_at: str = ""
    claim_status: str = "Unreviewed"
    notes: str = ""
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        campaign_id_value: str,
        target_id_value: str,
        email: str,
        **values: object,
    ) -> EmailClaim:
        normalized_email = clean(email).casefold()
        if not EMAIL_RE.fullmatch(normalized_email):
            raise ValueError(f"Invalid claimed email address: {email!r}")
        return cls(
            claim_id=email_claim_id(target_id_value, normalized_email),
            campaign_id=clean(campaign_id_value),
            target_id=clean(target_id_value),
            email=normalized_email,
            **values,
        )

    @classmethod
    def from_row(cls, row: dict[str, str]) -> EmailClaim:
        email = clean(row.get("Email")).casefold()
        if not EMAIL_RE.fullmatch(email):
            raise ValueError(f"Invalid claimed email address: {email!r}")
        target = clean(row.get("Target ID"))
        status = clean(row.get("Claim Status")) or "Unreviewed"
        if status not in CLAIM_STATUSES:
            raise ValueError(f"Invalid Claim Status: {status}")
        return cls(
            claim_id=clean(row.get("Claim ID")) or email_claim_id(target, email),
            campaign_id=clean(row.get("Campaign ID")),
            target_id=target,
            email=email,
            claim_origin=clean(row.get("Claim Origin")) or "User Provided",
            claimed_at=clean(row.get("Claimed At")),
            claim_status=status,
            notes=clean(row.get("Notes")),
            schema_version=clean(row.get("Schema Version")) or SCHEMA_VERSION,
        )

    def to_row(self) -> dict[str, str]:
        return {
            "Schema Version": self.schema_version,
            "Claim ID": self.claim_id,
            "Campaign ID": self.campaign_id,
            "Target ID": self.target_id,
            "Email": self.email,
            "Claim Origin": self.claim_origin,
            "Claimed At": self.claimed_at,
            "Claim Status": self.claim_status,
            "Notes": self.notes,
        }


@dataclass(frozen=True)
class TargetReport:
    report_id: str
    campaign_id: str
    target_id: str
    candidate_id: str = ""
    target_status: str = "Pending"
    identity_match_status: str = "Unverified"
    role_match_status: str = "Unverified"
    person_status: str = "Unknown"
    verified_current_title: str = ""
    verified_current_organization: str = ""
    role_as_of: str = ""
    current_role_evidence_id: str = ""
    email: str = ""
    contact_type: str = ""
    email_evidence_level: str = "E0 Claimed Only"
    email_evidence_id: str = ""
    mailbox_status: str = "Unknown"
    preferred_route_type: str = ""
    preferred_route_url: str = ""
    last_checked_at: str = ""
    notes: str = ""
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        campaign_id_value: str,
        target_id_value: str,
        *,
        role_as_of: str,
        **values: object,
    ) -> TargetReport:
        return cls(
            report_id=target_report_id(campaign_id_value, target_id_value, role_as_of),
            campaign_id=clean(campaign_id_value),
            target_id=clean(target_id_value),
            role_as_of=clean(role_as_of),
            **values,
        )

    @classmethod
    def from_row(cls, row: dict[str, str]) -> TargetReport:
        campaign = clean(row.get("Campaign ID"))
        target = clean(row.get("Target ID"))
        role_as_of = clean(row.get("Role As Of"))
        target_status = clean(row.get("Target Status")) or "Pending"
        evidence_level = clean(row.get("Email Evidence Level")) or "E0 Claimed Only"
        mailbox_status = clean(row.get("Mailbox Status")) or "Unknown"
        if target_status not in TARGET_STATUSES:
            raise ValueError(f"Invalid Target Status: {target_status}")
        if evidence_level not in EMAIL_EVIDENCE_LEVELS:
            raise ValueError(f"Invalid Email Evidence Level: {evidence_level}")
        if mailbox_status not in MAILBOX_STATUSES:
            raise ValueError(f"Invalid Mailbox Status: {mailbox_status}")
        return cls(
            report_id=clean(row.get("Report ID")) or target_report_id(campaign, target, role_as_of),
            campaign_id=campaign,
            target_id=target,
            candidate_id=clean(row.get("Candidate ID")),
            target_status=target_status,
            identity_match_status=clean(row.get("Identity Match Status")) or "Unverified",
            role_match_status=clean(row.get("Role Match Status")) or "Unverified",
            person_status=clean(row.get("Person Status")) or "Unknown",
            verified_current_title=clean(row.get("Verified Current Title")),
            verified_current_organization=clean(row.get("Verified Current Organization")),
            role_as_of=role_as_of,
            current_role_evidence_id=clean(row.get("Current Role Evidence ID")),
            email=clean(row.get("Email")).casefold(),
            contact_type=clean(row.get("Contact Type")),
            email_evidence_level=evidence_level,
            email_evidence_id=clean(row.get("Email Evidence ID")),
            mailbox_status=mailbox_status,
            preferred_route_type=clean(row.get("Preferred Route Type")),
            preferred_route_url=clean(row.get("Preferred Route URL")),
            last_checked_at=clean(row.get("Last Checked At")),
            notes=clean(row.get("Notes")),
            schema_version=clean(row.get("Schema Version")) or SCHEMA_VERSION,
        )

    def to_row(self) -> dict[str, str]:
        return {
            "Schema Version": self.schema_version,
            "Report ID": self.report_id,
            "Campaign ID": self.campaign_id,
            "Target ID": self.target_id,
            "Candidate ID": self.candidate_id,
            "Target Status": self.target_status,
            "Identity Match Status": self.identity_match_status,
            "Role Match Status": self.role_match_status,
            "Person Status": self.person_status,
            "Verified Current Title": self.verified_current_title,
            "Verified Current Organization": self.verified_current_organization,
            "Role As Of": self.role_as_of,
            "Current Role Evidence ID": self.current_role_evidence_id,
            "Email": self.email,
            "Contact Type": self.contact_type,
            "Email Evidence Level": self.email_evidence_level,
            "Email Evidence ID": self.email_evidence_id,
            "Mailbox Status": self.mailbox_status,
            "Preferred Route Type": self.preferred_route_type,
            "Preferred Route URL": self.preferred_route_url,
            "Last Checked At": self.last_checked_at,
            "Notes": self.notes,
        }


def load_campaigns(path: Path) -> list[Campaign]:
    return _unique(
        [Campaign.from_row(row) for row in _strict_rows(path, CAMPAIGN_COLUMNS)],
        "campaign_id",
        "Campaign ID",
    )


def load_targets(path: Path) -> list[IndustryTarget]:
    return _unique(
        [IndustryTarget.from_row(row) for row in _strict_rows(path, TARGET_COLUMNS)],
        "target_id",
        "Target ID",
    )


def load_email_claims(path: Path) -> list[EmailClaim]:
    return _unique(
        [EmailClaim.from_row(row) for row in _strict_rows(path, EMAIL_CLAIM_COLUMNS)],
        "claim_id",
        "Claim ID",
    )


def load_target_reports(path: Path) -> list[TargetReport]:
    return _unique(
        [TargetReport.from_row(row) for row in _strict_rows(path, TARGET_REPORT_COLUMNS)],
        "report_id",
        "Report ID",
    )


def validate_target_relations(
    campaigns: list[Campaign],
    targets: list[IndustryTarget],
    claims: list[EmailClaim],
    reports: list[TargetReport] | None = None,
) -> list[str]:
    """Return deterministic foreign-key errors for the campaign target bundle."""

    errors: list[str] = []
    campaign_ids = {record.campaign_id for record in campaigns}
    targets_by_id = {record.target_id: record for record in targets}
    for target in targets:
        if target.campaign_id not in campaign_ids:
            errors.append(
                f"Target {target.target_id} references missing Campaign ID {target.campaign_id}."
            )
    for claim in claims:
        target = targets_by_id.get(claim.target_id)
        if target is None:
            errors.append(f"Claim {claim.claim_id} references missing Target ID {claim.target_id}.")
        elif claim.campaign_id != target.campaign_id:
            errors.append(f"Claim {claim.claim_id} crosses campaign boundaries.")
    for report in reports or []:
        target = targets_by_id.get(report.target_id)
        if target is None:
            errors.append(
                f"Report {report.report_id} references missing Target ID {report.target_id}."
            )
        elif report.campaign_id != target.campaign_id:
            errors.append(f"Report {report.report_id} crosses campaign boundaries.")
    return errors


# Explicit CSV spellings and short vocabulary aliases are provided for callers
# that prefer either style.
load_campaigns_csv = load_campaigns
load_targets_csv = load_targets
load_email_claims_csv = load_email_claims
load_claims = load_email_claims
load_claims_csv = load_email_claims
load_target_reports_csv = load_target_reports
load_reports = load_target_reports
load_reports_csv = load_target_reports
claim_id = email_claim_id
report_id = target_report_id

# Short aliases keep the public model vocabulary natural without sacrificing
# descriptive class names at call sites.
Target = IndustryTarget
Claim = EmailClaim
Report = TargetReport


__all__ = [
    "Campaign",
    "Claim",
    "EmailClaim",
    "IndustryTarget",
    "Report",
    "Target",
    "TargetReport",
    "campaign_id",
    "claim_id",
    "email_claim_id",
    "load_campaigns",
    "load_campaigns_csv",
    "load_claims",
    "load_claims_csv",
    "load_email_claims",
    "load_email_claims_csv",
    "load_reports",
    "load_reports_csv",
    "load_target_reports",
    "load_target_reports_csv",
    "load_targets",
    "load_targets_csv",
    "target_id",
    "report_id",
    "target_report_id",
    "validate_target_relations",
]
