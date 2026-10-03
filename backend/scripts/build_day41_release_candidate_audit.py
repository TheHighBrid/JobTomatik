#!/usr/bin/env python3
"""Build the read-only Day 41 release-candidate audit report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.day41_release_audit import build_day41_release_candidate_audit


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day40-certification", required=True)
    parser.add_argument("--release-matrix", required=True)
    parser.add_argument("--runtime-state", required=True)
    parser.add_argument("--audit-results", required=True)
    parser.add_argument("--recovery-drills", required=True)
    parser.add_argument("--candidate-artifact", required=True)
    parser.add_argument("--release-documents", required=True)
    parser.add_argument("--checklist", required=True)
    parser.add_argument(
        "--output",
        default="evidence/day41-release-candidate-audit.json",
    )
    args = parser.parse_args()

    report = build_day41_release_candidate_audit(
        day40_certification=_load(args.day40_certification),
        release_matrix=_load(args.release_matrix),
        runtime_state=_load(args.runtime_state),
        audit_results=_load(args.audit_results),
        recovery_drills=_load(args.recovery_drills),
        candidate_artifact=_load(args.candidate_artifact),
        release_documents=_load(args.release_documents),
        checklist=_load(args.checklist),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": report.get("passed"),
                "day42_entry_eligible": report.get("day42_entry_eligible"),
                "candidate_revision": report.get("candidate_revision"),
                "report_sha256": report.get("report_sha256"),
                "publication_authorized": report.get("publication_authorized"),
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0 if report.get("passed") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
