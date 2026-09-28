from __future__ import annotations

import smtplib
from copy import deepcopy

import pytest

from speaker_pipeline import mailer
from speaker_pipeline.approvals import (
    ApprovalIntegrityError,
    approval_is_valid,
    approve_row,
    compute_approval_hash,
)
from speaker_pipeline.mailer import (
    CONFIRMATION_PHRASE,
    DuplicateRecipientError,
    MailSettings,
    SenderIdentityMismatchError,
    UnsafeDeliveryError,
    deliver_approved_drafts,
    sendable_drafts,
    validate_send_batch,
)
from speaker_pipeline.policy import DeliveryAuthorization


def settings(**changes: object) -> MailSettings:
    values: dict[str, object] = {
        "host": "smtp.example.org",
        "port": 587,
        "username": "sender@example.org",
        "password": "secret",
        "from_email": "sender@example.org",
        "from_name": "Program Team",
        "reply_to": "replies@example.org",
        "starttls": True,
    }
    values.update(changes)
    return MailSettings(**values)  # type: ignore[arg-type]


def approved_draft(**changes: str) -> dict[str, str]:
    row = {
        "Campaign ID": "CMP-ONE",
        "Draft ID": "DRAFT-ONE",
        "Candidate ID": "IND-ONE",
        "Candidate Approval Hash": "sha256-v2:candidate",
        "Campaign Policy Hash": "sha256:policy",
        "Revision": "1",
        "Schema Version": "1.1",
        "Draft Status": "Draft",
        "To Email": "recipient@example.com",
        "To Name": "Recipient",
        "Contact Type": "Direct",
        "Subject": "Invitation",
        "Body Text": "Please join our event.",
        "Profile URL": "https://example.com/recipient",
        "Sender Email": "sender@example.org",
        "Sender Name": "Program Team",
        "Reply-To": "replies@example.org",
        "Created At": "2026-08-20T00:00:00+00:00",
        "Last Attempt At": "",
        "Sent At": "",
        "Message ID": "",
        "Error": "",
        "Approval Hash": "",
        "Approved At": "",
        "Approved By": "",
    }
    row.update(changes)
    approve_row(
        row,
        "reviewer@example.org",
        record_type="draft",
        approved_at="2026-08-21T00:00:00+00:00",
    )
    return row


class FakeServer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.messages = []
        self.quit_called = False

    def send_message(self, message: object) -> None:
        self.messages.append(message)
        if self.error is not None:
            raise self.error

    def quit(self) -> None:
        self.quit_called = True


def safe_live_kwargs(snapshots: list[list[dict[str, str]]]) -> dict[str, object]:
    return {
        "send": True,
        "confirmation": CONFIRMATION_PHRASE,
        "campaign_id": "CMP-ONE",
        "delay_seconds": 0,
        "persist": lambda rows: snapshots.append(deepcopy(rows)),
        "lock_held": True,
        "preflight": lambda _context: DeliveryAuthorization(
            campaign_id="CMP-ONE",
            policy_hash="sha256-policy:test",
            selected=1,
            attempted=0,
            remaining_after_batch=0,
        ),
    }


@pytest.mark.parametrize(
    "field",
    [
        "Approved By",
        "Approved At",
        "Candidate Approval Hash",
        "Campaign Policy Hash",
        "Sender Email",
        "Sender Name",
        "Reply-To",
    ],
)
def test_v2_approval_binds_audit_policy_candidate_and_sender_fields(field: str) -> None:
    row = approved_draft()
    assert row["Approval Hash"].startswith("sha256-v2:")
    assert approval_is_valid(row, record_type="draft")

    row[field] += " changed"

    assert not approval_is_valid(row, record_type="draft")


def test_legacy_hash_is_readable_but_never_live_sendable() -> None:
    row = approved_draft()
    row["Approval Hash"] = compute_approval_hash(row, record_type="draft", version=1)
    assert approval_is_valid(row, record_type="draft")
    snapshots: list[list[dict[str, str]]] = []

    with pytest.raises(ApprovalIntegrityError, match="unsupported Approval Hash"):
        deliver_approved_drafts(
            [row],
            settings(),
            **safe_live_kwargs(snapshots),
            connector=lambda _settings: pytest.fail("SMTP must not be opened"),
        )


def test_runtime_sender_must_exactly_match_approved_sender_identity() -> None:
    row = approved_draft()
    snapshots: list[list[dict[str, str]]] = []

    with pytest.raises(SenderIdentityMismatchError, match="Sender Email"):
        deliver_approved_drafts(
            [row],
            settings(from_email="other@example.org"),
            **safe_live_kwargs(snapshots),
            connector=lambda _settings: pytest.fail("SMTP must not be opened"),
        )


@pytest.mark.parametrize("max_messages", [-1, True, 1.5])
def test_max_messages_must_be_a_nonnegative_integer(max_messages: object) -> None:
    with pytest.raises(ValueError, match="max_messages"):
        sendable_drafts([approved_draft()], max_messages=max_messages)  # type: ignore[arg-type]


@pytest.mark.parametrize("delay", [-0.1, float("inf"), float("nan"), True])
def test_delay_must_be_finite_and_nonnegative(delay: object) -> None:
    with pytest.raises(ValueError, match="delay_seconds"):
        deliver_approved_drafts(
            [approved_draft()],
            settings(),
            delay_seconds=delay,  # type: ignore[arg-type]
        )


def test_cross_campaign_duplicate_is_blocked_by_default() -> None:
    first = approved_draft()
    second = approved_draft(**{"Campaign ID": "CMP-TWO", "Draft ID": "DRAFT-TWO"})

    with pytest.raises(DuplicateRecipientError, match="Duplicate recipient"):
        validate_send_batch([first, second])

    assert validate_send_batch([first, second], allow_cross_campaign_recipients=True) == [
        first,
        second,
    ]


