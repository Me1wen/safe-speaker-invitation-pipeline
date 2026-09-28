"""Auditable claim evidence with deterministic source-snapshot identities."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

from .common import clean, normalize_url
from .schema import (
    CLAIM_POLARITIES,
    CONTACT_OWNERSHIP_TYPES,
    EMAIL_EVIDENCE_LEVELS,
    EMAIL_EVIDENCE_RANK,
    EVIDENCE_COLUMNS,
    EVIDENCE_REVIEW_STATUSES,
    MAILBOX_STATUSES,
    SCHEMA_VERSION,
    TEMPORAL_STATUSES,
)
from .targets import EmailClaim, IndustryTarget

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def content_sha256(content: bytes | str) -> str:
    """Hash exact source bytes (UTF-8 bytes for deterministic text fixtures)."""

    payload = content if isinstance(content, bytes) else content.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_claim(claim_type: str, value: str) -> str:
    normalized = clean(value)
    if clean(claim_type).casefold() == "email address":
        return normalized.casefold()
    if urlparse(normalized).scheme in {"http", "https"}:
        return normalize_url(normalized)
    return normalized.casefold()


def evidence_id(
    target_id_value: str,
    claim_type: str,
    claim_value: str,
    *,
    source_url: str = "",
    source_label: str = "",
    content_hash: str = "",
    claim_id_value: str = "",
) -> str:
    """Identify a claim from one exact source snapshot.

    Retrieval time is deliberately excluded: re-fetching identical bytes keeps
    the same ID and advances ``Last Confirmed At`` instead of duplicating rows.
    """

    source_identity = normalize_url(source_url) or clean(source_label).casefold()
    parts = (
        clean(target_id_value).casefold(),
        clean(claim_id_value).casefold(),
        clean(claim_type).casefold(),
        _normalize_claim(claim_type, claim_value),
        source_identity,
        clean(content_hash).casefold(),
    )
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16].upper()
    return f"EVID-{digest}"


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    campaign_id: str
    target_id: str
    claim_type: str
    claim_value: str
    claim_id: str = ""
    candidate_id: str = ""
    claim_organization: str = ""
    claim_polarity: str = "Context"
    temporal_status: str = "Not Applicable"
    email_evidence_level: str = ""
    contact_ownership: str = "Not Applicable"
    mailbox_status: str = "Unknown"
    source_url: str = ""
    source_label: str = ""
    source_publisher: str = ""
    source_type: str = ""
    source_authority: str = ""
    published_at: str = ""
    effective_from: str = ""
    effective_to: str = ""
    retrieved_at: str = ""
    last_confirmed_at: str = ""
    http_status: str = ""
    content_sha256: str = ""
    source_locator: str = ""
    evidence_summary: str = ""
    extractor_version: str = ""
    review_status: str = "Unreviewed"
    reviewed_by: str = ""
    reviewed_at: str = ""
    notes: str = ""
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        campaign_id_value: str,
        target_id_value: str,
        claim_type: str,
        claim_value: str,
        **values: object,
    ) -> EvidenceRecord:
        source_url = clean(str(values.get("source_url", "")))
        source_label = clean(str(values.get("source_label", "")))
        content_hash = clean(str(values.get("content_sha256", ""))).casefold()
        claim_identifier = clean(str(values.get("claim_id", "")))
        return cls(
            evidence_id=evidence_id(
                target_id_value,
                claim_type,
                claim_value,
                source_url=source_url,
                source_label=source_label,
                content_hash=content_hash,
                claim_id_value=claim_identifier,
            ),
            campaign_id=clean(campaign_id_value),
            target_id=clean(target_id_value),
            claim_type=clean(claim_type),
            claim_value=_normalize_claim(claim_type, claim_value),
            **values,
        )

    @classmethod
    def from_row(cls, row: dict[str, str]) -> EvidenceRecord:
        claim_type = clean(row.get("Claim Type"))
        claim_value = _normalize_claim(claim_type, row.get("Claim Value", ""))
        polarity = clean(row.get("Claim Polarity")) or "Context"
        temporal = clean(row.get("Temporal Status")) or "Not Applicable"
        level = clean(row.get("Email Evidence Level"))
        ownership = clean(row.get("Contact Ownership")) or "Not Applicable"
        mailbox = clean(row.get("Mailbox Status")) or "Unknown"
        review = clean(row.get("Review Status")) or "Unreviewed"
        content_hash = clean(row.get("Content SHA256")).casefold()
        if polarity not in CLAIM_POLARITIES:
            raise ValueError(f"Invalid Claim Polarity: {polarity}")
        if temporal not in TEMPORAL_STATUSES:
            raise ValueError(f"Invalid Temporal Status: {temporal}")
        if level and level not in EMAIL_EVIDENCE_LEVELS:
            raise ValueError(f"Invalid Email Evidence Level: {level}")
        if ownership not in CONTACT_OWNERSHIP_TYPES:
            raise ValueError(f"Invalid Contact Ownership: {ownership}")
        if mailbox not in MAILBOX_STATUSES:
            raise ValueError(f"Invalid Mailbox Status: {mailbox}")
        if review not in EVIDENCE_REVIEW_STATUSES:
            raise ValueError(f"Invalid evidence Review Status: {review}")
        if content_hash and not SHA256_RE.fullmatch(content_hash):
            raise ValueError("Content SHA256 must be 64 lowercase hexadecimal characters.")
        target = clean(row.get("Target ID"))
        claim_identifier = clean(row.get("Claim ID"))
        source_url = clean(row.get("Source URL"))
        source_label = clean(row.get("Source Label"))
        identifier = clean(row.get("Evidence ID")) or evidence_id(
            target,
            claim_type,
            claim_value,
            source_url=source_url,
            source_label=source_label,
            content_hash=content_hash,
            claim_id_value=claim_identifier,
        )
        return cls(
            evidence_id=identifier,
            campaign_id=clean(row.get("Campaign ID")),
            target_id=target,
            claim_id=claim_identifier,
            candidate_id=clean(row.get("Candidate ID")),
            claim_type=claim_type,
            claim_value=claim_value,
            claim_organization=clean(row.get("Claim Organization")),
            claim_polarity=polarity,
            temporal_status=temporal,
            email_evidence_level=level,
            contact_ownership=ownership,
            mailbox_status=mailbox,
            source_url=source_url,
            source_label=source_label,
            source_publisher=clean(row.get("Source Publisher")),
            source_type=clean(row.get("Source Type")),
            source_authority=clean(row.get("Source Authority")),
            published_at=clean(row.get("Published At")),
            effective_from=clean(row.get("Effective From")),
            effective_to=clean(row.get("Effective To")),
            retrieved_at=clean(row.get("Retrieved At")),
            last_confirmed_at=clean(row.get("Last Confirmed At")),
            http_status=clean(row.get("HTTP Status")),
            content_sha256=content_hash,
            source_locator=clean(row.get("Source Locator")),
            evidence_summary=clean(row.get("Evidence Summary")),
            extractor_version=clean(row.get("Extractor Version")),
            review_status=review,
            reviewed_by=clean(row.get("Reviewed By")),
            reviewed_at=clean(row.get("Reviewed At")),
            notes=clean(row.get("Notes")),
            schema_version=clean(row.get("Schema Version")) or SCHEMA_VERSION,
        )

    @property
    def email_rank(self) -> int:
        return EMAIL_EVIDENCE_RANK.get(self.email_evidence_level, -1)

    def to_row(self) -> dict[str, str]:
        return {
            "Schema Version": self.schema_version,
            "Evidence ID": self.evidence_id,
            "Campaign ID": self.campaign_id,
            "Target ID": self.target_id,
            "Claim ID": self.claim_id,
            "Candidate ID": self.candidate_id,
            "Claim Type": self.claim_type,
            "Claim Value": self.claim_value,
            "Claim Organization": self.claim_organization,
            "Claim Polarity": self.claim_polarity,
            "Temporal Status": self.temporal_status,
            "Email Evidence Level": self.email_evidence_level,
            "Contact Ownership": self.contact_ownership,
            "Mailbox Status": self.mailbox_status,
            "Source URL": self.source_url,
            "Source Label": self.source_label,
            "Source Publisher": self.source_publisher,
            "Source Type": self.source_type,
            "Source Authority": self.source_authority,
            "Published At": self.published_at,
            "Effective From": self.effective_from,
            "Effective To": self.effective_to,
            "Retrieved At": self.retrieved_at,
            "Last Confirmed At": self.last_confirmed_at,
            "HTTP Status": self.http_status,
            "Content SHA256": self.content_sha256,
            "Source Locator": self.source_locator,
            "Evidence Summary": self.evidence_summary,
            "Extractor Version": self.extractor_version,
            "Review Status": self.review_status,
            "Reviewed By": self.reviewed_by,
            "Reviewed At": self.reviewed_at,
            "Notes": self.notes,
        }


def load_evidence(path: Path) -> list[EvidenceRecord]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if headers != EVIDENCE_COLUMNS:
            raise ValueError(f"{path} columns do not match the required schema. Found: {headers}")
        records = [
            EvidenceRecord.from_row(
                {column: clean(source.get(column, "")) for column in EVIDENCE_COLUMNS}
            )
            for source in reader
            if any(clean(value) for value in source.values())
        ]
    seen: set[str] = set()
    for record in records:
        if record.evidence_id in seen:
            raise ValueError(f"Duplicate Evidence ID: {record.evidence_id}")
        seen.add(record.evidence_id)
    return records


def merge_evidence(
    existing: list[EvidenceRecord], discovered: list[EvidenceRecord]
) -> list[EvidenceRecord]:
    """Append source snapshots, preserving accepted human review decisions."""

    output = list(existing)
    positions = {record.evidence_id: index for index, record in enumerate(output)}
    for record in discovered:
        index = positions.get(record.evidence_id)
        if index is None:
            positions[record.evidence_id] = len(output)
            output.append(record)
            continue
        old = output[index]
        confirmed = max(old.last_confirmed_at, record.last_confirmed_at, record.retrieved_at)
        output[index] = replace(old, last_confirmed_at=confirmed)
    return output


def best_email_evidence(
    records: list[EvidenceRecord],
    email: str,
    *,
    target_id_value: str = "",
    accepted_only: bool = True,
) -> EvidenceRecord | None:
    """Select evidence only for the exact address; domain/pattern matches do not count."""

    normalized_email = clean(email).casefold()
    eligible = [
        record
        for record in records
        if record.claim_type.casefold() == "email address"
        and record.claim_value.casefold() == normalized_email
        and record.claim_polarity == "Supports"
        and (not target_id_value or record.target_id == target_id_value)
        and (not accepted_only or record.review_status == "Accepted")
    ]
    return max(eligible, key=lambda record: (record.email_rank, record.published_at), default=None)


def validate_evidence_relations(
    records: list[EvidenceRecord],
    targets: list[IndustryTarget],
    claims: list[EmailClaim],
) -> list[str]:
    """Validate target/campaign/claim links and exact claimed-email binding."""

    errors: list[str] = []
    targets_by_id = {target.target_id: target for target in targets}
    claims_by_id = {claim.claim_id: claim for claim in claims}
    for record in records:
        target = targets_by_id.get(record.target_id)
        if target is None:
            errors.append(
                f"Evidence {record.evidence_id} references missing Target ID {record.target_id}."
            )
            continue
        if record.campaign_id != target.campaign_id:
            errors.append(f"Evidence {record.evidence_id} crosses campaign boundaries.")
        if record.claim_id:
            claim = claims_by_id.get(record.claim_id)
            if claim is None:
                errors.append(
                    f"Evidence {record.evidence_id} references missing Claim ID {record.claim_id}."
                )
            elif claim.target_id != record.target_id or claim.campaign_id != record.campaign_id:
                errors.append(
                    f"Evidence {record.evidence_id} does not match its email claim scope."
                )
            elif (
                record.claim_type.casefold() == "email address"
                and record.claim_value.casefold() != claim.email.casefold()
            ):
                errors.append(
                    f"Evidence {record.evidence_id} does not match the exact claimed email."
                )
    return errors


Evidence = EvidenceRecord
load_evidence_csv = load_evidence

__all__ = [
    "Evidence",
    "EvidenceRecord",
    "best_email_evidence",
    "content_sha256",
    "evidence_id",
    "load_evidence",
    "load_evidence_csv",
    "merge_evidence",
    "validate_evidence_relations",
]
