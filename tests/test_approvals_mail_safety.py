from copy import deepcopy

import pytest

from speaker_pipeline.approvals import (
    ApprovalIntegrityError,
    approval_is_valid,
    approve_row,
)
from speaker_pipeline.drafts import campaign_id_from_config, generate_drafts
from speaker_pipeline.locking import LedgerLock, LockTimeoutError, lock_path_for
from speaker_pipeline.mailer import (
    CONFIRMATION_PHRASE,
    DuplicateRecipientError,
    MailSettings,
    deliver_approved_drafts,
    validate_mail_settings,
    validate_send_batch,
)
from speaker_pipeline.policy import DeliveryAuthorization
from speaker_pipeline.schema import CANDIDATE_COLUMNS


def candidate(**changes):
    row = {column: "" for column in CANDIDATE_COLUMNS}
    row.update(
        {
            "Candidate ID": "IND-123",
            "Speaker Type": "Industry",
            "Review Status": "Approved",
            "Full Name": "Ada Lovelace",
            "Organization": "Example Co",
            "Title": "Chief Scientist",
            "Expertise": "Machine learning",
            "Topic Fit": "responsible artificial intelligence",
            "Preferred Salutation": "Dr. Lovelace",
            "Email": "ada@example.com",
            "Contact Type": "Direct",
            "Email Source URL": "https://example.com/ada",
            "Profile URL": "https://example.com/ada",
            "Discovery Source URL": "https://example.com/leaders",
            "Last Checked": "2026-08-16",
        }
    )
    row.update(changes)
    return row


def invitation_config(**changes):
    config = {
        "event_name": "AI Forum",
        "event_host": "Example Host",
        "event_date": "October 1, 2026",
        "event_location": "San Francisco",
        "event_description": "a forum for researchers and industry leaders",
        "sender_name": "Alex Chen",
        "sender_title": "Program Director",
        "sender_organization": "Example Host",
        "sender_email": "alex@example.org",
        "subject_template": "Invitation for {full_name} to {event_name}",
        "direct_body_template": "Dear {salutation},\n\nPlease join {event_name}.\n\n{sender_name}",
        "routed_body_template": "Dear {route_greeting},\n\nPlease forward to {full_name}.\n\n{sender_name}",
    }
    config.update(changes)
    return config


def secure_settings(**changes):
    values = {
        "host": "smtp.example.org",
        "port": 587,
        "username": "user",
        "password": "secret",
        "from_email": "alex@example.org",
        "from_name": "Alex Chen",
        "starttls": True,
    }
    values.update(changes)
    return MailSettings(**values)


class FakeServer:
    def __init__(self):
        self.messages = []
        self.quit_called = False

    def send_message(self, message):
        self.messages.append(message)

    def quit(self):
        self.quit_called = True


def approved_draft(**changes):
    row = generate_drafts([candidate()], invitation_config(campaign_id="CMP-ONE"))[0]
    row.update(changes)
    approve_row(row, "reviewer@example.org", record_type="draft")
    return row


def live_safety_contract():
    return {
        "campaign_id": "CMP-ONE",
        "persist": lambda _rows: None,
        "lock_held": True,
        "preflight": lambda _context: DeliveryAuthorization(
            "CMP-ONE", "sha256-policy:test", 1, 0, 0
        ),
    }


def test_candidate_hash_binds_role_and_email_evidence_fields():
    row = candidate(
        **{
            "Schema Version": "1.1",
            "Campaign ID": "CMP-ONE",
            "Target ID": "TARGET-1",
            "Revision": "1",
            "Role Temporal Status": "Current",
            "Role As Of": "2026-08-16",
            "Role Evidence ID": "EVID-ROLE-1",
            "Email Evidence Level": "E4 Exact Current Official",
            "Email Evidence ID": "EVID-EMAIL-1",
            "Mailbox Status": "Unknown",
            "Preferred Route Type": "Direct",
            "Preferred Route URL": "https://example.com/contact",
        }
    )
    approve_row(row, "reviewer@example.org", record_type="candidate")
    assert approval_is_valid(row, record_type="candidate")

    row["Email Evidence ID"] = "EVID-EMAIL-REPLACED"
    assert not approval_is_valid(row, record_type="candidate")


@pytest.mark.parametrize("field", ["To Email", "Subject", "Body Text", "Campaign ID"])
def test_approved_draft_payload_tampering_invalidates_hash(field):
    row = approved_draft()
    row[field] += " changed"
    assert not approval_is_valid(row, record_type="draft")


@pytest.mark.parametrize("stored_hash", ["", "sha256-v1:" + "0" * 64])
def test_missing_or_stale_hash_blocks_before_smtp(stored_hash):
    row = approved_draft()
    row["Approval Hash"] = stored_hash
    called = False

    def connector(_settings):
        nonlocal called
        called = True
        return FakeServer()

    with pytest.raises(ApprovalIntegrityError, match="Approval Hash"):
        deliver_approved_drafts(
            [row],
            secure_settings(),
            send=True,
            confirmation=CONFIRMATION_PHRASE,
            delay_seconds=0,
            connector=connector,
            **live_safety_contract(),
        )
    assert not called
    assert row["Draft Status"] == "Approved"


