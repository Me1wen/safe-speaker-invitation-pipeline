from __future__ import annotations

from copy import deepcopy

import pytest

from speaker_pipeline.approvals import approve_row
from speaker_pipeline.drafts import generate_drafts
from speaker_pipeline.schema import CANDIDATE_COLUMNS, DRAFT_COLUMNS, EVIDENCE_COLUMNS
from speaker_pipeline.validation import approved_candidates, validate_candidates


def invitation_config(*, campaign_id: str = "CMP-ONE") -> dict[str, str]:
    return {
        "campaign_id": campaign_id,
        "event_name": "Safety Forum",
        "event_host": "Example Host",
        "event_date": "October 1, 2026",
        "event_location": "San Francisco",
        "event_description": "a small, consent-based leadership forum",
        "sender_name": "Alex Chen",
        "sender_title": "Program Director",
        "sender_organization": "Example Host",
        "sender_email": "alex@example.org",
        "reply_to": "events@example.org",
        "subject_template": "Invitation for {full_name} to {event_name}",
        "direct_body_template": "Dear {salutation},\n\nPlease join {event_name}.\n\n{sender_name}",
        "routed_body_template": (
            "Dear {route_greeting},\n\nPlease forward this invitation to {full_name}."
        ),
    }


def _evidence(
    identifier: str,
    claim_type: str,
    claim_value: str,
    *,
    temporal_status: str = "Current",
) -> dict[str, str]:
    row = {column: "" for column in EVIDENCE_COLUMNS}
    row.update(
        {
            "Schema Version": "1.1",
            "Evidence ID": identifier,
            "Campaign ID": "CMP-ONE",
            "Target ID": "TGT-ONE",
            "Candidate ID": "IND-ONE",
            "Claim Type": claim_type,
            "Claim Value": claim_value,
            "Claim Polarity": "Supports",
            "Temporal Status": temporal_status,
            "Contact Ownership": "Not Applicable",
            "Mailbox Status": "Unknown",
            "Source URL": "https://example.com/leader",
            "Review Status": "Accepted",
            "Reviewed By": "evidence-reviewer@example.org",
            "Reviewed At": "2026-08-20T12:00:00+00:00",
        }
    )
    return row


def targeted_bundle() -> tuple[dict[str, str], list[dict[str, str]]]:
    candidate = {column: "" for column in CANDIDATE_COLUMNS}
    candidate.update(
        {
            "Candidate ID": "IND-ONE",
            "Speaker Type": "Industry",
            "Review Status": "Draft",
            "Full Name": "Example Leader",
            "Organization": "Example Co",
            "Title": "CEO",
            "Expertise": "Responsible technology",
            "Topic Fit": "responsible technology",
            "Preferred Salutation": "Example Leader",
            "Email": "leader@example.com",
            "Contact Type": "Direct",
            "Email Source URL": "https://example.com/leader",
            "Profile URL": "https://example.com/leader",
            "Discovery Source URL": "https://example.com/leaders",
            "Last Checked": "2026-08-20",
            "Campaign ID": "CMP-ONE",
            "Target ID": "TGT-ONE",
            "Role Temporal Status": "Current",
            "Role As Of": "2026-08-20",
            "Identity Evidence ID": "EVID-IDENTITY",
            "Role Evidence ID": "EVID-ROLE",
            "Email Evidence Level": "E4 Exact Current Official",
            "Email Evidence ID": "EVID-EMAIL",
            "Mailbox Status": "Unknown",
            "Revision": "1",
            "Schema Version": "1.1",
        }
    )
    evidence = [
        _evidence(
            "EVID-IDENTITY",
            "Identity",
            "Example Leader",
            temporal_status="Not Applicable",
        ),
        _evidence("EVID-ROLE", "Current Role", "CEO"),
        _evidence("EVID-EMAIL", "Email Address", "leader@example.com"),
    ]
    evidence[2]["Email Evidence Level"] = "E4 Exact Current Official"
    evidence[2]["Contact Ownership"] = "Direct Person"
    approve_row(candidate, "candidate-reviewer@example.org", record_type="candidate")
    return candidate, evidence


def test_targeted_approval_requires_exact_accepted_current_support():
    candidate, evidence = targeted_bundle()

    assert validate_candidates([candidate], evidence) == []
    assert approved_candidates([candidate], evidence) == [candidate]


