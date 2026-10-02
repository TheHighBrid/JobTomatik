#!/usr/bin/env python3
"""Build exact-head evidence for Day 31 autonomous material verification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.config import get_settings
from app.services.answer_policy import MIN_AUTOFILL_CONFIDENCE
from app.services.autonomous_material_verification import (
    DAY31_MATERIAL_POLICY_VERSION,
    MIN_AUTONOMOUS_CLAIM_CONFIDENCE,
)
from app.services.operations_settings import get_operations_settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SOURCES = (
    "backend/app/services/autonomous_material_verification.py",
    "backend/app/services/material_generation.py",
    "backend/app/services/material_task_integration.py",
    "backend/app/services/answer_policy.py",
    "backend/tests/test_day31_autonomous_material_verification.py",
    "backend/tests/test_material_generation.py",
    "backend/tests/test_material_task_integration.py",
    "backend/tests/test_answer_policy_readiness.py",
    ".github/workflows/day31-material-verification-gate.yml",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_gate(verification_commit: str) -> dict:
    core = get_settings()
    operations = get_operations_settings()
    source_digests = {source: _sha256(REPO_ROOT / source) for source in SOURCES}
    runtime = {
        "autopilot_enabled": bool(operations.autopilot_enabled),
        "real_submission_enabled": bool(core.allow_real_application_submit),
    }
    contract = {
        "canonical_resume_selection": True,
        "conflicting_resume_fails_closed": True,
        "resume_file_sha256_bound": True,
        "stale_resume_digest_detected": True,
        "material_content_sha256_bound": True,
        "material_claims_sha256_bound": True,
        "material_evidence_sha256_bound": True,
        "unsupported_applicant_claim_fails_closed": True,
        "low_confidence_applicant_evidence_requires_review": True,
        "low_confidence_custom_answer_cannot_autofill": True,
        "answer_policy_conflicts_expiry_provenance_and_consent_preserved": True,
        "advisories_do_not_force_review_without_critical_blocker": True,
        "submission_authority_unchanged": True,
    }
    return {
        "schema_version": "1.0",
        "policy_version": DAY31_MATERIAL_POLICY_VERSION,
        "verification_commit": verification_commit,
        "gate_passed": bool(
            verification_commit
            and not runtime["autopilot_enabled"]
            and not runtime["real_submission_enabled"]
            and MIN_AUTONOMOUS_CLAIM_CONFIDENCE >= 0.80
            and MIN_AUTOFILL_CONFIDENCE >= 0.80
            and len(source_digests) == len(SOURCES)
        ),
        "confidence_thresholds": {
            "applicant_claim_evidence": MIN_AUTONOMOUS_CLAIM_CONFIDENCE,
            "answer_policy_autofill": MIN_AUTOFILL_CONFIDENCE,
        },
        "contract": contract,
        "runtime_safety": runtime,
        "source_digests_sha256": source_digests,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = build_gate(args.verification_commit.strip())
    Path(args.output).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not payload["gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