def test_changing_only_draft_status_does_not_create_live_send_approval():
    row = generate_drafts([candidate()], invitation_config(campaign_id="CMP-ONE"))[0]
    assert row["Approval Hash"] == ""
    row["Draft Status"] = "Approved"

    with pytest.raises(ApprovalIntegrityError, match="approval audit metadata"):
        deliver_approved_drafts(
            [row],
            secure_settings(),
            send=True,
            confirmation=CONFIRMATION_PHRASE,
            delay_seconds=0,
            connector=lambda _settings: pytest.fail("SMTP must not be opened"),
            **live_safety_contract(),
        )


def test_duplicate_recipient_in_campaign_blocks_before_batch_limit_and_smtp():
    first = approved_draft()
    second = deepcopy(first)
    second["Draft ID"] = "DRAFT-SECOND"
    second["Candidate ID"] = "IND-SECOND"
    second["To Email"] = first["To Email"].upper()
    approve_row(second, "reviewer@example.org", record_type="draft")
    called = False

    def connector(_settings):
        nonlocal called
        called = True
        return FakeServer()

    with pytest.raises(DuplicateRecipientError, match="(?i)duplicate recipient"):
        deliver_approved_drafts(
            [first, second],
            secure_settings(),
            send=True,
            confirmation=CONFIRMATION_PHRASE,
            max_messages=1,
            delay_seconds=0,
            connector=connector,
            **live_safety_contract(),
        )
    assert not called


def test_same_recipient_in_different_campaigns_is_globally_blocked_by_default():
    first = approved_draft()
    second = deepcopy(first)
    second["Campaign ID"] = "CMP-TWO"
    second["Draft ID"] = "DRAFT-SECOND"
    approve_row(second, "reviewer@example.org", record_type="draft")

    with pytest.raises(DuplicateRecipientError, match="Duplicate recipient"):
        validate_send_batch([first, second])

    # Deployments need an explicit higher-level cooldown/consent policy before
    # opting out of the global default.
    assert validate_send_batch([first, second], allow_cross_campaign_recipients=True) == [
        first,
        second,
    ]


@pytest.mark.parametrize("attempted_status", ["Sending", "Sent"])
def test_prior_attempt_blocks_same_campaign_recipient(attempted_status):
    attempted = approved_draft(**{"Draft Status": attempted_status})
    attempted["Draft Status"] = attempted_status
    replacement = deepcopy(attempted)
    replacement["Draft ID"] = "DRAFT-REPLACEMENT"
    replacement["Draft Status"] = "Approved"
    approve_row(replacement, "reviewer@example.org", record_type="draft")

    with pytest.raises(DuplicateRecipientError, match="already has"):
        validate_send_batch([attempted, replacement])


def test_campaign_id_is_stable_and_scopes_sent_history():
    config = invitation_config()
    assert campaign_id_from_config(config) == campaign_id_from_config(dict(config))

    first = generate_drafts([candidate()], config)
    first[0]["Draft Status"] = "Sent"
    future_config = invitation_config(event_date="October 1, 2027")
    result = generate_drafts([candidate()], future_config, first)

    assert len(result) == 2
    assert result[0]["Draft Status"] == "Sent"
    assert result[0]["Campaign ID"] != result[1]["Campaign ID"]
    assert result[1]["Draft Status"] == "Draft"


def test_plaintext_smtp_is_rejected_except_explicit_localhost_test():
    with pytest.raises(ValueError, match="transport encryption"):
        validate_mail_settings(
            secure_settings(use_ssl=False, starttls=False, username="", password="")
        )
    with pytest.raises(ValueError, match="transport encryption"):
        validate_mail_settings(
            secure_settings(
                host="localhost",
                use_ssl=False,
                starttls=False,
                username="",
                password="",
            )
        )

    validate_mail_settings(
        secure_settings(
            host="localhost",
            use_ssl=False,
            starttls=False,
            username="",
            password="",
            allow_insecure_localhost=True,
        )
    )


def test_insecure_localhost_exception_cannot_be_used_for_remote_host():
    with pytest.raises(ValueError, match="restricted to localhost"):
        validate_mail_settings(
            secure_settings(
                host="smtp.example.org",
                use_ssl=False,
                starttls=False,
                username="",
                password="",
                allow_insecure_localhost=True,
            )
        )


def test_ledger_lock_blocks_a_second_process_scope_and_can_be_reacquired(tmp_path):
    ledger = tmp_path / "email_drafts.csv"
    assert lock_path_for(ledger) == tmp_path / "email_drafts.csv.lock"

    with LedgerLock(ledger, timeout=0):
        with pytest.raises(LockTimeoutError):
            with LedgerLock(ledger, timeout=0):
                pass

    with LedgerLock(ledger, timeout=0):
        assert lock_path_for(ledger).exists()
