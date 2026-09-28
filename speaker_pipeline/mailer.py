"""SMTP delivery with dry-run default, two explicit approvals, and crash-safe states."""

from __future__ import annotations

import math
import os
import smtplib
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from types import MappingProxyType

from .approvals import require_valid_approval
from .common import EMAIL_RE, clean, utc_now_iso
from .locking import live_send_lock
from .policy import DeliveryAuthorization

CONFIRMATION_PHRASE = "SEND_APPROVED_EMAILS"


class DuplicateRecipientError(ValueError):
    """Raised when a mailbox would be contacted more than once."""


class SenderIdentityMismatchError(ValueError):
    """Raised when SMTP sender identity differs from the approved draft."""


class UnsafeDeliveryError(ValueError):
    """Raised when live delivery lacks persistence, locking, or policy gates."""


@dataclass(frozen=True)
class MailSettings:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str = ""
    reply_to: str = ""
    use_ssl: bool = False
    starttls: bool = True
    timeout: float = 30.0
    allow_insecure_localhost: bool = False

    @classmethod
    def from_environment(cls) -> MailSettings:
        def truthy(name: str, default: str) -> bool:
            return os.environ.get(name, default).strip().casefold() in {"1", "true", "yes", "on"}

        required = ["SMTP_HOST", "SMTP_PORT", "SMTP_FROM_EMAIL"]
        missing = [name for name in required if not os.environ.get(name, "").strip()]
        if missing:
            raise ValueError(f"Missing SMTP environment variables: {', '.join(missing)}")
        username = os.environ.get("SMTP_USERNAME", "").strip()
        password = os.environ.get("SMTP_PASSWORD", "")
        if bool(username) != bool(password):
            raise ValueError(
                "SMTP_USERNAME and SMTP_PASSWORD must either both be set or both be blank."
            )
        return cls(
            host=os.environ["SMTP_HOST"].strip(),
            port=int(os.environ["SMTP_PORT"]),
            username=username,
            password=password,
            from_email=os.environ["SMTP_FROM_EMAIL"].strip(),
            from_name=os.environ.get("SMTP_FROM_NAME", "").strip(),
            reply_to=os.environ.get("SMTP_REPLY_TO", "").strip(),
            use_ssl=truthy("SMTP_USE_SSL", "false"),
            starttls=truthy("SMTP_STARTTLS", "true"),
            timeout=float(os.environ.get("SMTP_TIMEOUT", "30")),
            allow_insecure_localhost=truthy("SMTP_ALLOW_INSECURE_LOCALHOST", "false"),
        )


@dataclass(frozen=True)
class DeliveryPreflightContext:
    """Read-only snapshots supplied to the deployment's final policy gate.

    The caller can close over authoritative campaign, candidate, evidence, and
    suppression ledgers.  Raising from the hook aborts before SMTP is opened.
    """

    rows: tuple[Mapping[str, str], ...]
    selected: tuple[Mapping[str, str], ...]
    settings: MailSettings
    campaign_id: str
    max_messages: int


DeliveryPreflight = Callable[[DeliveryPreflightContext], DeliveryAuthorization]


def _validate_delivery_numbers(max_messages: int, delay_seconds: float) -> None:
    if isinstance(max_messages, bool) or not isinstance(max_messages, int):
        raise ValueError("max_messages must be a nonnegative integer.")
    if max_messages < 0:
        raise ValueError("max_messages must be a nonnegative integer.")
    if (
        isinstance(delay_seconds, bool)
        or not isinstance(delay_seconds, (int, float))
        or not math.isfinite(float(delay_seconds))
        or delay_seconds < 0
    ):
        raise ValueError("delay_seconds must be a finite nonnegative number.")


def sendable_drafts(
    rows: list[dict[str, str]], max_messages: int = 0, *, campaign_id: str = ""
) -> list[dict[str, str]]:
    """Select status-approved rows for preview.

    Approval hash and duplicate checks are deliberately performed by the live
    preflight so dry-run can still show operators which status-approved legacy
    rows need remediation without ever making them deliverable.
    """

    _validate_delivery_numbers(max_messages, 0.0)
    selected = [
        row
        for row in rows
        if clean(row.get("Draft Status")) == "Approved"
        and (not campaign_id or clean(row.get("Campaign ID")) == clean(campaign_id))
    ]
    return selected[:max_messages] if max_messages > 0 else selected


def _recipient_key(
    row: Mapping[str, str], *, allow_cross_campaign_recipients: bool
) -> tuple[str, ...]:
    email = clean(row.get("To Email")).casefold()
    if allow_cross_campaign_recipients:
        return (clean(row.get("Campaign ID")), email)
    return (email,)


