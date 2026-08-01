#!/usr/bin/env python3
"""Finalize one externally retained interactive Lever Phase A report."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.services.lever_phase_a_provenance import finalize_interactive_candidate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--github-token-env",
        default="GITHUB_TOKEN",
        help="Environment variable containing a token allowed to read Actions artifacts.",
    )
    parser.add_argument(
        "--corpus-root",
        default="evidence/lever-phase-a-target-corpus",
    )
    parser.add_argument(
        "--evidence-root",
        default="evidence",
    )
    parser.add_argument("--candidate-output")
    parser.add_argument("--source-output")
    args = parser.parse_args()

    review_id = str(args.review_id).strip()
    evidence_root = Path(args.evidence_root)
    candidate_path = Path(args.candidate_output) if args.candidate_output else (
        evidence_root / f"lever-phase-a-candidate-{review_id}.csv"
    )
    source_receipt_path = Path(args.source_output) if args.source_output else (
        evidence_root / f"lever-phase-a-source-{review_id}.csv"
    )
    github_token = os.getenv(args.github_token_env, "")
    if not github_token:
        raise SystemExit(
            f"Missing GitHub token in environment variable {args.github_token_env!r}."
        )

    result = finalize_interactive_candidate(
        report_path=Path(args.report),
        review_id=review_id,
        corpus_root=Path(args.corpus_root),
        evidence_root=evidence_root,
        candidate_path=candidate_path,
        source_receipt_path=source_receipt_path,
        operator=args.operator,
        workflow_run_id=args.workflow_run_id,
        artifact_id=args.artifact_id,
        artifact_digest=args.artifact_digest,
        github_token=github_token,
        run_id=args.run_id,
    )

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    print(f"Candidate:       {candidate_path}")
    print(f"Source receipt:  {source_receipt_path}")
    print(f"Durable archive: {result['durable_archive']['path']}")
    print("No file was appended to the canonical manifests.")


if __name__ == "__main__":
    main()
