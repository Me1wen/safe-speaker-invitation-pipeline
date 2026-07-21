#!/usr/bin/env python3
"""Export canonical CSV tables to human-friendly Excel review workbooks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import read_csv, write_workbook
from speaker_pipeline.schema import CANDIDATE_COLUMNS, DRAFT_COLUMNS


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export candidate or draft CSV to XLSX for review."
    )
    parser.add_argument("--kind", choices=["candidates", "drafts"], required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.kind == "candidates":
        columns, sheet = CANDIDATE_COLUMNS, "Candidates"
        source = args.input or PROJECT_ROOT / "data" / "candidates.csv"
        output = args.output or PROJECT_ROOT / "outputs" / "candidate_review.xlsx"
    else:
        columns, sheet = DRAFT_COLUMNS, "Email Drafts"
        source = args.input or PROJECT_ROOT / "data" / "email_drafts.csv"
        output = args.output or PROJECT_ROOT / "outputs" / "email_draft_review.xlsx"
    rows = read_csv(source, columns)
    write_workbook(output, sheet, columns, rows)
    print(f"Rows exported: {len(rows)}")
    print(f"Workbook: {output}")


if __name__ == "__main__":
    main()