def _describe_recipient_key(key: tuple[str, ...]) -> str:
    return key[-1] or "<blank>"


def validate_send_batch(
    rows: list[dict[str, str]],
    *,
    campaign_id: str = "",
    settings: MailSettings | None = None,
    allow_cross_campaign_recipients: bool = False,
    require_delivery_approval: bool = False,
) -> list[dict[str, str]]:
    """Validate Approved rows before batch limiting or SMTP access.

    Recipient history is global by default.  A deployment that intentionally
    permits repeat contact across campaigns must opt in explicitly and should
    enforce its own cooldown/consent policy in the final preflight hook.
    """

    selected = sendable_drafts(rows, campaign_id=campaign_id)
    for row in selected:
        require_valid_approval(
            row,
            record_type="draft",
            allow_legacy=not require_delivery_approval,
        )
        if settings is not None:
            validate_approved_sender(row, settings)

    selected_keys = {
        _recipient_key(row, allow_cross_campaign_recipients=allow_cross_campaign_recipients)
        for row in selected
    }
    approved_by_key: dict[tuple[str, ...], list[str]] = {}
    for row in rows:
        if clean(row.get("Draft Status")) != "Approved":
            continue
        key = _recipient_key(
            row,
            allow_cross_campaign_recipients=allow_cross_campaign_recipients,
        )
        if key not in selected_keys:
            continue
        approved_by_key.setdefault(key, []).append(clean(row.get("Draft ID")) or "<unknown>")
    for key, identifiers in approved_by_key.items():
        if len(identifiers) > 1:
            raise DuplicateRecipientError(
                f"Duplicate recipient {_describe_recipient_key(key)} appears in Approved "
                f"drafts {', '.join(identifiers)}. Consolidate or reject all but one draft."
            )

    selected_ids = {id(row) for row in selected}
    for attempted in rows:
        if id(attempted) in selected_ids:
            continue
        status = clean(attempted.get("Draft Status"))
        was_attempted = status in {"Sending", "Sent", "Failed"} or bool(
            clean(attempted.get("Last Attempt At"))
        )
        if not was_attempted:
            continue
        key = _recipient_key(
            attempted,
            allow_cross_campaign_recipients=allow_cross_campaign_recipients,
        )
        if key not in selected_keys:
            continue
        attempted_id = clean(attempted.get("Draft ID")) or "<unknown>"
        raise DuplicateRecipientError(
            f"Recipient {_describe_recipient_key(key)} already has attempted draft "
            f"{attempted_id} with status {status or '<blank>'}; refusing another delivery."
        )
    return selected


def validate_mail_settings(settings: MailSettings) -> None:
    if (
        not settings.host
        or isinstance(settings.port, bool)
        or not isinstance(settings.port, int)
        or not 1 <= settings.port <= 65535
    ):
        raise ValueError("SMTP host/port is invalid.")
    if (
        isinstance(settings.timeout, bool)
        or not isinstance(settings.timeout, (int, float))
        or not math.isfinite(float(settings.timeout))
        or settings.timeout <= 0
    ):
        raise ValueError("SMTP timeout must be a finite positive number.")
    for label, value in (
        ("SMTP_FROM_EMAIL", settings.from_email),
        ("SMTP_REPLY_TO", settings.reply_to),
    ):
        if value and not EMAIL_RE.fullmatch(value):
            raise ValueError(f"{label} is not a valid plain email address.")
    if settings.use_ssl and settings.starttls:
        raise ValueError("Choose SMTP_USE_SSL or SMTP_STARTTLS, not both.")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    is_explicit_localhost = settings.host.strip().casefold().rstrip(".") in local_hosts
    if settings.allow_insecure_localhost and not is_explicit_localhost:
        raise ValueError("The insecure SMTP test exception is restricted to localhost.")
    if not settings.use_ssl and not settings.starttls:
        if not (settings.allow_insecure_localhost and is_explicit_localhost):
            raise ValueError(
                "SMTP transport encryption is required. Enable SMTP_USE_SSL or "
                "SMTP_STARTTLS; plaintext is allowed only for an explicitly opted-in "
                "localhost test server."
            )
    if bool(settings.username) != bool(settings.password):
        raise ValueError("SMTP username and password must either both be set or both be blank.")
    for label, value in (("SMTP_FROM_NAME", settings.from_name), ("SMTP_HOST", settings.host)):
        if "\r" in value or "\n" in value:
            raise ValueError(f"{label} must not contain a newline.")


