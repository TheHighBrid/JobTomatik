"""Canonical ATS maturity model derived from runtime manifest evidence.

The descriptive ``certification_level`` strings used by individual adapters are
retained for diagnostics, but they never authorize unattended submission. Only
this roadmap-aligned maturity field is consumed by the unattended policy gate.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Tuple


class AdapterMaturity(str, Enum):
    """Operational maturity levels defined by roadmap issue #13."""

    UNSUPPORTED = "unsupported"
    DETECT_ONLY = "detect_only"
    DRY_RUN = "dry_run"
    HUMAN_REVIEWED_SUBMIT = "human_reviewed_submit"
    CERTIFIED_AUTONOMOUS = "certified_autonomous"


HUMAN_REVIEWED_RELEASE_GATES: Tuple[str, ...] = (
    "supervised_real_submission_pilot_complete",
    "zero_false_positive_submitted_records",
    "duplicate_prevention_verified",
    "confirmation_evidence_verified",
)

AUTONOMY_RELEASE_GATES: Tuple[str, ...] = (
    *HUMAN_REVIEWED_RELEASE_GATES,
    "duplicate_replay_and_crash_recovery_passed",
    "manual_handoff_notifications_operational",
    "caps_quiet_hours_exclusions_and_kill_switches_configured",
    "rollback_and_incident_response_drill_passed",
)


def normalize_adapter_maturity(value: Any) -> AdapterMaturity | None:
    """Return a known maturity or ``None`` for missing/unknown values."""

    try:
        return AdapterMaturity(str(value))
    except (TypeError, ValueError):
        return None


def _is_certified(value: Any) -> bool:
    if value is True:
        return True
    if not isinstance(value, str):
        return False
    return value.strip().lower() in {
        "certified",
        "complete",
        "completed",
        "passed",
        "verified",
    }


def _release_status(
    manifest: Mapping[str, Any],
    section_name: str,
    required_gates: Iterable[str],
) -> tuple[bool, list[str]]:
    section = manifest.get(section_name)
    if not isinstance(section, Mapping):
        section = {}

    missing: list[str] = []
    if section.get("approved") is not True:
        missing.append("approved")
    if not str(section.get("approval_reference") or "").strip():
        missing.append("approval_reference")

    for gate in required_gates:
        if section.get(gate) is not True:
            missing.append(gate)

    return not missing, missing


def _has_current_live_dry_run_evidence(manifest: Mapping[str, Any]) -> bool:
    live = manifest.get("live_certification")
    if not isinstance(live, Mapping):
        return False

    # A fixture-only full-form test is useful, but it does not promote a live
    # adapter to dry-run maturity. Require a current live synthetic exercise or
    # a current live boundary that reached the filled pre-submit stage.
    if _is_certified(live.get("synthetic_full_form_exercise")):
        return live.get("final_submit_clicked") is False

    boundary = str(live.get("latest_certified_boundary") or "").strip().lower()
    reached_filled_boundary = boundary in {
        "dry_run_pre_submit_or_manual_challenge",
        "captcha_detected_post_fill_pre_action",
        "ready_to_submit",
        "manual_challenge_handoff",
    }
    verified_upload = bool(
        live.get("verified_resume_upload")
        or live.get("live_verified_resume_upload")
    )
    return reached_filled_boundary and verified_upload and live.get(
        "final_submit_clicked"
    ) is False


def _has_detection_evidence(manifest: Mapping[str, Any]) -> bool:
    if manifest.get("supported_hosts"):
        return True

    live = manifest.get("live_certification")
    if not isinstance(live, Mapping):
        return False

    detection_keys = (
        "public_form_smoke",
        "public_posting_metadata",
        "public_cxs_metadata",
        "pre_form_anti_bot_handoff",
        "bounded_job_page_apply",
        "same_origin_public_apply_route",
    )
    return any(_is_certified(live.get(key)) for key in detection_keys)


def derive_adapter_maturity(manifest: Mapping[str, Any]) -> AdapterMaturity:
    """Derive operational maturity without trusting certification prose.

    Promotion to a submission-capable maturity requires explicit, reviewable
    release-gate records. Descriptive labels, green workflows, fixtures, and
    zero-submit live exercises cannot independently authorize real submission.
    """

    name = str(manifest.get("name") or "").strip().lower()
    if not name or name == "generic":
        return AdapterMaturity.UNSUPPORTED

    autonomy_ready, _ = _release_status(
        manifest,
        "autonomy_release",
        AUTONOMY_RELEASE_GATES,
    )
    if autonomy_ready:
        return AdapterMaturity.CERTIFIED_AUTONOMOUS

    reviewed_ready, _ = _release_status(
        manifest,
        "human_reviewed_release",
        HUMAN_REVIEWED_RELEASE_GATES,
    )
    if reviewed_ready:
        return AdapterMaturity.HUMAN_REVIEWED_SUBMIT

    if _has_current_live_dry_run_evidence(manifest):
        return AdapterMaturity.DRY_RUN

    if _has_detection_evidence(manifest):
        return AdapterMaturity.DETECT_ONLY

    return AdapterMaturity.UNSUPPORTED


def annotate_adapter_manifest(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Add the canonical maturity and fail-closed release-gate diagnostics."""

    value = dict(manifest)
    maturity = derive_adapter_maturity(value)
    human_ready, missing_human = _release_status(
        value,
        "human_reviewed_release",
        HUMAN_REVIEWED_RELEASE_GATES,
    )
    autonomy_ready, missing_autonomy = _release_status(
        value,
        "autonomy_release",
        AUTONOMY_RELEASE_GATES,
    )

    value["maturity"] = maturity.value
    value["maturity_model"] = "roadmap_issue_13_v1"
    value["certification_level_semantics"] = "descriptive_evidence_label_only"
    value["human_reviewed_submission_allowed"] = human_ready
    value["autonomous_submission_allowed"] = autonomy_ready
    value["release_gate_status"] = {
        "human_reviewed_submit": {
            "passed": human_ready,
            "missing": missing_human,
        },
        "certified_autonomous": {
            "passed": autonomy_ready,
            "missing": missing_autonomy,
        },
    }
    return value
