#!/usr/bin/env python3
"""Verify an explicit CEO/founder target list and write auditable ledgers."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from speaker_pipeline.common import merge_candidates, read_csv, read_table, write_csv
from speaker_pipeline.evidence import load_evidence, merge_evidence, validate_evidence_relations
from speaker_pipeline.industry import IndustrySource
from speaker_pipeline.locking import LedgerLock
from speaker_pipeline.schema import (
    CANDIDATE_COLUMNS,
    EVIDENCE_COLUMNS,
    INDUSTRY_SOURCE_COLUMNS,
    TARGET_REPORT_COLUMNS,
)
from speaker_pipeline.targeted import collect_targeted_industry
from speaker_pipeline.targets import (
    load_campaigns,
    load_email_claims,
    load_targets,
    validate_target_relations,
)
from speaker_pipeline.web import OfficialWebClient


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify explicit industry-speaker targets. Network access is disabled unless "
            "--allow-live-fetch is supplied."
        )
    )
    parser.add_argument("--campaigns", type=Path, default=PROJECT_ROOT / "config" / "campaigns.csv")
    parser.add_argument(
        "--targets", type=Path, default=PROJECT_ROOT / "config" / "industry_targets.csv"
    )
    parser.add_argument("--claims", type=Path, default=PROJECT_ROOT / "config" / "email_claims.csv")
    parser.add_argument(
        "--evidence",
        type=Path,
        default=PROJECT_ROOT / "config" / "email_evidence.csv",
        help="Existing/seeded evidence ledger (read-only input).",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=PROJECT_ROOT / "config" / "industry_sources.csv",
    )
    parser.add_argument(
        "--candidates-output", type=Path, default=PROJECT_ROOT / "data" / "candidates.csv"
    )
    parser.add_argument(
        "--evidence-output", type=Path, default=PROJECT_ROOT / "data" / "evidence.csv"
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "industry_target_report.csv",
    )
    parser.add_argument("--candidate-sheet")
    parser.add_argument("--allow-live-fetch", action="store_true")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--lock-timeout", type=float, default=10.0)
    return parser


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(
            f"Missing active {label} file: {path}. Run create_workspace.py, then configure it."
        )


def _require_rows(rows: list[object], path: Path, label: str) -> None:
    if not rows:
        raise SystemExit(
            f"Active {label} file has no configured rows: {path}. "
            "Do not run verification against packaged example fixtures by accident."
        )


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.delay < 0:
        raise SystemExit("--delay must be zero or greater.")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than zero.")
    if args.lock_timeout < 0:
        raise SystemExit("--lock-timeout must be zero or greater.")

    for path, label in (
        (args.campaigns, "campaigns"),
        (args.targets, "industry targets"),
        (args.claims, "email claims"),
        (args.evidence, "email evidence"),
        (args.sources, "industry sources"),
    ):
        _require_file(path, label)
    try:
        campaigns = load_campaigns(args.campaigns)
        targets = load_targets(args.targets)
        claims = load_email_claims(args.claims)
        evidence = load_evidence(args.evidence)
        source_rows = read_csv(args.sources, INDUSTRY_SOURCE_COLUMNS)
        sources = [IndustrySource.from_row(row) for row in source_rows]
    except ValueError as exc:
        raise SystemExit(f"Invalid active verification input: {exc}") from exc

    _require_rows(campaigns, args.campaigns, "campaigns")
    _require_rows(targets, args.targets, "industry targets")
    _require_rows(sources, args.sources, "industry sources")

    relation_errors = [
        *validate_target_relations(campaigns, targets, claims),
        *validate_evidence_relations(evidence, targets, claims),
    ]
    if relation_errors:
        raise SystemExit("Input relation errors:\n- " + "\n- ".join(relation_errors))

    client = OfficialWebClient(
        allow_live_fetch=args.allow_live_fetch,
        delay_seconds=args.delay,
        timeout_seconds=args.timeout,
    )
    discovered, merged_evidence, reports, warnings = collect_targeted_industry(
        campaigns,
        targets,
        claims,
        evidence,
        sources,
        client,
    )

    # Hold the canonical candidate lock across the complete read/merge/write
    # transaction.  A sidecar lock remains stable across atomic CSV replacement.
    with LedgerLock(args.candidates_output, timeout=args.lock_timeout):
        existing = (
            read_table(args.candidates_output, CANDIDATE_COLUMNS, args.candidate_sheet)
            if args.candidates_output.exists()
            else []
        )
        merged_candidates = merge_candidates(existing, discovered)
        write_csv(args.candidates_output, CANDIDATE_COLUMNS, merged_candidates)

    # Acquire the evidence lock only after releasing the candidate lock.  This
    # avoids nested-lock ordering hazards while preserving prior source snapshots.
    with LedgerLock(args.evidence_output, timeout=args.lock_timeout):
        existing_output_evidence = load_evidence(args.evidence_output)
        merged_evidence = merge_evidence(existing_output_evidence, merged_evidence)
        write_csv(
            args.evidence_output,
            EVIDENCE_COLUMNS,
            [record.to_row() for record in merged_evidence],
        )
    write_csv(
        args.report_output,
        TARGET_REPORT_COLUMNS,
        [report.to_row() for report in reports],
    )

    status_counts = Counter(report.target_status for report in reports)
    print(f"Targets: {len(targets)}")
    print(f"Terminal reports: {len(reports)}")
    print(f"New candidate rows: {len(discovered)}")
    print(f"Candidate rows after merge: {len(merged_candidates)}")
    print(f"Evidence rows: {len(merged_evidence)}")
    print(
        "Target statuses: "
        + ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items()))
    )
    print(f"Candidates: {args.candidates_output}")
    print(f"Evidence: {args.evidence_output}")
    print(f"Target report: {args.report_output}")
    for warning in warnings:
        print(f"WARNING: {warning}")


if __name__ == "__main__":
    main()
