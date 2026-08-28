#!/usr/bin/env python3
"""Build the read-only Day 42 exact-commit publish-readiness report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.day42_publish_readiness import build_day42_publish_readiness


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day41-audit", required=True)
    parser.add_argument("--final-release-matrix", required=True)
    parser.add_argument("--candidate-artifact", required=True)
    parser.add_argument("--maturity-manifest", required=True)
    parser.add_argument("--repository-release-state", required=True)
    parser.add_argument("--release-documents", required=True)
    parser.add_argument("--owner-authorization", required=True)
    parser.add_argument(
        "--output",
        default="evidence/day42-publish-readiness.json",
    )
    args = parser.parse_args()

    report = build_day42_publish_readiness(
        day41_audit=_load(args.day41_audit),
        final_release_matrix=_load(args.final_release_matrix),
        candidate_artifact=_load(args.candidate_artifact),
        maturity_manifest=_load(args.maturity_manifest),
        repository_release_state=_load(args.repository_release_state),
        release_documents=_load(args.release_documents),
        owner_authorization=_load(args.owner_authorization),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "publication_eligible": report.get("publication_eligible"),
                "publication_executed": report.get("publication_executed"),
                "candidate_revision": report.get("candidate_revision"),
                "candidate_run_id": report.get("candidate_run_id"),
                "candidate_workflow_path": report.get("candidate_workflow_path"),
                "apk_sha256": report.get("apk_sha256"),
                "report_sha256": report.get("report_sha256"),
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0 if report.get("publication_eligible") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
