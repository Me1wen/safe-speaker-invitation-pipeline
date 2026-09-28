#!/usr/bin/env python3
"""Resolve one uncertain SMTP attempt using provider-side evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import clean, read_csv, utc_now_iso, write_csv
from speaker_pipeline.locking import LedgerLock
from speaker_pipeline.schema import DRAFT_COLUMNS

CONFIRMATION_PHRASE = "RECONCILE_UNCERTAIN_DELIVERY"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "data" / "email_drafts.csv",
    )
    parser.add_argument("--draft-id", required=True)
    parser.add_argument(
        "--resolution",
        choices=("provider-accepted", "provider-rejected"),
        required=True,
    )
    parser.add_argument("--provider-reference", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--confirm", default="")
    return parser


def reconcile(argv: list[str] | None = None) -> dict[str, str]:
    args = _parser().parse_args(argv)
    if args.confirm != CONFIRMATION_PHRASE:
        raise SystemExit(f"Reconciliation requires --confirm {CONFIRMATION_PHRASE}")
    reviewer = clean(args.reviewer)
    provider_reference = clean(args.provider_reference)
    if not reviewer or not provider_reference:
        raise SystemExit("--reviewer and --provider-reference must not be blank.")
    if not args.input.is_file():
        raise SystemExit(f"Delivery ledger does not exist: {args.input}")

    with LedgerLock(args.input):
        rows = read_csv(args.input, DRAFT_COLUMNS)
        matches = [row for row in rows if clean(row.get("Draft ID")) == clean(args.draft_id)]
        if len(matches) != 1:
            raise SystemExit("Exactly one delivery row must match --draft-id.")
        row = matches[0]
        if clean(row.get("Draft Status")) != "Sending":
            raise SystemExit("Only a Sending/uncertain delivery can be reconciled.")
        if not clean(row.get("Last Attempt At")) or not clean(row.get("Message ID")):
            raise SystemExit(
                "The uncertain row lacks Last Attempt At or Message ID; manual forensic "
                "review is required before changing it."
            )

        resolved_at = utc_now_iso()
        row["Delivery Resolution"] = args.resolution
        row["Reconciled At"] = resolved_at
        row["Reconciled By"] = reviewer
        row["Provider Reference"] = provider_reference
        if args.resolution == "provider-accepted":
            row["Draft Status"] = "Sent"
            row["Sent At"] = row.get("Sent At") or resolved_at
            row["Error"] = ""
        else:
            # Only provider-confirmed non-acceptance is retryable.  The existing
            # v2 approval remains bound, but review workflow must explicitly
            # return Failed to Approved before another attempt.
            row["Draft Status"] = "Failed"
            row["Error"] = "Provider confirmed that the message was not accepted."
        write_csv(args.input, DRAFT_COLUMNS, rows)
        return row


def main(argv: list[str] | None = None) -> None:
    row = reconcile(argv)
    print(f"Reconciled draft: {row['Draft ID']}")
    print(f"Delivery status: {row['Draft Status']}")
    print("No email was sent by this command.")


if __name__ == "__main__":
    main()
