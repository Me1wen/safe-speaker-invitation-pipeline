from copy import deepcopy
from dataclasses import replace
from datetime import date

import pytest

from speaker_pipeline.approvals import approve_row
from speaker_pipeline.drafts import generate_drafts
from speaker_pipeline.evidence import EvidenceRecord
from speaker_pipeline.policy import (
    DeliveryPolicyError,
    SuppressionRecord,
    campaign_policy_hash,
    validate_delivery_policy,
)
from speaker_pipeline.schema import CANDIDATE_COLUMNS
from speaker_pipeline.targets import Campaign


def _bundle():
    campaign = Campaign(
        campaign_id="CMP-SAFE",
        campaign_name="Reviewed speaker invitations",
        campaign_status="Active",
        purpose="Invite one reviewed speaker",
        owner="Program Director",
        sender_organization="Example Host",
        research_as_of="2026-08-22",
        outreach_not_before="2026-08-01",
        outreach_not_after="2026-08-31",
        minimum_direct_email_evidence="E4 Exact Current Official",
        allow_historical_targets=False,
        allow_department_routes=False,
        max_messages=2,
        created_at="2026-08-01T00:00:00+00:00",
        updated_at="2026-08-22T00:00:00+00:00",
    )
    candidate = {column: "" for column in CANDIDATE_COLUMNS}
    candidate.update(
        {
            "Candidate ID": "IND-SAFE",
            "Speaker Type": "Industry",
            "Review Status": "Draft",
            "Full Name": "Ada Example",
            "Organization": "Example Co",
            "Title": "Chief Scientist",
            "Topic Fit": "responsible technology",
            "Preferred Salutation": "Ada Example",
            "Email": "ada@example.com",
            "Contact Type": "Direct",
            "Email Source URL": "https://example.com/ada",
            "Profile URL": "https://example.com/ada",
            "Campaign ID": campaign.campaign_id,
            "Target ID": "TGT-SAFE",
            "Role Temporal Status": "Current",
            "Role As Of": "2026-08-22",
            "Email Evidence Level": "E4 Exact Current Official",
            "Mailbox Status": "Unknown",
            "Revision": "1",
            "Schema Version": "1.1",
        }
    )
    common = {
        "candidate_id": candidate["Candidate ID"],
        "claim_polarity": "Supports",
        "review_status": "Accepted",
        "reviewed_by": "Evidence Reviewer",
        "reviewed_at": "2026-08-22T00:00:00+00:00",
        "source_url": "https://example.com/ada",
        "retrieved_at": "2026-08-22T00:00:00+00:00",
        "last_confirmed_at": "2026-08-22T00:00:00+00:00",
    }
    identity = EvidenceRecord.create(
        campaign.campaign_id,
        candidate["Target ID"],
        "Identity",
        candidate["Full Name"],
        temporal_status="Not Applicable",
        **common,
    )
    role = EvidenceRecord.create(
        campaign.campaign_id,
        candidate["Target ID"],
        "Current Role",
        candidate["Title"],
        temporal_status="Current",
        **common,
    )
    email = EvidenceRecord.create(
        campaign.campaign_id,
        candidate["Target ID"],
        "Email Address",
        candidate["Email"],
        temporal_status="Current",
        email_evidence_level="E4 Exact Current Official",
        contact_ownership="Direct Person",
        mailbox_status="Unknown",
        **common,
    )
    candidate["Identity Evidence ID"] = identity.evidence_id
    candidate["Role Evidence ID"] = role.evidence_id
    candidate["Email Evidence ID"] = email.evidence_id
    approve_row(
        candidate,
        "Candidate Reviewer",
        record_type="candidate",
        approved_at="2026-08-22T01:00:00+00:00",
    )
    config = {
        "campaign_id": campaign.campaign_id,
        "event_name": "AI Forum",
        "event_host": "Example Host",
        "event_date": "October 1, 2026",
        "event_location": "San Francisco",
        "event_description": "a small reviewed forum",
        "sender_name": "Alex Chen",
        "sender_title": "Program Director",
        "sender_organization": "Example Host",
        "sender_email": "alex@example.org",
        "subject_template": "Invitation for {full_name}",
        "direct_body_template": "Dear {salutation},\n\nPlease join {event_name}.\n\n{sender_name}",
        "routed_body_template": "Dear {route_greeting},\n\nPlease forward this invitation.",
    }
    evidence = [identity, role, email]
    drafts = generate_drafts(
        [candidate],
        config,
        evidence_records=evidence,
        campaign_policy_hash=campaign_policy_hash(campaign),
    )
    approve_row(
        drafts[0],
        "Draft Reviewer",
        record_type="draft",
        approved_at="2026-08-22T02:00:00+00:00",
    )
    return campaign, candidate, evidence, drafts


