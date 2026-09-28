#!/usr/bin/env python3
"""Generate reviewable invitation drafts from valid Approved candidates only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import read_csv, read_table, write_csv, write_workbook
from speaker_pipeline.drafts import campaign_id_from_config, generate_drafts, load_invitation_config
from speaker_pipeline.evidence import load_evidence
from speaker_pipeline.locking import LedgerLock
from speaker_pipeline.policy import campaign_policy_hash
from speaker_pipeline.schema import CANDIDATE_COLUMNS, DRAFT_COLUMNS
from speaker_pipeline.targets import load_campaigns


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate invitation drafts; never sends email.")
    parser.add_argument("--candidates", type=Path, default=PROJECT_ROOT / "data" / "candidates.csv")
    parser.add_argument("--candidate-sheet")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "invitation.json")
    parser.add_argument(
        "--campaigns",
        type=Path,
        default=PROJECT_ROOT / "config" / "campaigns.csv",
        help="Canonical campaign policy used to bind every generated draft.",
    )
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "email_drafts.csv")
    parser.add_argument("--evidence", type=Path, default=PROJECT_ROOT / "data" / "evidence.csv")
    parser.add_argument(
        "--preview", type=Path, default=PROJECT_ROOT / "outputs" / "email_draft_review.xlsx"
    )
    parser.add_argument(
        "--allow-legacy-unscoped-candidates",
        action="store_true",
        help=(
            "Generate review-only drafts for genuine pre-1.1 candidates with no campaign or "
            "evidence identifiers. Such drafts remain ineligible for live delivery."
        ),
    )
    args = parser.parse_args()
    invitation = load_invitation_config(args.config)
    campaign_id = campaign_id_from_config(invitation)
    campaigns = load_campaigns(args.campaigns)
    matching = [campaign for campaign in campaigns if campaign.campaign_id == campaign_id]
    if len(matching) != 1:
        raise SystemExit(
            "Invitation config must name exactly one Campaign ID present in --campaigns."
        )
    campaign = matching[0]
    if invitation["sender_organization"].strip() != campaign.sender_organization:
        raise SystemExit(
            "Invitation sender_organization must exactly match Campaign Sender Organization."
        )
    candidates = read_table(args.candidates, CANDIDATE_COLUMNS, args.candidate_sheet)
    evidence = load_evidence(args.evidence) if args.evidence.exists() else []
    with LedgerLock(args.output):
        existing = read_csv(args.output, DRAFT_COLUMNS) if args.output.exists() else []
        drafts = generate_drafts(
            candidates,
            invitation,
            existing,
            evidence_records=evidence,
            allow_historical_targets=campaign.allow_historical_targets,
            allow_legacy_unscoped_candidates=args.allow_legacy_unscoped_candidates,
            campaign_policy_hash=campaign_policy_hash(campaign),
        )
        write_csv(args.output, DRAFT_COLUMNS, drafts)
    write_workbook(args.preview, "Email Drafts", DRAFT_COLUMNS, drafts)
    print(f"Drafts generated: {len(drafts)}")
    print(f"Draft review CSV: {args.output}")
    print(f"Draft review workbook: {args.preview}")
    print("No email was sent. Review each draft and set Draft Status to Approved before delivery.")


if __name__ == "__main__":
    main()