def test_cross_campaign_attempt_history_is_blocked_by_default() -> None:
    attempted = approved_draft()
    attempted["Draft Status"] = "Sent"
    attempted["Sent At"] = "2026-08-21T01:00:00+00:00"
    next_campaign = approved_draft(**{"Campaign ID": "CMP-TWO", "Draft ID": "DRAFT-TWO"})

    with pytest.raises(DuplicateRecipientError, match="already has attempted draft"):
        validate_send_batch([attempted, next_campaign], campaign_id="CMP-TWO")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"campaign_id": ""}, "explicit campaign_id"),
        ({"persist": None}, "persistence callback"),
        ({"persist": object()}, "persistence callback"),
        ({"lock_held": False}, "ledger lock"),
        ({"preflight": None}, "preflight hook"),
        ({"preflight": object()}, "preflight hook"),
    ],
)
def test_live_api_refuses_unsafe_delivery_contract(
    overrides: dict[str, object], message: str
) -> None:
    snapshots: list[list[dict[str, str]]] = []
    kwargs = safe_live_kwargs(snapshots)
    kwargs.update(overrides)

    with pytest.raises(UnsafeDeliveryError, match=message):
        deliver_approved_drafts(
            [approved_draft()],
            settings(),
            **kwargs,
            connector=lambda _settings: pytest.fail("SMTP must not be opened"),
        )


def test_external_preflight_can_fail_closed_before_smtp() -> None:
    snapshots: list[list[dict[str, str]]] = []
    kwargs = safe_live_kwargs(snapshots)
    observed = []

    def refuse(context: object) -> object:
        observed.append(context)
        return False

    kwargs["preflight"] = refuse
    with pytest.raises(UnsafeDeliveryError, match="verified DeliveryAuthorization"):
        deliver_approved_drafts(
            [approved_draft()],
            settings(),
            **kwargs,
            connector=lambda _settings: pytest.fail("SMTP must not be opened"),
        )
    assert len(observed) == 1
    assert snapshots == []


def test_mutation_during_preflight_is_rechecked_before_smtp() -> None:
    row = approved_draft()
    snapshots: list[list[dict[str, str]]] = []
    kwargs = safe_live_kwargs(snapshots)

    def mutate_caller_state(_context: object) -> DeliveryAuthorization:
        row["Subject"] = "Changed after the first check"
        return DeliveryAuthorization("CMP-ONE", "sha256-policy:test", 1, 0, 0)

    kwargs["preflight"] = mutate_caller_state
    with pytest.raises(ApprovalIntegrityError, match="stale"):
        deliver_approved_drafts(
            [row],
            settings(),
            **kwargs,
            connector=lambda _settings: pytest.fail("SMTP must not be opened"),
        )
    assert snapshots == []


def test_server_accepted_then_timeout_remains_sending_and_uncertain() -> None:
    row = approved_draft()
    snapshots: list[list[dict[str, str]]] = []
    server = FakeServer(TimeoutError("timeout after DATA acceptance"))

    result = deliver_approved_drafts(
        [row],
        settings(),
        **safe_live_kwargs(snapshots),
        connector=lambda _settings: server,
    )

    assert result == {"selected": 1, "sent": 0, "failed": 0, "uncertain": 1}
    assert row["Draft Status"] == "Sending"
    assert row["Sent At"] == ""
    assert row["Error"].startswith("UNCERTAIN DELIVERY: TimeoutError:")
    assert snapshots[0][0]["Draft Status"] == "Sending"
    assert snapshots[-1][0]["Draft Status"] == "Sending"
    assert len(server.messages) == 1


def test_explicit_permanent_smtp_refusal_is_failed() -> None:
    row = approved_draft()
    snapshots: list[list[dict[str, str]]] = []
    server = FakeServer(smtplib.SMTPDataError(550, b"content rejected"))

    result = deliver_approved_drafts(
        [row],
        settings(),
        **safe_live_kwargs(snapshots),
        connector=lambda _settings: server,
    )

    assert result == {"selected": 1, "sent": 0, "failed": 1, "uncertain": 0}
    assert row["Draft Status"] == "Failed"
    assert row["Error"].startswith("DEFINITIVE SMTP REFUSAL: SMTPDataError:")


def test_real_connector_path_negotiates_starttls_before_login(monkeypatch) -> None:
    calls: list[object] = []

    class ProtocolServer:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))

        def ehlo(self):
            calls.append("ehlo")

        def starttls(self, *, context):
            assert context is not None
            calls.append("starttls")

        def login(self, username, password):
            calls.append(("login", username, password))

    monkeypatch.setattr(mailer.smtplib, "SMTP", ProtocolServer)
    result = mailer._connect(settings())

    assert isinstance(result, ProtocolServer)
    assert calls == [
        ("connect", "smtp.example.org", 587, 30.0),
        "ehlo",
        "starttls",
        "ehlo",
        ("login", "sender@example.org", "secret"),
    ]


def test_persistence_failure_before_smtp_never_sends() -> None:
    row = approved_draft()
    server = FakeServer()

    def fail_persist(_rows):
        raise OSError("disk unavailable")

    kwargs = safe_live_kwargs([])
    kwargs["persist"] = fail_persist
    with pytest.raises(OSError, match="disk unavailable"):
        deliver_approved_drafts(
            [row],
            settings(),
            **kwargs,
            connector=lambda _settings: server,
        )

    assert server.messages == []
    assert row["Draft Status"] == "Sending"