def _authorization(campaign, candidate, evidence, drafts, suppressions=()):
    return validate_delivery_policy(
        drafts,
        campaign,
        [candidate],
        evidence,
        suppressions,
        campaign_id=campaign.campaign_id,
        as_of=date(2026, 8, 22),
    )


def test_active_current_bound_batch_is_authorized():
    campaign, candidate, evidence, drafts = _bundle()
    authorization = _authorization(campaign, candidate, evidence, drafts)
    assert authorization.selected == 1
    assert authorization.attempted == 0
    assert authorization.remaining_after_batch == 1


@pytest.mark.parametrize(
    "status", ["Draft", "Research", "Review", "Approved", "Closed", "Cancelled"]
)
def test_only_active_campaign_can_deliver(status):
    campaign, candidate, evidence, drafts = _bundle()
    with pytest.raises(DeliveryPolicyError, match="only Active"):
        _authorization(replace(campaign, campaign_status=status), candidate, evidence, drafts)


def test_policy_change_invalidates_reviewed_draft():
    campaign, candidate, evidence, drafts = _bundle()
    changed = replace(campaign, max_messages=3, updated_at="2026-08-22T03:00:00+00:00")
    with pytest.raises(DeliveryPolicyError, match="current campaign policy"):
        _authorization(changed, candidate, evidence, drafts)


def test_candidate_reapproval_invalidates_existing_draft_binding():
    campaign, candidate, evidence, drafts = _bundle()
    changed = deepcopy(candidate)
    changed["Notes"] = "Materially changed after draft review"
    approve_row(changed, "Second Reviewer", record_type="candidate")
    with pytest.raises(DeliveryPolicyError, match="current approval"):
        _authorization(campaign, changed, evidence, drafts)


def test_stale_or_expired_evidence_blocks_delivery():
    campaign, candidate, evidence, drafts = _bundle()
    stale = [replace(evidence[0], last_confirmed_at="2026-08-21T00:00:00+00:00"), *evidence[1:]]
    with pytest.raises(DeliveryPolicyError, match="evidence is stale"):
        _authorization(campaign, candidate, stale, drafts)

    expired = [*evidence[:2], replace(evidence[2], effective_to="2026-08-21")]
    with pytest.raises(DeliveryPolicyError, match="evidence has expired"):
        _authorization(campaign, candidate, expired, drafts)


@pytest.mark.parametrize(
    ("scope", "value"),
    [
        ("Email", "ada@example.com"),
        ("Domain", "example.com"),
        ("Target ID", "TGT-SAFE"),
        ("Candidate ID", "IND-SAFE"),
    ],
)
def test_active_global_suppression_blocks_every_supported_scope(scope, value):
    campaign, candidate, evidence, drafts = _bundle()
    suppression = SuppressionRecord.from_row(
        {
            "Schema Version": "1.1",
            "Suppression ID": f"SUP-{scope}",
            "Scope": scope,
            "Value": value,
            "Reason": "Recipient requested no further contact",
            "Status": "Active",
            "Created At": "2026-08-22T00:00:00+00:00",
            "Created By": "Program Director",
        }
    )
    with pytest.raises(DeliveryPolicyError, match="active suppression"):
        _authorization(campaign, candidate, evidence, drafts, [suppression])


def test_zero_campaign_cap_authorizes_nothing():
    campaign, candidate, evidence, drafts = _bundle()
    with pytest.raises(DeliveryPolicyError, match="must be positive"):
        _authorization(replace(campaign, max_messages=0), candidate, evidence, drafts)


def test_attempted_rows_consume_campaign_cap():
    campaign, candidate, evidence, drafts = _bundle()
    attempted = deepcopy(drafts[0])
    attempted["Draft ID"] = "DRAFT-PRIOR"
    attempted["Draft Status"] = "Failed"
    attempted["Last Attempt At"] = "2026-08-21T00:00:00+00:00"
    with pytest.raises(DeliveryPolicyError, match="Campaign cap exceeded"):
        _authorization(
            replace(campaign, max_messages=1),
            candidate,
            evidence,
            [attempted, *drafts],
        )
