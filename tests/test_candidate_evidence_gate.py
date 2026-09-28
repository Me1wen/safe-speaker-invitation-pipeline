from copy import deepcopy

from speaker_pipeline.approvals import approve_row
from speaker_pipeline.evidence import EvidenceRecord
from speaker_pipeline.schema import CANDIDATE_COLUMNS
from speaker_pipeline.validation import approved_candidates, validate_candidates


def _bundle():
    candidate = {column: "" for column in CANDIDATE_COLUMNS}
    candidate.update(
        {
            "Candidate ID": "IND-ONE",
            "Speaker Type": "Industry",
            "Review Status": "Draft",
            "Full Name": "Example Leader",
            "Organization": "Example Co",
            "Title": "CEO",
            "Topic Fit": "responsible technology",
            "Preferred Salutation": "Example Leader",
            "Email": "leader@example.com",
            "Contact Type": "Direct",
            "Email Source URL": "https://example.com/leader",
            "Profile URL": "https://example.com/leader",
            "Campaign ID": "CMP-ONE",
            "Target ID": "TGT-ONE",
            "Role Temporal Status": "Current",
            "Role As Of": "2026-08-16",
            "Email Evidence Level": "E4 Exact Current Official",
            "Mailbox Status": "Unknown",
            "Revision": "1",
            "Schema Version": "1.1",
        }
    )
    identity = EvidenceRecord.create(
        "CMP-ONE",
        "TGT-ONE",
        "Identity",
        "Example Leader",
        candidate_id="IND-ONE",
        claim_polarity="Supports",
        temporal_status="Not Applicable",
        source_url="https://example.com/leader",
        review_status="Accepted",
        reviewed_by="Evidence Reviewer",
        reviewed_at="2026-08-16T00:00:00+00:00",
    )
    role = EvidenceRecord.create(
        "CMP-ONE",
        "TGT-ONE",
        "Current Role",
        "CEO",
        candidate_id="IND-ONE",
        claim_polarity="Supports",
        temporal_status="Current",
        source_url="https://example.com/leader",
        review_status="Accepted",
        reviewed_by="Evidence Reviewer",
        reviewed_at="2026-08-16T00:00:00+00:00",
    )
    email = EvidenceRecord.create(
        "CMP-ONE",
        "TGT-ONE",
        "Email Address",
        "leader@example.com",
        candidate_id="IND-ONE",
        claim_polarity="Supports",
        temporal_status="Current",
        email_evidence_level="E4 Exact Current Official",
        contact_ownership="Direct Person",
        source_url="https://example.com/leader",
        review_status="Accepted",
        reviewed_by="Evidence Reviewer",
        reviewed_at="2026-08-16T00:00:00+00:00",
    )
    candidate["Identity Evidence ID"] = identity.evidence_id
    candidate["Role Evidence ID"] = role.evidence_id
    candidate["Email Evidence ID"] = email.evidence_id
    approve_row(candidate, "reviewer@example.org", record_type="candidate")
    return candidate, identity, role, email


def test_targeted_approval_requires_matching_evidence_ledger():
    candidate, identity, role, email = _bundle()
    assert approved_candidates([candidate], [identity, role, email]) == [candidate]
    issues = validate_candidates([candidate])
    assert any(issue["Field"] == "Evidence Ledger" for issue in issues)


def test_email_evidence_must_bind_exact_address_and_person_ownership():
    candidate, identity, role, email = _bundle()
    wrong = deepcopy(email)
    object.__setattr__(wrong, "claim_value", "other@example.com")
    issues = validate_candidates([candidate], [identity, role, wrong])
    assert any("exact email" in issue["Issue"] for issue in issues)

    department = deepcopy(email)
    object.__setattr__(department, "contact_ownership", "Department Route")
    issues = validate_candidates([candidate], [identity, role, department])
    assert any(issue["Field"] == "Contact Type" for issue in issues)
