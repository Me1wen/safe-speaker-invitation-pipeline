#!/usr/bin/env python3
"""Dry-run by default; deliver only explicitly Approved mail drafts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import read_table, write_csv
from speaker_pipeline.mailer import (
    CONFIRMATION_PHRASE,
    MailSettings,
    deliver_approved_drafts,
    sendable_drafts,
)
from speaker_pipeline.schema import DRAFT_COLUMNS


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run or send manually Approved invitation drafts."
    )
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "data" / "email_drafts.csv")
    parser.add_argument("--sheet")
    parser.add_argument("--send", action="store_true", help="Enable live SMTP delivery.")
    parser.add_argument(
        "--confirm", default="", help=f"Required for live send: {CONFIRMATION_PHRASE}"
    )
    parser.add_argument("--max-messages", type=int, default=0, help="0 means all Approved drafts.")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    rows = read_table(args.input, DRAFT_COLUMNS, args.sheet)
    selected = sendable_drafts(rows, args.max_messages)
    print(f"Approved unsent drafts selected: {len(selected)}")
    target_label = "LIVE TARGET" if args.send else "DRY-RUN TARGET"
    for row in selected:
        print(f"{target_label}: {row['To Email']} | {row['Subject']}")
    if not args.send:
        print("Dry run complete. No SMTP connection was opened and no email was sent.")
        return
    if args.input.suffix.casefold() != ".csv":
        raise SystemExit(
            "Live send requires canonical CSV input so delivery status can be saved safely."
        )
    if args.confirm != CONFIRMATION_PHRASE:
        raise SystemExit(f"Live send requires --confirm {CONFIRMATION_PHRASE}")
    try:
        settings = MailSettings.from_environment()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    def persist(updated_rows: list[dict[str, str]]) -> None:
        write_csv(args.input, DRAFT_COLUMNS, updated_rows)

    try:
        result = deliver_approved_drafts(
            rows,
            settings,
            send=True,
            confirmation=args.confirm,
            max_messages=args.max_messages,
            delay_seconds=args.delay,
            persist=persist,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Sent: {result['sent']}")
    print(f"Failed: {result['failed']}")
    print(f"Updated delivery ledger: {args.input}")


if __name__ == "__main__":
    main()
