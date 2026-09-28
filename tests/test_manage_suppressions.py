import pytest

from scripts.manage_suppressions import REVOCATION_PHRASE, main
from speaker_pipeline.policy import load_suppressions


def test_add_and_explicitly_revoke_suppression(tmp_path):
    ledger = tmp_path / "suppressions.csv"
    main(
        [
            "--input",
            str(ledger),
            "add",
            "--scope",
            "Email",
            "--value",
            "stop@example.com",
            "--reason",
            "Recipient opt-out",
            "--created-by",
            "Operations Reviewer",
        ]
    )
    record = load_suppressions(ledger)[0]
    assert record.status == "Active"

    main(
        [
            "--input",
            str(ledger),
            "revoke",
            "--id",
            record.suppression_id,
            "--revoked-by",
            "Privacy Reviewer",
            "--confirm",
            REVOCATION_PHRASE,
        ]
    )
    revoked = load_suppressions(ledger)[0]
    assert revoked.status == "Revoked"
    assert revoked.revoked_at
    assert revoked.revoked_by == "Privacy Reviewer"


def test_revocation_fails_without_exact_confirmation(tmp_path):
    ledger = tmp_path / "suppressions.csv"
    main(
        [
            "--input",
            str(ledger),
            "add",
            "--scope",
            "Domain",
            "--value",
            "example.com",
            "--reason",
            "Organization-wide request",
            "--created-by",
            "Operations Reviewer",
        ]
    )
    record = load_suppressions(ledger)[0]
    with pytest.raises(SystemExit, match=REVOCATION_PHRASE):
        main(
            [
                "--input",
                str(ledger),
                "revoke",
                "--id",
                record.suppression_id,
                "--revoked-by",
                "Privacy Reviewer",
            ]
        )