@pytest.mark.parametrize(
    ("record_index", "field", "value", "issue_fragment"),
    [
        (0, "Review Status", "Unreviewed", "Only Accepted evidence"),
        (1, "Review Status", "Superseded", "Only Accepted evidence"),
        (2, "Claim Polarity", "Contradicts", "Only supporting evidence"),
        (0, "Temporal Status", "Former", "temporal status must be"),
        (1, "Temporal Status", "Former", "temporal status must be"),
        (2, "Temporal Status", "Historical Fact", "temporal status must be"),
    ],
)
def test_noncurrent_or_nonaccepted_evidence_fails_closed(
    record_index: int, field: str, value: str, issue_fragment: str
):
    candidate, evidence = targeted_bundle()
    evidence[record_index][field] = value

    issues = validate_candidates([candidate], evidence)

    assert any(issue_fragment in issue["Issue"] for issue in issues)
    assert approved_candidates([candidate], evidence) == []


@pytest.mark.parametrize(
    ("record_index", "field", "value", "issue_fragment"),
    [
        (0, "Candidate ID", "", "exact Candidate ID"),
        (1, "Campaign ID", "CMP-OTHER", "different campaign"),
        (1, "Target ID", "TGT-OTHER", "different target"),
        (0, "Claim Value", "Different Leader", "exact claim value"),
        (1, "Claim Value", "Chair", "exact claim value"),
        (2, "Claim Value", "other@example.com", "exact claim value"),
        (2, "Contact Ownership", "Department Route", "ownership must be"),
        (2, "Email Evidence Level", "E3 Exact Current Authoritative", "levels do not match"),
        (2, "Mailbox Status", "Delivered", "mailbox statuses do not match"),
        (2, "Mailbox Status", "Hard Bounce", "bounced or suppressed"),
        (2, "Mailbox Status", "Unrecognized", "missing or unsupported"),
    ],
)
def test_evidence_scope_and_contact_fields_must_match_exactly(
    record_index: int, field: str, value: str, issue_fragment: str
):
    candidate, evidence = targeted_bundle()
    evidence[record_index][field] = value

    issues = validate_candidates([candidate], evidence)

    assert any(issue_fragment in issue["Issue"] for issue in issues)
    assert approved_candidates([candidate], evidence) == []


@pytest.mark.parametrize("mailbox_status", ["Hard Bounce", "Suppressed"])
def test_candidate_and_evidence_blocked_mailbox_statuses_cannot_be_approved(
    mailbox_status: str,
):
    candidate, evidence = targeted_bundle()
    candidate["Mailbox Status"] = mailbox_status
    evidence[2]["Mailbox Status"] = mailbox_status
    approve_row(candidate, "candidate-reviewer@example.org", record_type="candidate")

    issues = validate_candidates([candidate], evidence)

    assert any(issue["Field"] == "Mailbox Status" for issue in issues)
    assert approved_candidates([candidate], evidence) == []


def test_historical_target_requires_explicit_opt_in_and_matching_role_evidence():
    candidate, evidence = targeted_bundle()
    candidate["Title"] = "Former CEO"
    candidate["Role Temporal Status"] = "Historical Fact"
    evidence[1]["Claim Type"] = "Historical Role"
    evidence[1]["Claim Value"] = "Former CEO"
    evidence[1]["Temporal Status"] = "Former"
    approve_row(candidate, "candidate-reviewer@example.org", record_type="candidate")

    assert approved_candidates([candidate], evidence) == []
    assert approved_candidates([candidate], evidence, allow_historical_targets=True) == [candidate]


def test_draft_generation_rejects_cross_campaign_candidate():
    candidate, evidence = targeted_bundle()
    candidate["Campaign ID"] = "CMP-TWO"
    for record in evidence:
        record["Campaign ID"] = "CMP-TWO"
    approve_row(candidate, "candidate-reviewer@example.org", record_type="candidate")

    with pytest.raises(ValueError, match="belongs to campaign CMP-TWO"):
        generate_drafts([candidate], invitation_config(), evidence_records=evidence)


