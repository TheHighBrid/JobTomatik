#!/usr/bin/env python3
"""Certify Lever pilot evidence without enabling or executing live submission."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.services.lever_pilot_ingestion import render_readiness_markdown
from app.services.lever_pilot_ledger_boundary import read_lever_pilot_readiness


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_certification_report(
    readiness: Mapping[str, Any],
    *,
    require_phase_a: bool = False,
    require_phase_b: bool = False,
) -> Dict[str, Any]:
    summary = dict(readiness.get("summary") or {})
    gates = dict(summary.get("gates") or {})

    checks = {
        "platform_is_lever": summary.get("platform") == "lever",
        "canonical_maturity_is_dry_run": summary.get("canonical_maturity") == "dry_run",
        "promotion_is_not_authorized": gates.get("explicit_separate_promotion_approval") is False,
        "promotion_ready_is_false": summary.get("promotion_ready") is False,
        "zero_false_submitted_records": int(summary.get("false_submitted_count") or 0) == 0,
        "zero_duplicate_submissions": int(summary.get("duplicate_submission_count") or 0) == 0,
        "uncertain_outcomes_remain_uncertain": int(
            summary.get("uncertain_status_violation_count") or 0
        )
        == 0,
        "all_evidence_hashes_match_consumed_approvals": int(
            summary.get("payload_hash_mismatch_count") or 0
        )
        == 0,
    }
    if require_phase_a:
        checks.update(
            {
                "phase_a_has_thirty_qualifying_dry_runs": bool(
                    gates.get("thirty_qualifying_dry_runs")
                ),
                "phase_a_has_thirty_distinct_sites": bool(
                    gates.get("thirty_distinct_lever_sites")
                ),
                "phase_a_covers_global_and_eu": bool(
                    gates.get("global_and_eu_hosts_covered")
                ),
            }
        )
    if require_phase_b:
        checks.update(
            {
                "phase_b_has_ten_confirmed_submissions": bool(
                    gates.get("ten_supervised_confirmed_submissions")
                ),
                "phase_b_successes_are_independently_reviewed": bool(
                    gates.get("all_success_evidence_independently_reviewed")
                ),
            }
        )

    return {
        "schema_version": "1.0",
        "certification": "lever_supervised_pilot_readiness",
        "mode": "read_only_evidence_certification",
        "require_phase_a": require_phase_a,
        "require_phase_b": require_phase_b,
        "passed": all(checks.values()),
        "checks": checks,
        "readiness": dict(readiness),
        "safety": {
            "browser_opened": False,
            "network_contacted": False,
            "approval_issued": False,
            "submission_queued": False,
            "final_submit_clicked": False,
            "maturity_promoted": False,
        },
    }


def certify_paths(
    *,
    baseline_path: Optional[str | Path] = None,
    ledger_path: Optional[str | Path] = None,
    require_phase_a: bool = False,
    require_phase_b: bool = False,
) -> Dict[str, Any]:
    readiness = read_lever_pilot_readiness(
        baseline_path=baseline_path,
        ledger_path=ledger_path,
    )
    return build_certification_report(
        readiness,
        require_phase_a=require_phase_a,
        require_phase_b=require_phase_b,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline")
    parser.add_argument("--ledger")
    parser.add_argument("--json-output", default="lever-pilot-certification.json")
    parser.add_argument("--markdown-output", default="lever-pilot-certification.md")
    parser.add_argument("--require-phase-a", action="store_true")
    parser.add_argument("--require-phase-b", action="store_true")
    args = parser.parse_args()

    report = certify_paths(
        baseline_path=args.baseline,
        ledger_path=args.ledger,
        require_phase_a=args.require_phase_a,
        require_phase_b=args.require_phase_b,
    )
    json_output = Path(args.json_output)
    markdown_output = Path(args.markdown_output)
    _atomic_write(json_output, json.dumps(report, indent=2, sort_keys=True) + "\n")
    readiness_markdown = render_readiness_markdown(report["readiness"])
    checks_markdown = "\n".join(
        f"- [{'x' if passed else ' '}] `{name}`"
        for name, passed in report["checks"].items()
    )
    _atomic_write(
        markdown_output,
        readiness_markdown
        + "\n## Certification checks\n\n"
        + checks_markdown
        + f"\n\n**Certification passed:** `{report['passed']}`\n",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
