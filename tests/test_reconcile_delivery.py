import pytest

from scripts.reconcile_delivery import CONFIRMATION_PHRASE, reconcile
from speaker_pipeline.common import read_csv, write_csv
from speaker_pipeline.schema import DRAFT_COLUMNS


def _uncertain(path):
    row = {column: "" for column in DRAFT_COLUMNS}
    row.update(
        {
            "Draft ID": "DRAFT-UNCERTAIN",
            "Candidate ID": "IND-ONE",
            "Campaign ID": "CMP-ONE",
            "Draft Status": "Sending",
            "To Email": "person@example.com",
            "Message ID": "<message@example.org>",
            "Last Attempt At": "2026-08-22T00:00:00+00:00",
            "Error": "UNCERTAIN DELIVERY: TimeoutError: response lost",
        }
    )
    write_csv(path, DRAFT_COLUMNS, [row])


@pytest.mark.parametrize(
    ("resolution", "expected"),
    [("provider-accepted", "Sent"), ("provider-rejected", "Failed")],
)
def test_uncertain_attempt_requires_explicit_provider_reconciliation(
    tmp_path, resolution, expected
):
    ledger = tmp_path / "drafts.csv"
    _uncertain(ledger)
    result = reconcile(
        [
            "--input",
            str(ledger),
            "--draft-id",
            "DRAFT-UNCERTAIN",
            "--resolution",
            resolution,
            "--provider-reference",
            "provider-event-123",
            "--reviewer",
            "Operations Reviewer",
            "--confirm",
            CONFIRMATION_PHRASE,
        ]
    )
    persisted = read_csv(ledger, DRAFT_COLUMNS)[0]
    assert result["Draft Status"] == expected
    assert persisted["Draft Status"] == expected
    assert persisted["Reconciled By"] == "Operations Reviewer"
    assert persisted["Provider Reference"] == "provider-event-123"


def test_reconciliation_cannot_reclassify_an_unattempted_draft(tmp_path):
    ledger = tmp_path / "drafts.csv"
    _uncertain(ledger)
    rows = read_csv(ledger, DRAFT_COLUMNS)
    rows[0]["Draft Status"] = "Approved"
    write_csv(ledger, DRAFT_COLUMNS, rows)
    with pytest.raises(SystemExit, match="Only a Sending"):
        reconcile(
            [
                "--input",
                str(ledger),
                "--draft-id",
                "DRAFT-UNCERTAIN",
                "--resolution",
                "provider-accepted",
                "--provider-reference",
                "provider-event-123",
                "--reviewer",
                "Operations Reviewer",
                "--confirm",
                CONFIRMATION_PHRASE,
            ]
        )
