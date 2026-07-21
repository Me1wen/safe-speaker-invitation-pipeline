"""SMTP delivery with dry-run default, two explicit approvals, and crash-safe states."""

from __future__ import annotations

import os
import smtplib
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from .common import EMAIL_RE, clean, utc_now_iso

CONFIRMATION_PHRASE = "SEND_APPROVED_EMAILS"


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
        )


def sendable_drafts(rows: list[dict[str, str]], max_messages: int = 0) -> list[dict[str, str]]:
    selected = [row for row in rows if clean(row.get("Draft Status")) == "Approved"]
    return selected[:max_messages] if max_messages > 0 else selected


def validate_mail_settings(settings: MailSettings) -> None:
    if not settings.host or not 1 <= settings.port <= 65535:
        raise ValueError("SMTP host/port is invalid.")
    for label, value in (
        ("SMTP_FROM_EMAIL", settings.from_email),
        ("SMTP_REPLY_TO", settings.reply_to),
    ):
        if value and not EMAIL_RE.fullmatch(value):
            raise ValueError(f"{label} is not a valid plain email address.")
    if settings.use_ssl and settings.starttls:
        raise ValueError("Choose SMTP_USE_SSL or SMTP_STARTTLS, not both.")


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
    persist: Callable[[list[dict[str, str]]], None] | None = None,
    connector: Callable[[MailSettings], object] = _connect,
) -> dict[str, int]:
    selected = sendable_drafts(rows, max_messages)
    if not send:
        return {"selected": len(selected), "sent": 0, "failed": 0}
    if confirmation != CONFIRMATION_PHRASE:
        raise ValueError(f"Live send requires confirmation phrase: {CONFIRMATION_PHRASE}")
    validate_mail_settings(settings)
    if not selected:
        return {"selected": 0, "sent": 0, "failed": 0}

    server = connector(settings)
    sent = 0
    failed = 0
    try:
        for row in selected:
            row["Draft Status"] = "Sending"
            row["Last Attempt At"] = utc_now_iso()
            row["Error"] = ""
            if persist:
                persist(rows)
            try:
                message = _message_for(row, settings)
                row["Message ID"] = str(message["Message-ID"])
                server.send_message(message)
            except Exception as exc:
                row["Draft Status"] = "Failed"
                row["Error"] = clean(exc)
                failed += 1
            else:
                row["Draft Status"] = "Sent"
                row["Sent At"] = utc_now_iso()
                sent += 1
            if persist:
                persist(rows)
            if delay_seconds > 0 and row is not selected[-1]:
                time.sleep(delay_seconds)
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return {"selected": len(selected), "sent": sent, "failed": failed}
