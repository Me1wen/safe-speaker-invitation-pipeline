#!/usr/bin/env python3
"""Validate the candidate review gate and write a QA report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import read_table, write_csv
from speaker_pipeline.schema import CANDIDATE_COLUMNS, QA_COLUMNS
from speaker_pipeline.validation import validate_candidates


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate candidate records before drafting invitations."
    )
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "data" / "candidates.csv")
    parser.add_argument("--sheet")
    parser.add_argument(
        "--qa-output", type=Path, default=PROJECT_ROOT / "outputs" / "candidate_qa.csv"
    )
    args = parser.parse_args()
    rows = read_table(args.input, CANDIDATE_COLUMNS, args.sheet)
    issues = validate_candidates(rows)
    write_csv(args.qa_output, QA_COLUMNS, issues)
    high = sum(issue["Severity"] == "High" for issue in issues)
    approved = sum(row.get("Review Status") == "Approved" for row in rows)
    print(f"Rows checked: {len(rows)}")
    print(f"Approved rows: {approved}")
    print(f"QA issues: {len(issues)} ({high} high)")
    print(f"QA report: {args.qa_output}")


if __name__ == "__main__":
    main()
