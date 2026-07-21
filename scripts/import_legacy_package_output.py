#!/usr/bin/env python3
"""Migrate old academic/industry output into the canonical review table."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import merge_candidates, read_csv, write_csv
from speaker_pipeline.legacy import migrate_legacy_rows, read_legacy_table
from speaker_pipeline.schema import CANDIDATE_COLUMNS


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely import output from either original collection package."
    )
    parser.add_argument("--type", choices=["academic", "industry"], required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sheet")
    parser.add_argument("--review", type=Path, default=PROJECT_ROOT / "data" / "candidates.csv")
    args = parser.parse_args()
    existing = read_csv(args.review, CANDIDATE_COLUMNS) if args.review.exists() else []
    migrated = migrate_legacy_rows(read_legacy_table(args.input, args.sheet), args.type)
    merged = merge_candidates(existing, migrated)
    write_csv(args.review, CANDIDATE_COLUMNS, merged)
    print(f"Legacy rows migrated: {len(migrated)}")
    print(f"Review rows after merge: {len(merged)}")
    print("All migrated rows are Needs Review and must be explicitly reapproved.")


if __name__ == "__main__":
    main()
