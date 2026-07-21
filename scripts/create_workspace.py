#!/usr/bin/env python3
"""Create canonical review and draft tables without overwriting existing work."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import write_csv
from speaker_pipeline.schema import CANDIDATE_COLUMNS, DRAFT_COLUMNS


def main() -> None:
    data_dir = PROJECT_ROOT / "data"
    output_dir = PROJECT_ROOT / "outputs"
    data_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    tables = (
        (data_dir / "candidates.csv", CANDIDATE_COLUMNS),
        (data_dir / "email_drafts.csv", DRAFT_COLUMNS),
    )
    for path, columns in tables:
        if path.exists():
            print(f"Kept existing: {path}")
        else:
            write_csv(path, columns, [])
            print(f"Created: {path}")
    active_industry = PROJECT_ROOT / "config" / "industry_sources.csv"
    if not active_industry.exists():
        shutil.copyfile(PROJECT_ROOT / "config" / "industry_sources.empty.csv", active_industry)
        print(f"Created: {active_industry}")
    invitation = PROJECT_ROOT / "config" / "invitation.json"
    if not invitation.exists():
        shutil.copyfile(PROJECT_ROOT / "config" / "invitation.example.json", invitation)
        print(f"Created: {invitation}")


if __name__ == "__main__":
    main()