def validate_approved_sender(row: Mapping[str, str], settings: MailSettings) -> None:
    """Require the runtime From/Reply-To identity approved in a v2 draft hash."""

    approved_email = clean(row.get("Sender Email"))
    approved_name = str(row.get("Sender Name", "") or "").strip()
    approved_reply_to = clean(row.get("Reply-To"))
    identifier = clean(row.get("Draft ID")) or "<unknown>"
    if not approved_email:
        raise SenderIdentityMismatchError(
            f"Draft {identifier} has no approved Sender Email; regenerate and re-approve it."
        )
    comparisons = (
        ("Sender Email", approved_email.casefold(), clean(settings.from_email).casefold()),
        ("Sender Name", approved_name, str(settings.from_name or "").strip()),
        ("Reply-To", approved_reply_to.casefold(), clean(settings.reply_to).casefold()),
    )
    mismatches = [label for label, approved, actual in comparisons if approved != actual]
    if mismatches:
        raise SenderIdentityMismatchError(
            f"Draft {identifier} SMTP sender identity differs from its approval: "
            f"{', '.join(mismatches)}. Regenerate/re-approve or use the approved sender."
        )


def _is_definitive_smtp_refusal(exc: Exception) -> bool:
    """Return true only when SMTP explicitly proves the message was rejected."""

    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        responses = list(exc.recipients.values())
        return bool(responses) and all(
            isinstance(response, tuple)
            and response
            and isinstance(response[0], int)
            and 500 <= response[0] <= 599
            for response in responses
        )
    if isinstance(exc, smtplib.SMTPResponseException):
        return 500 <= exc.smtp_code <= 599
    return False


def _delivery_error(exc: Exception, *, uncertain: bool) -> str:
    detail = clean(exc) or "no detail supplied"
    prefix = "UNCERTAIN DELIVERY" if uncertain else "DEFINITIVE SMTP REFUSAL"
    return f"{prefix}: {type(exc).__name__}: {detail}"


def _message_for(row: dict[str, str], settings: MailSettings) -> EmailMessage:
    recipient = clean(row.get("To Email"))
    subject = str(row.get("Subject", "")).strip()
    body = str(row.get("Body Text", "")).strip()
    if not EMAIL_RE.fullmatch(recipient):
        raise ValueError("To Email must be exactly one valid email address.")
    if not subject or "\r" in subject or "\n" in subject:
        raise ValueError("Subject must be one non-empty line.")
    if not body:
        raise ValueError("Body Text is empty.")
    message = EmailMessage()
    message["From"] = (
        formataddr((settings.from_name, settings.from_email))
        if settings.from_name
        else settings.from_email
    )
    message["To"] = recipient
    message["Subject"] = subject
    if settings.reply_to:
        message["Reply-To"] = settings.reply_to
    message_id = clean(row.get("Message ID")) or make_msgid(
        domain=settings.from_email.split("@")[-1]
    )
    message["Message-ID"] = message_id
    message.set_content(body)
    return message


def _connect(settings: MailSettings):
    validate_mail_settings(settings)
    context = ssl.create_default_context()
    if settings.use_ssl:
        server = smtplib.SMTP_SSL(
            settings.host, settings.port, timeout=settings.timeout, context=context
        )
    else:
        server = smtplib.SMTP(settings.host, settings.port, timeout=settings.timeout)
        server.ehlo()
        if settings.starttls:
            server.starttls(context=context)
            server.ehlo()
    if settings.username:
        server.login(settings.username, settings.password)
    return server


