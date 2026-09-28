#!/usr/bin/env python3
"""Offline readiness checks for active configuration, delivery policy, and SMTP settings."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import read_csv
from speaker_pipeline.drafts import campaign_id_from_config, load_invitation_config
from speaker_pipeline.evidence import load_evidence, validate_evidence_relations
from speaker_pipeline.industry import IndustrySource
from speaker_pipeline.mailer import MailSettings, validate_mail_settings
from speaker_pipeline.policy import load_suppressions, validate_delivery_policy
from speaker_pipeline.schema import CANDIDATE_COLUMNS, DRAFT_COLUMNS, INDUSTRY_SOURCE_COLUMNS
from speaker_pipeline.targets import (
    load_campaigns,
    load_email_claims,
    load_targets,
    validate_target_relations,
)

T = TypeVar("T")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check active workspace files, delivery policy, and SMTP environment without "
            "opening a network connection."
        )
    )
    parser.add_argument("--campaign-id", default="")
    parser.add_argument("--campaigns", type=Path, default=PROJECT_ROOT / "config" / "campaigns.csv")
    parser.add_argument(
        "--targets", type=Path, default=PROJECT_ROOT / "config" / "industry_targets.csv"
    )
    parser.add_argument("--claims", type=Path, default=PROJECT_ROOT / "config" / "email_claims.csv")
    parser.add_argument(
        "--seed-evidence", type=Path, default=PROJECT_ROOT / "config" / "email_evidence.csv"
    )
    parser.add_argument(
        "--sources", type=Path, default=PROJECT_ROOT / "config" / "industry_sources.csv"
    )
    parser.add_argument(
        "--invitation", type=Path, default=PROJECT_ROOT / "config" / "invitation.json"
    )
    parser.add_argument("--candidates", type=Path, default=PROJECT_ROOT / "data" / "candidates.csv")
    parser.add_argument("--drafts", type=Path, default=PROJECT_ROOT / "data" / "email_drafts.csv")
    parser.add_argument("--evidence", type=Path, default=PROJECT_ROOT / "data" / "evidence.csv")
    parser.add_argument(
        "--suppressions", type=Path, default=PROJECT_ROOT / "data" / "suppressions.csv"
    )
    parser.add_argument("--max-messages", type=int, default=0)
    return parser


def _load(
    path: Path,
    label: str,
    loader: Callable[[Path], T],
    errors: list[str],
) -> T | None:
    if not path.is_file():
        errors.append(f"missing active {label} file: {path}")
        return None
    try:
        return loader(path)
    except (OSError, ValueError) as exc:
        errors.append(f"invalid {label} file {path}: {exc}")
        return None


def run_checks(args: argparse.Namespace) -> list[str]:
    """Return all offline readiness failures without exposing recipients or secrets."""

    errors: list[str] = []
    campaigns = _load(args.campaigns, "campaigns", load_campaigns, errors)
    targets = _load(args.targets, "industry targets", load_targets, errors)
    claims = _load(args.claims, "email claims", load_email_claims, errors)
    seed_evidence = _load(args.seed_evidence, "seed evidence", load_evidence, errors)
    source_rows = _load(
        args.sources,
        "industry sources",
        lambda path: read_csv(path, INDUSTRY_SOURCE_COLUMNS),
        errors,
    )
    candidates = _load(
        args.candidates,
        "candidates",
        lambda path: read_csv(path, CANDIDATE_COLUMNS),
        errors,
    )
    drafts = _load(
        args.drafts,
        "email drafts",
        lambda path: read_csv(path, DRAFT_COLUMNS),
        errors,
    )
    evidence = _load(args.evidence, "evidence", load_evidence, errors)
    suppressions = _load(args.suppressions, "suppressions", load_suppressions, errors)
    invitation = _load(args.invitation, "invitation", load_invitation_config, errors)

    sources: list[IndustrySource] | None = None
    if source_rows is not None:
        try:
            sources = [IndustrySource.from_row(row) for row in source_rows]
        except ValueError as exc:
            errors.append(f"invalid industry source row: {exc}")

    if campaigns is not None and not campaigns:
        errors.append("campaigns.csv has no campaign rows")
    if targets is not None and not targets:
        errors.append("industry_targets.csv has no configured target rows")
    if sources is not None and not sources:
        errors.append("industry_sources.csv has no configured source rows")

    if campaigns is not None and targets is not None and claims is not None:
        errors.extend(validate_target_relations(campaigns, targets, claims))
    if seed_evidence is not None and targets is not None and claims is not None:
        errors.extend(validate_evidence_relations(seed_evidence, targets, claims))

    campaign = None
    if campaigns:
        requested = args.campaign_id.strip()
        matches = (
            [record for record in campaigns if record.campaign_id == requested]
            if requested
            else campaigns
        )
        if len(matches) != 1:
            errors.append("doctor requires exactly one campaign; provide --campaign-id")
        else:
            campaign = matches[0]

    if invitation is not None:
        try:
            invitation_campaign = campaign_id_from_config(invitation)
        except ValueError as exc:
            errors.append(f"invalid invitation campaign: {exc}")
        else:
            if campaign is not None and invitation_campaign != campaign.campaign_id:
                errors.append("invitation campaign_id does not match the selected campaign")

    try:
        smtp = MailSettings.from_environment()
        validate_mail_settings(smtp)
    except (TypeError, ValueError) as exc:
        errors.append(f"SMTP configuration is not ready: {exc}")

    if all(value is not None for value in (campaign, candidates, drafts, evidence, suppressions)):
        try:
            validate_delivery_policy(
                drafts,
                campaign,
                candidates,
                evidence,
                suppressions,
                campaign_id=campaign.campaign_id,
                max_messages=args.max_messages,
            )
        except ValueError as exc:
            errors.append(f"delivery policy is not ready: {exc}")

    return errors


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.max_messages < 0:
        raise SystemExit("--max-messages must be zero or greater.")
    errors = run_checks(args)
    print("Offline doctor: no network connection was attempted.")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Readiness: FAILED ({len(errors)} issue(s))")
        raise SystemExit(1)
    print("SMTP configuration: valid (not connected)")
    print("Delivery policy: authorized for the current approved batch")
    print("Readiness: PASS")


if __name__ == "__main__":
    main()
