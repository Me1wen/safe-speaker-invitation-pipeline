#!/usr/bin/env python3
"""Import an exactly-matching reviewed XLSX table back to canonical CSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import read_table, write_csv
from speaker_pipeline.schema import CANDIDATE_COLUMNS, DRAFT_COLUMNS
from speaker_pipeline.validation import validate_candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a reviewed candidate or draft workbook.")
    parser.add_argument("--kind", choices=["candidates", "drafts"], required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sheet")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.kind == "candidates":
        columns = CANDIDATE_COLUMNS
        output = args.output or PROJECT_ROOT / "data" / "candidates.csv"
    else:
        columns = DRAFT_COLUMNS
        output = args.output or PROJECT_ROOT / "data" / "email_drafts.csv"
    rows = read_table(args.input, columns, args.sheet)
    if args.kind == "candidates":
        high = [issue for issue in validate_candidates(rows) if issue["Severity"] == "High"]
        if high:
            print(f"WARNING: imported table has {len(high)} high-severity QA issue(s).")
    write_csv(output, columns, rows)
    print(f"Rows imported: {len(rows)}")
    print(f"Canonical CSV: {output}")


if __name__ == "__main__":
    main()
