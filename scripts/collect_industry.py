#!/usr/bin/env python3
"""Collect verified senior-leader rows and merge them into the review table."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import merge_candidates, read_csv, read_table, write_csv
from speaker_pipeline.industry import IndustrySource, collect_industry
from speaker_pipeline.schema import CANDIDATE_COLUMNS, INDUSTRY_SOURCE_COLUMNS
from speaker_pipeline.web import OfficialWebClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect public industry speaker candidates.")
    parser.add_argument(
        "--sources", type=Path, default=PROJECT_ROOT / "config" / "industry_sources.csv"
    )
    parser.add_argument("--review", type=Path, default=PROJECT_ROOT / "data" / "candidates.csv")
    parser.add_argument("--sheet")
    parser.add_argument("--allow-live-fetch", action="store_true")
    parser.add_argument("--limit-per-source", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    source_rows = read_csv(args.sources, INDUSTRY_SOURCE_COLUMNS)
    sources = [IndustrySource.from_row(row) for row in source_rows]
    existing = (
        read_table(args.review, CANDIDATE_COLUMNS, args.sheet) if args.review.exists() else []
    )
    client = OfficialWebClient(
        allow_live_fetch=args.allow_live_fetch,
        delay_seconds=args.delay,
        timeout_seconds=args.timeout,
    )
    discovered, warnings = collect_industry(sources, client, limit_per_source=args.limit_per_source)
    merged = merge_candidates(existing, discovered)
    output = (
        args.review
        if args.review.suffix.casefold() == ".csv"
        else PROJECT_ROOT / "data" / "candidates.csv"
    )
    write_csv(output, CANDIDATE_COLUMNS, merged)
    print(f"Industry sources: {len(sources)}")
    print(f"Newly discovered valid rows: {len(discovered)}")
    print(f"Review rows after merge: {len(merged)}")
    print(f"Review table: {output}")
    for warning in warnings:
        print(f"WARNING: {warning}")


if __name__ == "__main__":
    main()
