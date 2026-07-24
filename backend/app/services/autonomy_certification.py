"""Autonomous-submission certification roadmap and gap analysis.

This module does not enable real submission. It turns the existing adapter
manifest and operations settings into an auditable checklist for progressing
from today's dry-run / human-reviewed stages toward certified autonomous real
submission.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

from app.services.ats_manifest import ats_certification_manifest
from app.services.ats_maturity import AUTONOMY_RELEASE_GATES, HUMAN_REVIEWED_RELEASE_GATES
from app.services.operations_policy import operations_readiness_manifest

AUTONOMY_TARGET_MATURITY = "certified_autonomous"
AUTONOMY_CERTIFICATION_FRAMEWORK_VERSION = "autonomy_certification_v1"

# Ordered stages make the destination explicit without pretending the runtime is
# already submission-capable. Each stage can be used as a release checklist.
CERTIFICATION_STAGES = (
    {
        "id": "live_dry_run_evidence",
        "title": "Live dry-run evidence",
        "description": (
            "Adapter reaches a filled pre-submit/manual-challenge boundary on live "
            "public surfaces without clicking final submit."
        ),
        "required_for": "dry_run",
        "checks": (
            "live certification evidence is present",
            "resume upload is verified where supported",
            "final_submit_clicked is false",
        ),
    },
    {
        "id": "human_reviewed_real_submission",
        "title": "Human-reviewed real submission pilot",
        "description": (
            "A supervised pilot proves exact-payload approvals, duplicate prevention, "
            "and confirmation evidence for real submissions."
        ),
        "required_for": "human_reviewed_submit",
        "checks": HUMAN_REVIEWED_RELEASE_GATES,
    },
    {
        "id": "autonomous_real_submission",
        "title": "Evidence-backed autonomous real submission",
        "description": (
            "Autonomous submission is permitted only after every autonomy release gate "
            "has an explicit approval record and operations controls are configured."
        ),
        "required_for": AUTONOMY_TARGET_MATURITY,
        "checks": AUTONOMY_RELEASE_GATES,
    },
)


def _gate_status(adapter: Mapping[str, Any], release_key: str, gates: Iterable[str]) -> Dict[str, Any]:
    release = adapter.get(release_key)
    if not isinstance(release, Mapping):
        release = {}

    checks: Dict[str, bool] = {
        "approved": release.get("approved") is True,
        "approval_reference": bool(str(release.get("approval_reference") or "").strip()),
    }
    for gate in gates:
        checks[gate] = release.get(gate) is True

    missing = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not missing,
        "checks": checks,
        "missing": missing,
        "approval_reference": release.get("approval_reference") or None,
    }


def _live_dry_run_status(adapter: Mapping[str, Any]) -> Dict[str, Any]:
    live = adapter.get("live_certification")
    if not isinstance(live, Mapping):
        live = {}
    maturity = adapter.get("maturity")
    passed = maturity in {
        "dry_run",
        "human_reviewed_submit",
        AUTONOMY_TARGET_MATURITY,
    }
    checks = {
        "live_certification_present": bool(live),
        "final_submit_not_clicked": live.get("final_submit_clicked") is False,
        "boundary_or_synthetic_exercise_present": bool(
            live.get("latest_certified_boundary")
            or live.get("synthetic_full_form_exercise")
            or live.get("synthetic_live_full_form_exercise")
        ),
        "resume_upload_evidence_present": bool(
            live.get("verified_resume_upload")
            or live.get("live_verified_resume_upload")
            or live.get("fixture_verified_resume_upload")
        ),
    }
    missing = [name for name, value in checks.items() if not value]
    return {
        "passed": passed,
        "checks": checks,
        "missing": [] if passed else missing,
        "latest_certified_boundary": live.get("latest_certified_boundary"),
    }


def _adapter_certification_plan(adapter: Mapping[str, Any]) -> Dict[str, Any]:
    human = _gate_status(adapter, "human_reviewed_release", HUMAN_REVIEWED_RELEASE_GATES)
    autonomy = _gate_status(adapter, "autonomy_release", AUTONOMY_RELEASE_GATES)
    dry_run = _live_dry_run_status(adapter)

    blockers = []
    if not dry_run["passed"]:
        blockers.append("live_dry_run_evidence")
    if not human["passed"]:
        blockers.append("human_reviewed_real_submission")
    if not autonomy["passed"]:
        blockers.append("autonomous_real_submission")

    return {
        "name": adapter.get("name"),
        "version": adapter.get("version"),
        "current_maturity": adapter.get("maturity"),
        "target_maturity": AUTONOMY_TARGET_MATURITY,
        "autonomous_submission_allowed": adapter.get("autonomous_submission_allowed") is True,
        "stages": {
            "live_dry_run_evidence": dry_run,
            "human_reviewed_real_submission": human,
            "autonomous_real_submission": autonomy,
        },
        "next_blockers": blockers,
        "ready_for_autonomous_release": not blockers,
    }


def build_autonomy_certification_manifest() -> Dict[str, Any]:
    """Return an auditable roadmap from current adapter evidence to autonomy.

    The output is intentionally derived from runtime manifests and current
    operations settings. It can be surfaced in UI/CI without flipping any feature
    flag or treating documentation language as certification evidence.
    """

    ats = ats_certification_manifest()
    operations = operations_readiness_manifest()
    adapters = [
        _adapter_certification_plan(item)
        for item in ats.get("adapters", [])
        if isinstance(item, Mapping)
    ]
    ready = sorted(
        item["name"]
        for item in adapters
        if item.get("ready_for_autonomous_release") is True
    )
    return {
        "framework_version": AUTONOMY_CERTIFICATION_FRAMEWORK_VERSION,
        "target_maturity": AUTONOMY_TARGET_MATURITY,
        "current_runtime": {
            "autopilot_enabled": operations.get("autopilot_enabled"),
            "real_submission_enabled": operations.get("real_submission_enabled"),
            "autonomous_adapters": ats.get("autonomous_adapters", []),
        },
        "stages": list(CERTIFICATION_STAGES),
        "adapters": adapters,
        "ready_adapters": ready,
        "remaining_adapter_count": len(adapters) - len(ready),
        "invariants": {
            "does_not_enable_real_submission": True,
            "documentation_is_not_certification_evidence": True,
            "feature_flags_may_remain_off_until_release_approval": True,
            "autonomous_release_requires_all_adapter_gates": True,
        },
    }