def test_only_true_legacy_candidate_gets_review_only_compatibility():
    candidate, _evidence_rows = targeted_bundle()
    for field in (
        "Campaign ID",
        "Target ID",
        "Role Temporal Status",
        "Role As Of",
        "Identity Evidence ID",
        "Role Evidence ID",
        "Email Evidence Level",
        "Email Evidence ID",
        "Mailbox Status",
        "Revision",
        "Approval Hash",
        "Approved At",
        "Approved By",
    ):
        candidate[field] = ""
    candidate["Schema Version"] = "1.0"

    drafts = generate_drafts([candidate], invitation_config())
    assert len(drafts) == 1
    assert drafts[0]["Campaign ID"] == "CMP-ONE"
    assert drafts[0]["Candidate Approval Hash"] == ""
    assert drafts[0]["Campaign Policy Hash"] == ""

    with pytest.raises(ValueError, match="campaign <blank>"):
        generate_drafts(
            [candidate],
            invitation_config(),
            allow_legacy_unscoped_candidates=False,
        )

    candidate["Schema Version"] = "1.1"
    approve_row(candidate, "candidate-reviewer@example.org", record_type="candidate")
    with pytest.raises(ValueError, match="campaign <blank>"):
        generate_drafts(
            [candidate],
            invitation_config(),
            allow_legacy_unscoped_candidates=True,
        )


def test_generated_draft_binds_candidate_policy_and_sender_identity():
    candidate, evidence = targeted_bundle()

    draft = generate_drafts(
        [candidate],
        invitation_config(),
        evidence_records=evidence,
        campaign_policy_hash="sha256-policy:abc123",
    )[0]

    assert draft["Candidate Approval Hash"] == candidate["Approval Hash"]
    assert draft["Campaign Policy Hash"] == "sha256-policy:abc123"
    assert draft["Sender Email"] == "alex@example.org"
    assert draft["Sender Name"] == "Alex Chen"
    assert draft["Reply-To"] == "events@example.org"

    no_reply_to = invitation_config()
    no_reply_to.pop("reply_to")
    assert (
        generate_drafts(
            [candidate],
            no_reply_to,
            evidence_records=evidence,
            campaign_policy_hash="sha256-policy:abc123",
        )[0]["Reply-To"]
        == ""
    )


def test_duplicate_evidence_id_is_ambiguous_and_blocks_approval():
    candidate, evidence = targeted_bundle()
    evidence.append(deepcopy(evidence[2]))

    issues = validate_candidates([candidate], evidence)

    assert any("duplicated" in issue["Issue"] for issue in issues)
    assert approved_candidates([candidate], evidence) == []


def _attempted_draft(identifier: str, candidate_id: str, status: str) -> dict[str, str]:
    row = {column: "" for column in DRAFT_COLUMNS}
    row.update(
        {
            "Draft ID": identifier,
            "Candidate ID": candidate_id,
            "Draft Status": status,
            "Campaign ID": "CMP-ONE",
            "To Email": f"{candidate_id.casefold()}@example.com",
            "Subject": "Prior invitation",
            "Body Text": "Prior body\n\nwith audit history.",
            "Last Attempt At": "2026-08-20T12:00:00+00:00",
            "Schema Version": "1.1",
            "Provider Receipt": f"receipt-{identifier}",
        }
    )
    return row


def test_all_delivery_attempts_are_preserved_even_without_current_candidates():
    attempted = [
        _attempted_draft("DRAFT-SENDING", "IND-SENDING", "Sending"),
        _attempted_draft("DRAFT-SENT", "IND-SENT", "Sent"),
        _attempted_draft("DRAFT-FAILED", "IND-FAILED", "Failed"),
        _attempted_draft("DRAFT-RESOLVED", "IND-RESOLVED", "Approved"),
    ]

    result = generate_drafts([], invitation_config(), deepcopy(attempted))

    assert [row["Draft ID"] for row in result] == [row["Draft ID"] for row in attempted]
    assert result[2]["Draft Status"] == "Failed"
    assert result[3]["Last Attempt At"] == "2026-08-20T12:00:00+00:00"
    assert result[0]["Provider Receipt"] == "receipt-DRAFT-SENDING"


def test_malformed_existing_ledger_fails_without_silently_deleting_rows():
    malformed = _attempted_draft("DRAFT-UNKNOWN", "IND-ONE", "Unknown Result")
    with pytest.raises(ValueError, match="Invalid existing Draft Status"):
        generate_drafts([], invitation_config(), [malformed])

    missing_scope = _attempted_draft("DRAFT-NOSCOPE", "IND-ONE", "Failed")
    missing_scope["Campaign ID"] = ""
    with pytest.raises(ValueError, match="manual reconciliation"):
        generate_drafts([], invitation_config(), [missing_scope])
