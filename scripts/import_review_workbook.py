#!/usr/bin/env python3
"""Import an exactly-matching reviewed XLSX table back to canonical CSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import read_csv, read_table, write_csv
from speaker_pipeline.evidence import load_evidence
from speaker_pipeline.locking import LedgerLock, LockTimeoutError
from speaker_pipeline.review import ReviewMergeError, merge_review_rows
from speaker_pipeline.schema import CANDIDATE_COLUMNS, DRAFT_COLUMNS
from speaker_pipeline.validation import validate_candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a reviewed candidate or draft workbook.")
    parser.add_argument("--kind", choices=["candidates", "drafts"], required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sheet")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--approver",
        default="",
        help="Human reviewer identity; required when a row transitions to Approved.",
    )
    parser.add_argument("--lock-timeout", type=float, default=10.0)
    parser.add_argument("--evidence", type=Path, default=PROJECT_ROOT / "data" / "evidence.csv")
    args = parser.parse_args()
    if args.kind == "candidates":
        columns = CANDIDATE_COLUMNS
        output = args.output or PROJECT_ROOT / "data" / "candidates.csv"
    else:
        columns = DRAFT_COLUMNS
        output = args.output or PROJECT_ROOT / "data" / "email_drafts.csv"
    if not output.exists():
        raise SystemExit(
            f"Canonical ledger does not exist: {output}. Run create_workspace/collection first."
        )
    try:
        with LedgerLock(output, timeout=args.lock_timeout):
            canonical = read_csv(output, columns)
            reviewed = read_table(args.input, columns, args.sheet)
            rows = merge_review_rows(canonical, reviewed, kind=args.kind, approver=args.approver)
            if args.kind == "candidates":
                evidence = load_evidence(args.evidence) if args.evidence.exists() else []
                high = [
                    issue
                    for issue in validate_candidates(rows, evidence)
                    if issue["Severity"] == "High"
                ]
                if high:
                    print(f"WARNING: imported table has {len(high)} high-severity QA issue(s).")
            write_csv(output, columns, rows)
    except (LockTimeoutError, ReviewMergeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Rows imported or preserved: {len(rows)}")
    print(f"Canonical CSV: {output}")


if __name__ == "__main__":
    main()
