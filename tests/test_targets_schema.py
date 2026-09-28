import csv

import pytest

from speaker_pipeline.evidence import (
    EvidenceRecord,
    best_email_evidence,
    content_sha256,
    evidence_id,
    load_evidence,
    merge_evidence,
    validate_evidence_relations,
)
from speaker_pipeline.schema import (
    CANDIDATE_COLUMNS,
    CANDIDATE_COLUMNS_V1_0,
    DRAFT_COLUMNS,
    DRAFT_COLUMNS_V1_0,
    EMAIL_CLAIM_COLUMNS,
    EVIDENCE_COLUMNS,
    TARGET_COLUMNS,
    V1_0_CANDIDATE_COLUMNS,
    V1_0_DRAFT_COLUMNS,
)
from speaker_pipeline.targets import (
    Campaign,
    EmailClaim,
    IndustryTarget,
    load_email_claims,
    load_targets,
    target_id,
    validate_target_relations,
)


def write_rows(path, columns, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_v11_columns_append_to_exact_v10_schemas():
    assert V1_0_CANDIDATE_COLUMNS == CANDIDATE_COLUMNS_V1_0
    assert V1_0_DRAFT_COLUMNS == DRAFT_COLUMNS_V1_0
    assert CANDIDATE_COLUMNS[: len(CANDIDATE_COLUMNS_V1_0)] == CANDIDATE_COLUMNS_V1_0
    assert DRAFT_COLUMNS[: len(DRAFT_COLUMNS_V1_0)] == DRAFT_COLUMNS_V1_0
    assert CANDIDATE_COLUMNS[-5:] == [
        "Revision",
        "Approval Hash",
        "Approved At",
        "Approved By",
        "Schema Version",
    ]
    assert DRAFT_COLUMNS[-6:] == [
        "Campaign ID",
        "Revision",
        "Approval Hash",
        "Approved At",
        "Approved By",
        "Schema Version",
    ]


def test_target_ids_are_stable_and_matching_requires_a_full_name():
    first = target_id("CMP-1", "C.C. Wei", "TSMC")
    second = target_id("cmp-1", "C. C. Wei", "tsmc")
    assert first == second

    target = IndustryTarget.create(
        "CMP-1",
        "C.C. Wei",
        "TSMC",
        "CEO",
        name_aliases=("Che-Chia Wei",),
        canonical_organization="Taiwan Semiconductor Manufacturing Company",
        organization_aliases=("TSMC",),
        official_domain="tsmc.com",
        allowed_domains=("tsmc.com", "pr.tsmc.com"),
    )
    assert target.matches_name("C C Wei")
    assert target.matches_name("Che-Chia Wei")
    assert not target.matches_name("Wei")
    assert target.allowed_domains == ("tsmc.com", "pr.tsmc.com")
    assert target.to_row()["Allowed Domains"] == "tsmc.com; pr.tsmc.com"


def test_strict_target_loader_preserves_all_people_at_shared_companies(tmp_path):
    campaign = Campaign.create("Executive speaker verification", research_as_of="2026-08-16")
    targets = [
        IndustryTarget.create(
            campaign.campaign_id,
            f"Executive {index}",
            f"Company {index % 10}",
            "CEO" if index < 10 else "Founder",
            official_domain=f"company{index % 10}.example",
            allowed_domains=(f"company{index % 10}.example",),
        )
        for index in range(16)
    ]
    path = tmp_path / "targets.csv"
    write_rows(path, TARGET_COLUMNS, [target.to_row() for target in targets])
    loaded = load_targets(path)
    assert len(loaded) == 16
    assert len({target.target_id for target in loaded}) == 16
    assert len({target.requested_organization for target in loaded}) == 10

    bad_path = tmp_path / "bad_targets.csv"
    write_rows(bad_path, list(reversed(TARGET_COLUMNS)), [])
    with pytest.raises(ValueError, match="required schema"):
        load_targets(bad_path)


def test_thirteen_claims_keep_exact_variants_separate(tmp_path):
    campaign_id_value = "CMP-TEST"
    targets = [
        IndustryTarget.create(campaign_id_value, f"Person {index}", "Example Co", "CEO")
        for index in range(11)
    ]
    claims = [
        EmailClaim.create(
            campaign_id_value,
            targets[index % len(targets)].target_id,
            f"person{index}@example.com",
            claim_origin="Manager-provided Copilot list",
        )
        for index in range(13)
    ]
    path = tmp_path / "claims.csv"
    write_rows(path, EMAIL_CLAIM_COLUMNS, [claim.to_row() for claim in claims])
    loaded = load_email_claims(path)
    assert len(loaded) == 13
    assert len({claim.claim_id for claim in loaded}) == 13
    assert all(claim.claim_status == "Unreviewed" for claim in loaded)


def test_evidence_id_uses_exact_snapshot_but_not_retrieval_time():
    source_hash = content_sha256(b"official source bytes")
    first = EvidenceRecord.create(
        "CMP-1",
        "TGT-1",
        "Email Address",
        "Person@Example.com",
        source_url="https://example.com/leader",
        content_sha256=source_hash,
        retrieved_at="2026-08-16T10:00:00+00:00",
    )
    second = EvidenceRecord.create(
        "CMP-1",
        "TGT-1",
        "Email Address",
        "person@example.com",
        source_url="https://www.example.com/leader/",
        content_sha256=source_hash,
        retrieved_at="2026-08-17T10:00:00+00:00",
    )
    assert first.evidence_id == second.evidence_id
    assert first.claim_value == "person@example.com"
    assert first.evidence_id != evidence_id(
        "TGT-1",
        "Email Address",
        "person@example.com",
        source_url="https://example.com/leader",
        content_hash=content_sha256(b"changed bytes"),
    )


def test_email_evidence_is_exact_and_mailbox_status_is_independent():
    historical = EvidenceRecord.create(
        "CMP-1",
        "TGT-1",
        "Email Address",
        "zuck@fb.example",
        source_url="https://records.example/old",
        content_sha256=content_sha256("old"),
        email_evidence_level="E2 Exact Historical",
        claim_polarity="Supports",
        review_status="Accepted",
    )
    current = EvidenceRecord.create(
        "CMP-1",
        "TGT-1",
        "Email Address",
        "zuck@meta.example",
        source_url="https://meta.example/contact",
        content_sha256=content_sha256("current"),
        email_evidence_level="E4 Exact Current Official",
        claim_polarity="Supports",
        mailbox_status="Unknown",
        review_status="Accepted",
    )
    mx = EvidenceRecord.create(
        "CMP-1",
        "TGT-1",
        "Domain Mail",
        "MX Present",
        source_label="DNS observation",
        mailbox_status="Unknown",
    )
    records = [historical, current, mx]
    assert best_email_evidence(records, "zuck@meta.example") == current
    assert best_email_evidence(records, "zuck@fb.example") == historical
    assert best_email_evidence(records, "other@meta.example") is None
    assert mx.mailbox_status == "Unknown"


def test_repeat_snapshot_preserves_review_and_updates_last_confirmed():
    old = EvidenceRecord.create(
        "CMP-1",
        "TGT-1",
        "Role",
        "CEO",
        source_url="https://example.com/bio",
        content_sha256=content_sha256("same"),
        retrieved_at="2026-08-16T10:00:00+00:00",
        last_confirmed_at="2026-08-16T10:00:00+00:00",
        claim_polarity="Supports",
        temporal_status="Current",
        review_status="Accepted",
        reviewed_by="Reviewer",
    )
    repeat = EvidenceRecord.create(
        "CMP-1",
        "TGT-1",
        "Role",
        "CEO",
        source_url="https://example.com/bio",
        content_sha256=content_sha256("same"),
        retrieved_at="2026-08-17T10:00:00+00:00",
        last_confirmed_at="2026-08-17T10:00:00+00:00",
        claim_polarity="Contradicts",
        temporal_status="Former",
    )
    result = merge_evidence([old], [repeat])
    assert len(result) == 1
    assert result[0].review_status == "Accepted"
    assert result[0].claim_polarity == "Supports"
    assert result[0].temporal_status == "Current"
    assert result[0].last_confirmed_at == "2026-08-17T10:00:00+00:00"


def test_evidence_csv_is_strict_and_relations_bind_the_exact_claim(tmp_path):
    campaign = Campaign.create("One", research_as_of="2026-08-16")
    target = IndustryTarget.create(campaign.campaign_id, "Ada Example", "Example", "CEO")
    claim = EmailClaim.create(campaign.campaign_id, target.target_id, "ada@example.com")
    evidence = EvidenceRecord.create(
        campaign.campaign_id,
        target.target_id,
        "Email Address",
        claim.email,
        claim_id=claim.claim_id,
        source_url="https://example.com/ada",
        content_sha256=content_sha256("page"),
        email_evidence_level="E4 Exact Current Official",
        claim_polarity="Supports",
    )
    path = tmp_path / "evidence.csv"
    write_rows(path, EVIDENCE_COLUMNS, [evidence.to_row()])
    assert load_evidence(path) == [evidence]
    assert validate_target_relations([campaign], [target], [claim]) == []
    assert validate_evidence_relations([evidence], [target], [claim]) == []

    mismatched = EvidenceRecord.create(
        campaign.campaign_id,
        target.target_id,
        "Email Address",
        "different@example.com",
        claim_id=claim.claim_id,
    )
    errors = validate_evidence_relations([mismatched], [target], [claim])
    assert any("exact claimed email" in error for error in errors)


def test_current_and_upcoming_roles_remain_separate_assertions():
    current = EvidenceRecord.create(
        "CMP-1",
        "TGT-1",
        "Role",
        "Chief Executive Officer",
        claim_organization="Example",
        temporal_status="Current",
        effective_to="2026-09-01",
    )
    upcoming = EvidenceRecord.create(
        "CMP-1",
        "TGT-1",
        "Role",
        "Executive Chair",
        claim_organization="Example",
        temporal_status="Upcoming",
        effective_from="2026-09-01",
    )
    assert current.evidence_id != upcoming.evidence_id
    assert current.temporal_status == "Current"
    assert upcoming.temporal_status == "Upcoming"
    assert current.effective_to == upcoming.effective_from
