#!/usr/bin/env python3
"""Add, inspect, or explicitly revoke global outreach suppressions."""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import utc_now_iso, write_csv
from speaker_pipeline.locking import LedgerLock
from speaker_pipeline.policy import SuppressionRecord, load_suppressions
from speaker_pipeline.schema import SUPPRESSION_COLUMNS, SUPPRESSION_SCOPES

REVOCATION_PHRASE = "REVOKE_SUPPRESSION"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "data" / "suppressions.csv",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="Add an immediately active suppression.")
    add.add_argument("--scope", choices=sorted(SUPPRESSION_SCOPES), required=True)
    add.add_argument("--value", required=True)
    add.add_argument("--reason", required=True)
    add.add_argument("--created-by", required=True)
    add.add_argument("--expires-at", default="")
    add.add_argument("--notes", default="")

    revoke = subparsers.add_parser(
        "revoke", help="Revoke one suppression after an explicit human decision."
    )
    revoke.add_argument("--id", required=True)
    revoke.add_argument("--revoked-by", required=True)
    revoke.add_argument("--confirm", default="")

    listing = subparsers.add_parser("list", help="List suppression metadata.")
    listing.add_argument(
        "--show-values",
        action="store_true",
        help="Show suppressed addresses/domains/identifiers in terminal output.",
    )
    return parser


def _new_record(args: argparse.Namespace) -> SuppressionRecord:
    created_at = utc_now_iso()
    seed = f"{args.scope}|{args.value}|{created_at}"
    identifier = f"SUP-{hashlib.sha256(seed.encode()).hexdigest()[:16].upper()}"
    return SuppressionRecord.from_row(
        {
            "Schema Version": "1.1",
            "Suppression ID": identifier,
            "Scope": args.scope,
            "Value": args.value,
            "Reason": args.reason,
            "Status": "Active",
            "Created At": created_at,
            "Created By": args.created_by,
            "Expires At": args.expires_at,
            "Revoked At": "",
            "Revoked By": "",
            "Notes": args.notes,
        }
    )


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    args.input.parent.mkdir(parents=True, exist_ok=True)
    if not args.input.exists():
        write_csv(args.input, SUPPRESSION_COLUMNS, [])

    with LedgerLock(args.input):
        records = load_suppressions(args.input)
        if args.command == "list":
            for record in records:
                value = record.value if args.show_values else "[hidden]"
                print(
                    f"{record.suppression_id} | {record.status} | "
                    f"{record.scope}={value} | {record.reason}"
                )
            print(f"Suppressions: {len(records)}")
            return

        if args.command == "add":
            new_record = _new_record(args)
            if any(
                record.status == "Active"
                and record.scope == new_record.scope
                and record.value == new_record.value
                for record in records
            ):
                raise SystemExit("An active suppression already exists for that scope and value.")
            records.append(new_record)
            write_csv(args.input, SUPPRESSION_COLUMNS, [record.to_row() for record in records])
            print(f"Added active suppression: {new_record.suppression_id}")
            return

        if args.confirm != REVOCATION_PHRASE:
            raise SystemExit(f"Revocation requires --confirm {REVOCATION_PHRASE}")
        matches = [record for record in records if record.suppression_id == args.id]
        if len(matches) != 1:
            raise SystemExit("Exactly one suppression must match --id.")
        target = matches[0]
        if target.status != "Active":
            raise SystemExit("Only an Active suppression can be revoked.")
        replacement = replace(
            target,
            status="Revoked",
            revoked_at=utc_now_iso(),
            revoked_by=args.revoked_by.strip(),
        )
        if not replacement.revoked_by:
            raise SystemExit("--revoked-by must identify the human reviewer.")
        updated = [
            replacement if record.suppression_id == args.id else record for record in records
        ]
        write_csv(args.input, SUPPRESSION_COLUMNS, [record.to_row() for record in updated])
        print(f"Revoked suppression: {target.suppression_id}")


if __name__ == "__main__":
    main()
