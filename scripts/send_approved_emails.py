#!/usr/bin/env python3
"""Dry-run by default; deliver only explicitly Approved mail drafts."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import read_csv, read_table, write_csv
from speaker_pipeline.evidence import load_evidence
from speaker_pipeline.locking import LedgerLock, LockTimeoutError
from speaker_pipeline.mailer import (
    CONFIRMATION_PHRASE,
    DeliveryPreflightContext,
    MailSettings,
    deliver_approved_drafts,
    sendable_drafts,
)
from speaker_pipeline.policy import load_suppressions, validate_delivery_policy
from speaker_pipeline.schema import CANDIDATE_COLUMNS, DRAFT_COLUMNS
from speaker_pipeline.targets import load_campaigns


def _parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--campaign-id",
        default="",
        help="Required for live send; scopes approval and duplicate-recipient checks.",
    )
    parser.add_argument(
        "--campaigns",
        type=Path,
        help="Required for live send: explicit canonical campaign policy CSV.",
    )
    parser.add_argument(
        "--suppressions",
        type=Path,
        help="Required for live send: explicit canonical suppression CSV.",
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        help="Required for live send: explicit canonical candidate CSV.",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        help="Required for live send: explicit canonical evidence CSV.",
    )
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--lock-timeout", type=float, default=10.0)
    parser.add_argument(
        "--show-targets",
        action="store_true",
        help="Print recipient addresses and subjects. This may expose personal data in logs.",
    )
    return parser


def _require_live_file(path: Path | None, option: str) -> Path:
    if path is None:
        raise SystemExit(f"Live send requires an explicit {option} path.")
    if not path.is_file():
        raise SystemExit(f"Live send input does not exist or is not a file ({option}): {path}")
    return path


@contextmanager
def _live_input_locks(paths: list[Path], timeout: float) -> Iterator[None]:
    """Lock every live ledger in one deterministic cross-process order."""

    ordered = sorted({path.resolve() for path in paths}, key=lambda path: str(path))
    with ExitStack() as stack:
        for path in ordered:
            stack.enter_context(LedgerLock(path, timeout=timeout))
        yield


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.max_messages < 0:
        raise SystemExit("--max-messages must be zero or greater.")
    if args.delay < 0:
        raise SystemExit("--delay must be zero or greater.")
    if args.lock_timeout < 0:
        raise SystemExit("--lock-timeout must be zero or greater.")
    if not args.input.is_file():
        raise SystemExit(f"Draft input does not exist or is not a file: {args.input}")
    if not args.send:
        rows = read_table(args.input, DRAFT_COLUMNS, args.sheet)
        selected = sendable_drafts(rows, args.max_messages, campaign_id=args.campaign_id)
        print(f"Approved unsent drafts selected: {len(selected)}")
        if args.show_targets:
            for row in selected:
                print(f"DRY-RUN TARGET: {row['To Email']} | {row['Subject']}")
        elif selected:
            print("Target details hidden. Re-run with --show-targets only in a private terminal.")
        print("Dry run complete. No SMTP connection was opened and no email was sent.")
        return
    if args.input.suffix.casefold() != ".csv":
        raise SystemExit(
            "Live send requires canonical CSV input so delivery status can be saved safely."
        )
    if args.confirm != CONFIRMATION_PHRASE:
        raise SystemExit(f"Live send requires --confirm {CONFIRMATION_PHRASE}")
    if not args.campaign_id.strip():
        raise SystemExit("Live send requires an explicit --campaign-id.")
    campaigns_path = _require_live_file(args.campaigns, "--campaigns")
    suppressions_path = _require_live_file(args.suppressions, "--suppressions")
    candidates_path = _require_live_file(args.candidates, "--candidates")
    evidence_path = _require_live_file(args.evidence, "--evidence")
    try:
        settings = MailSettings.from_environment()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        # Lock all policy inputs in one stable order, then re-read every ledger.
        # The locks remain held through Sending/Sent/Failed persistence updates.
        with _live_input_locks(
            [args.input, campaigns_path, candidates_path, evidence_path, suppressions_path],
            args.lock_timeout,
        ):
            rows = read_csv(args.input, DRAFT_COLUMNS)
            matching_campaigns = [
                campaign
                for campaign in load_campaigns(campaigns_path)
                if campaign.campaign_id == args.campaign_id.strip()
            ]
            if len(matching_campaigns) != 1:
                raise ValueError("Exactly one campaign row must match --campaign-id.")
            campaign = matching_campaigns[0]
            candidates = read_csv(candidates_path, CANDIDATE_COLUMNS)
            evidence = load_evidence(evidence_path)
            suppressions = load_suppressions(suppressions_path)
            authorization = validate_delivery_policy(
                rows,
                campaign,
                candidates,
                evidence,
                suppressions,
                campaign_id=args.campaign_id,
                max_messages=args.max_messages,
            )
            selected = sendable_drafts(rows, args.max_messages, campaign_id=args.campaign_id)
            print(f"Approved unsent drafts selected: {len(selected)}")
            print(f"Campaign attempts before this batch: {authorization.attempted}")
            print(f"Campaign capacity after this batch: {authorization.remaining_after_batch}")
            if args.show_targets:
                for row in selected:
                    print(f"LIVE TARGET: {row['To Email']} | {row['Subject']}")
            else:
                print("Target details hidden; live preflight passed all current policy ledgers.")

            def persist(updated_rows: list[dict[str, str]]) -> None:
                write_csv(args.input, DRAFT_COLUMNS, updated_rows)

            def final_preflight(context: DeliveryPreflightContext):
                # Mailer validation determines the exact batch first. Re-run the
                # deployment policy against that immutable snapshot while all
                # authoritative input ledgers remain locked.
                return validate_delivery_policy(
                    [dict(row) for row in context.rows],
                    campaign,
                    candidates,
                    evidence,
                    suppressions,
                    campaign_id=context.campaign_id,
                    max_messages=context.max_messages,
                )

            result = deliver_approved_drafts(
                rows,
                settings,
                send=True,
                confirmation=args.confirm,
                max_messages=args.max_messages,
                delay_seconds=args.delay,
                campaign_id=args.campaign_id,
                persist=persist,
                lock_held=True,
                preflight=final_preflight,
            )
    except (LockTimeoutError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Sent: {result['sent']}")
    print(f"Failed: {result['failed']}")
    print(f"Uncertain: {result['uncertain']}")
    print(f"Updated delivery ledger: {args.input}")


if __name__ == "__main__":
    main()
