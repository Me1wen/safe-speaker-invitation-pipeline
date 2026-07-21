#!/usr/bin/env python3
"""Collect verified academic profile rows and merge them into the review table."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.academic import AcademicSource, collect_academic
from speaker_pipeline.common import merge_candidates, read_csv, read_table, write_csv
from speaker_pipeline.schema import ACADEMIC_SOURCE_COLUMNS, CANDIDATE_COLUMNS
from speaker_pipeline.web import OfficialWebClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect public academic speaker candidates.")
    parser.add_argument(
        "--sources", type=Path, default=PROJECT_ROOT / "config" / "academic_sources.csv"
    )
    parser.add_argument("--review", type=Path, default=PROJECT_ROOT / "data" / "candidates.csv")
    parser.add_argument("--sheet")
    parser.add_argument("--allow-live-fetch", action="store_true")
    parser.add_argument("--limit-per-source", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    source_rows = read_csv(args.sources, ACADEMIC_SOURCE_COLUMNS)
    sources = [AcademicSource.from_row(row) for row in source_rows]
    existing = (
        read_table(args.review, CANDIDATE_COLUMNS, args.sheet) if args.review.exists() else []
    )
    client = OfficialWebClient(
        allow_live_fetch=args.allow_live_fetch,
        delay_seconds=args.delay,
        timeout_seconds=args.timeout,
    )
    discovered, warnings = collect_academic(sources, client, limit_per_source=args.limit_per_source)
    merged = merge_candidates(existing, discovered)
    output = (
        args.review
        if args.review.suffix.casefold() == ".csv"
        else PROJECT_ROOT / "data" / "candidates.csv"
    )
    write_csv(output, CANDIDATE_COLUMNS, merged)
    print(f"Academic sources: {len(sources)}")
    print(f"Newly discovered valid rows: {len(discovered)}")
    print(f"Review rows after merge: {len(merged)}")
    print(f"Review table: {output}")
    for warning in warnings:
        print(f"WARNING: {warning}")


if __name__ == "__main__":
    main()
