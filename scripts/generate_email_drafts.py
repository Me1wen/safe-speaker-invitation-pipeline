#!/usr/bin/env python3
"""Generate reviewable invitation drafts from valid Approved candidates only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import read_csv, read_table, write_csv, write_workbook
from speaker_pipeline.drafts import generate_drafts, load_invitation_config
from speaker_pipeline.schema import CANDIDATE_COLUMNS, DRAFT_COLUMNS


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate invitation drafts; never sends email.")
    parser.add_argument("--candidates", type=Path, default=PROJECT_ROOT / "data" / "candidates.csv")
    parser.add_argument("--candidate-sheet")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "invitation.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "email_drafts.csv")
    parser.add_argument(
        "--preview", type=Path, default=PROJECT_ROOT / "outputs" / "email_draft_review.xlsx"
    )
    args = parser.parse_args()
    candidates = read_table(args.candidates, CANDIDATE_COLUMNS, args.candidate_sheet)
    existing = read_csv(args.output, DRAFT_COLUMNS) if args.output.exists() else []
    drafts = generate_drafts(candidates, load_invitation_config(args.config), existing)
    write_csv(args.output, DRAFT_COLUMNS, drafts)
    write_workbook(args.preview, "Email Drafts", DRAFT_COLUMNS, drafts)
    print(f"Drafts generated: {len(drafts)}")
    print(f"Draft review CSV: {args.output}")
    print(f"Draft review workbook: {args.preview}")
    print("No email was sent. Review each draft and set Draft Status to Approved before delivery.")


if __name__ == "__main__":
    main()