def deliver_approved_drafts(
    rows: list[dict[str, str]],
    settings: MailSettings,
    *,
    send: bool = False,
    confirmation: str = "",
    max_messages: int = 0,
    delay_seconds: float = 1.0,
    campaign_id: str = "",
    persist: Callable[[list[dict[str, str]]], None] | None = None,
    lock_held: bool = False,
    preflight: DeliveryPreflight | None = None,
    allow_cross_campaign_recipients: bool = False,
    connector: Callable[[MailSettings], object] = _connect,
) -> dict[str, int]:
    _validate_delivery_numbers(max_messages, delay_seconds)
    selected = sendable_drafts(rows, max_messages, campaign_id=campaign_id)
    if not send:
        return {"selected": len(selected), "sent": 0, "failed": 0, "uncertain": 0}
    if confirmation != CONFIRMATION_PHRASE:
        raise ValueError(f"Live send requires confirmation phrase: {CONFIRMATION_PHRASE}")
    if not clean(campaign_id):
        raise UnsafeDeliveryError("Live delivery requires an explicit campaign_id.")
    if persist is None or not callable(persist):
        raise UnsafeDeliveryError(
            "Live delivery requires an authoritative persistence callback; refusing an "
            "in-memory-only send."
        )
    if lock_held is not True:
        raise UnsafeDeliveryError(
            "Live delivery requires the caller to hold the canonical ledger lock and pass "
            "lock_held=True."
        )
    if preflight is None or not callable(preflight):
        raise UnsafeDeliveryError(
            "Live delivery requires a final campaign/candidate/evidence/suppression preflight hook."
        )
    validate_mail_settings(settings)
    # Validate the complete campaign before applying the operator's batch limit;
    # max_messages must never hide a duplicate or stale approval later in the set.
    approved_batch = validate_send_batch(
        rows,
        campaign_id=campaign_id,
        settings=settings,
        allow_cross_campaign_recipients=allow_cross_campaign_recipients,
        require_delivery_approval=True,
    )
    selected = approved_batch[:max_messages] if max_messages > 0 else approved_batch
    if not selected:
        return {"selected": 0, "sent": 0, "failed": 0, "uncertain": 0}

    authorization = preflight(
        DeliveryPreflightContext(
            rows=tuple(MappingProxyType(dict(row)) for row in rows),
            selected=tuple(MappingProxyType(dict(row)) for row in selected),
            settings=settings,
            campaign_id=clean(campaign_id),
            max_messages=max_messages,
        )
    )
    if not isinstance(authorization, DeliveryAuthorization):
        raise UnsafeDeliveryError(
            "The final delivery preflight did not return a verified DeliveryAuthorization."
        )
    if (
        authorization.campaign_id != clean(campaign_id)
        or authorization.selected != len(selected)
        or not authorization.policy_hash
    ):
        raise UnsafeDeliveryError(
            "The final DeliveryAuthorization does not match the exact selected batch."
        )
    # A hook receives immutable snapshots, but it may also close over caller
    # state.  Re-run the core seal/sender/duplicate checks after it returns so
    # accidental mutation cannot create a check-then-send bypass.
    post_preflight_batch = validate_send_batch(
        rows,
        campaign_id=campaign_id,
        settings=settings,
        allow_cross_campaign_recipients=allow_cross_campaign_recipients,
        require_delivery_approval=True,
    )
    post_preflight_selected = (
        post_preflight_batch[:max_messages] if max_messages > 0 else post_preflight_batch
    )
    if [id(row) for row in post_preflight_selected] != [id(row) for row in selected]:
        raise UnsafeDeliveryError("The selected delivery batch changed during final preflight.")
    prepared = [(row, _message_for(row, settings)) for row in selected]
    server = connector(settings)
    sent = 0
    failed = 0
    uncertain = 0
    try:
        for index, (row, message) in enumerate(prepared):
            row["Message ID"] = str(message["Message-ID"])
            row["Draft Status"] = "Sending"
            row["Last Attempt At"] = utc_now_iso()
            row["Error"] = ""
            persist(rows)
            try:
                server.send_message(message)
            except Exception as exc:
                definitive = _is_definitive_smtp_refusal(exc)
                if definitive:
                    row["Draft Status"] = "Failed"
                    row["Error"] = _delivery_error(exc, uncertain=False)
                    failed += 1
                else:
                    # The server may have accepted the DATA command before a
                    # timeout/disconnect reached the client.  Keep the durable
                    # Sending state so automation cannot retry it.
                    row["Draft Status"] = "Sending"
                    row["Error"] = _delivery_error(exc, uncertain=True)
                    uncertain += 1
            else:
                row["Draft Status"] = "Sent"
                row["Sent At"] = utc_now_iso()
                sent += 1
            persist(rows)
            if uncertain:
                # The connection and this recipient now require human/provider
                # reconciliation.  Do not risk additional messages on it.
                break
            if delay_seconds > 0 and index < len(prepared) - 1:
                time.sleep(delay_seconds)
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return {
        "selected": len(selected),
        "sent": sent,
        "failed": failed,
        "uncertain": uncertain,
    }


__all__ = [
    "CONFIRMATION_PHRASE",
    "DeliveryPreflight",
    "DeliveryPreflightContext",
    "DuplicateRecipientError",
    "MailSettings",
    "SenderIdentityMismatchError",
    "UnsafeDeliveryError",
    "deliver_approved_drafts",
    "live_send_lock",
    "sendable_drafts",
    "validate_mail_settings",
    "validate_approved_sender",
    "validate_send_batch",
]
