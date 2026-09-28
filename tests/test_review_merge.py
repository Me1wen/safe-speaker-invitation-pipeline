from copy import deepcopy

import pytest

from speaker_pipeline.approvals import approve_row
from speaker_pipeline.review import ReviewMergeError, merge_review_rows
from speaker_pipeline.schema import DRAFT_COLUMNS


def _draft(status="Draft"):
    row = {column: "" for column in DRAFT_COLUMNS}
    row.update(
        {
            "Draft ID": "DRAFT-1",
            "Candidate ID": "IND-1",
            "Draft Status": status,
            "Campaign ID": "CAMPAIGN-1",
            "Revision": "1",
            "To Email": "person@example.com",
            "Subject": "Invitation",
            "Body Text": "First paragraph.\n\nSecond paragraph.",
            "Schema Version": "1.1",
        }
    )
    return row


def test_approval_transition_stamps_reviewer_hash_and_revision():
    current = _draft()
    reviewed = deepcopy(current)
    reviewed["Draft Status"] = "Approved"
    result = merge_review_rows([current], [reviewed], kind="drafts", approver="Reviewer")
    assert result[0]["Revision"] == "2"
    assert result[0]["Approved By"] == "Reviewer"
    assert result[0]["Approval Hash"].startswith("sha256-v2:")


def test_editing_an_approved_payload_without_unapproving_is_rejected():
    current = _draft("Approved")
    approve_row(current, "Reviewer", record_type="draft")
    reviewed = deepcopy(current)
    reviewed["Body Text"] = "Changed after approval"
    with pytest.raises(ReviewMergeError, match="Approved content changed"):
        merge_review_rows([current], [reviewed], kind="drafts", approver="Reviewer")


def test_stale_and_protected_rows_are_rejected():
    current = _draft()
    stale = deepcopy(current)
    stale["Revision"] = "0"
    with pytest.raises(ReviewMergeError, match="Stale review row"):
        merge_review_rows([current], [stale], kind="drafts")

    sent = _draft("Sent")
    modified = deepcopy(sent)
    modified["Subject"] = "Changed"
    with pytest.raises(ReviewMergeError, match="Protected Sent"):
        merge_review_rows([sent], [modified], kind="drafts")


def test_missing_rows_are_preserved_and_unknown_rows_rejected():
    current = _draft()
    assert merge_review_rows([current], [], kind="drafts") == [current]
    unknown = _draft()
    unknown["Draft ID"] = "DRAFT-UNKNOWN"
    with pytest.raises(ReviewMergeError, match="unknown Draft ID"):
        merge_review_rows([current], [unknown], kind="drafts")
