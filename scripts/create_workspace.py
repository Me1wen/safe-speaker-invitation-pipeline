#!/usr/bin/env python3
"""Create canonical review and draft tables without overwriting existing work."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import write_csv
from speaker_pipeline.schema import (
    CAMPAIGN_COLUMNS,
    CANDIDATE_COLUMNS,
    DRAFT_COLUMNS,
    EMAIL_CLAIM_COLUMNS,
    EVIDENCE_COLUMNS,
    INDUSTRY_SOURCE_COLUMNS,
    SCHEMA_VERSION,
    SUPPRESSION_COLUMNS,
    TARGET_COLUMNS,
)

SAFE_DRAFT_CAMPAIGN = {
    "Schema Version": SCHEMA_VERSION,
    "Campaign ID": "YOUR-EVENT-2026",
    "Campaign Name": "Configure this draft campaign",
    "Campaign Status": "Draft",
    "Purpose": "Replace every placeholder and review the outreach policy before activation",
    "Owner": "",
    "Sender Organization": "",
    "Research As Of": "",
    "Outreach Not Before": "",
    "Outreach Not After": "",
    "Minimum Direct Email Evidence": "E4 Exact Current Official",
    "Allow Historical Targets": "false",
    "Allow Department Routes": "false",
    "Max Messages": "0",
    "Created At": "",
    "Updated At": "",
    "Notes": "Template only; Draft campaigns are not authorized for live delivery.",
}


def main() -> None:
    data_dir = PROJECT_ROOT / "data"
    output_dir = PROJECT_ROOT / "outputs"
    config_dir = PROJECT_ROOT / "config"
    data_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    config_dir.mkdir(exist_ok=True)
    tables = (
        (data_dir / "candidates.csv", CANDIDATE_COLUMNS),
        (data_dir / "email_drafts.csv", DRAFT_COLUMNS),
        (data_dir / "evidence.csv", EVIDENCE_COLUMNS),
        (data_dir / "suppressions.csv", SUPPRESSION_COLUMNS),
    )
    for path, columns in tables:
        if path.exists():
            print(f"Kept existing: {path}")
        else:
            write_csv(path, columns, [])
            print(f"Created: {path}")
    active_industry = config_dir / "industry_sources.csv"
    if not active_industry.exists():
        write_csv(active_industry, INDUSTRY_SOURCE_COLUMNS, [])
        print(f"Created: {active_industry}")
    invitation = config_dir / "invitation.json"
    if not invitation.exists():
        shutil.copyfile(config_dir / "invitation.example.json", invitation)
        print(f"Created: {invitation}")
    for active_name, columns, rows in (
        ("campaigns.csv", CAMPAIGN_COLUMNS, [SAFE_DRAFT_CAMPAIGN]),
        ("industry_targets.csv", TARGET_COLUMNS, []),
        ("email_claims.csv", EMAIL_CLAIM_COLUMNS, []),
        ("email_evidence.csv", EVIDENCE_COLUMNS, []),
    ):
        active = config_dir / active_name
        if active.exists():
            print(f"Kept existing: {active}")
        else:
            write_csv(active, columns, rows)
            print(f"Created: {active}")


if __name__ == "__main__":
    main()
