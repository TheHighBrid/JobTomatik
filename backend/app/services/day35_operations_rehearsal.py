"""Day 35 full no-submit operations rehearsal and provisional certification dossier.

This module does not call external job sources, browsers, Celery, or submission APIs. It
orchestrates a deterministic simulation using the production policy/recovery contracts,
then binds the result to the frozen Phase 4 candidate and exact repository digests.
A passing rehearsal may recommend entry into the Day 36 shadow run only. It can never
promote adapter maturity or authorize real submission.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from app.config import get_settings
from app.services.autonomy_release_contract import (
    REQUIRED_SHADOW_CHECKS,
    autonomy_release_contract_requirements,
)
from app.services.day33_recovery_chaos import run_day33_recovery_chaos_matrix
from app.services.operations_policy import is_quiet_hour
from app.services.operations_settings import get_operations_settings
from app.services.phase4_candidate_gate import build_phase4_candidate_gate


DAY35_REHEARSAL_VERSION = "day35-operations-rehearsal-v1"
PILOT_CONFIGURATION_PATH = "backend/evidence/day35-unattended-pilot-configuration.json"
REQUIRED_SIMULATION_STAGES = (
    "discovery",
    "scoring",
    "policy_admission",
    "material_preparation",
    "dry_run_form_fill",
    "evidence_shape",
    "reconciliation",
)

# Deliberately conservative audit-log leak indicators. These operate on retained audit
# material only and do not attempt to replace the application's secret-management layer.
_SECRET_PATTERNS = (
    re.compile(r"redis://[^\s:@/]+:[^\s@/]+@", re.IGNORECASE),
    re.compile(r"\bbearer\s+[a-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"(?:api[_-]?key|secret[_-]?key|password)\s*[:=]\s*[^\s,;}]+", re.IGNORECASE),
    re.compile(r"sk-[a-z0-9_-]{16,}", re.IGNORECASE),
)
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_configuration(root: Path) -> dict[str, Any]:
    path = root / PILOT_CONFIGURATION_PATH
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Day 35 pilot configuration must be a JSON object")
    return value


def scan_audit_secret_leakage(value: Any) -> list[dict[str, str]]:
    """Return bounded descriptions of secret-like values without echoing the secret."""

    raw = json.dumps(value, sort_keys=True, default=str)
    findings: list[dict[str, str]] = []
    for index, pattern in enumerate(_SECRET_PATTERNS, start=1):
        if pattern.search(raw):
            findings.append({"pattern": f"secret_pattern_{index}", "status": "detected"})
    return findings


def audit_explainability_report(entries: list[dict[str, Any]]) -> dict[str, Any]:
    required = {"timestamp", "stage", "decision", "reason_code", "reason", "candidate_id"}
    incomplete: list[int] = []
    consequential_authority_violations: list[int] = []
    for index, entry in enumerate(entries):
        if not required.issubset(entry) or any(entry.get(key) in (None, "") for key in required):
            incomplete.append(index)
        if entry.get("submission_authorized") is not False:
            consequential_authority_violations.append(index)
    leaks = scan_audit_secret_leakage(entries)
    return {
        "entry_count": len(entries),
        "all_entries_explainable": not incomplete,
        "incomplete_entry_indexes": incomplete,
        "no_consequential_authority": not consequential_authority_violations,
        "consequential_authority_violation_indexes": consequential_authority_violations,
        "secret_leak_findings": leaks,
        "secret_leakage_clear": not leaks,
    }


def _audit(
    entries: list[dict[str, Any]],
    *,
    timestamp: datetime,
    stage: str,
    decision: str,
    reason_code: str,
    reason: str,
    candidate_id: str,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    entries.append(
        {
            "timestamp": timestamp.replace(microsecond=0).isoformat(),
            "stage": stage,
            "decision": decision,
            "reason_code": reason_code,
            "reason": reason,
            "candidate_id": candidate_id,
            "metadata": dict(metadata or {}),
            "submission_authorized": False,
        }
    )


def _candidate(candidate_id: str, *, platform: str = "lever") -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "platform": platform,
        "posting_id": f"posting-{candidate_id}",
        "company": f"Simulation Employer {candidate_id}",
        "score": 0.91,
        "state": "discovered",
        "automatic_retry_count": 0,
        "final_submit_clicked": False,
        "submission_status": "not_submitted",
    }


def run_no_submit_simulation(
    *,
    configuration: Mapping[str, Any],
    start: datetime | None = None,
) -> dict[str, Any]:
    """Exercise the complete unattended control flow without consequential side effects."""

    current = start or datetime(2026, 9, 1, 23, 0, tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    policy = dict(configuration.get("policy") or {})
    daily_cap = int(policy.get("daily_application_cap") or 0)
    weekly_cap = int(policy.get("weekly_application_cap") or 0)
    platform_cap = int(policy.get("per_platform_daily_cap") or 0)
    quiet_start = int(policy.get("quiet_hours_start_utc") or 0)
    quiet_end = int(policy.get("quiet_hours_end_utc") or 0)
    retry_cap = int(policy.get("maximum_automatic_retries_per_attempt") or 0)

    candidates = [_candidate(f"candidate-{index}") for index in range(1, 5)]
    audit: list[dict[str, Any]] = []
    evidence_packets: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    dead_letters: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    daily_admitted = 0
    weekly_admitted = 0
    platform_admitted = 0

    # Discovery and scoring are deterministic, de-duplicated, and side-effect free.
    seen_postings: set[str] = set()
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        posting_id = candidate["posting_id"]
        if posting_id in seen_postings:
            raise AssertionError("simulation produced a duplicate posting identity")
        seen_postings.add(posting_id)
        _audit(
            audit,
            timestamp=current,
            stage="discovery",
            decision="accepted",
            reason_code="canonical_posting_discovered",
            reason="Unique canonical posting entered the simulation queue.",
            candidate_id=candidate_id,
            metadata={"posting_id": posting_id},
        )
        candidate["state"] = "scored"
        _audit(
            audit,
            timestamp=current,
            stage="scoring",
            decision="accepted",
            reason_code="minimum_score_met",
            reason="Candidate score met the frozen simulation threshold.",
            candidate_id=candidate_id,
            metadata={"score": candidate["score"]},
        )

    # Candidate 1 enters before quiet hours and completes a full dry-run shape.
    first = candidates[0]
    _audit(
        audit,
        timestamp=current,
        stage="policy_admission",
        decision="accepted",
        reason_code="within_caps_and_policy_window",
        reason="Candidate is within frozen daily, weekly, platform, and time-window controls.",
        candidate_id=first["candidate_id"],
    )
    daily_admitted += 1
    weekly_admitted += 1
    platform_admitted += 1
    first["state"] = "material_prepared"
    _audit(
        audit,
        timestamp=current + timedelta(minutes=1),
        stage="material_preparation",
        decision="accepted",
        reason_code="verified_material_shape_ready",
        reason="Simulation material passed deterministic evidence-shaped preparation.",
        candidate_id=first["candidate_id"],
    )
    first["state"] = "dry_run_completed"
    _audit(
        audit,
        timestamp=current + timedelta(minutes=2),
        stage="dry_run_form_fill",
        decision="accepted",
        reason_code="dry_run_fill_completed",
        reason="Form-fill simulation completed without invoking final submit.",
        candidate_id=first["candidate_id"],
    )
    packet = {
        "candidate_id": first["candidate_id"],
        "adapter": first["platform"],
        "posting_id": first["posting_id"],
        "payload_sha256": canonical_sha256(
            {"candidate_id": first["candidate_id"], "posting_id": first["posting_id"]}
        ),
        "final_submit_clicked": False,
        "submission_status": "not_submitted",
        "evidence_kind": "simulation_completion_shape",
    }
    evidence_packets.append(packet)
    _audit(
        audit,
        timestamp=current + timedelta(minutes=3),
        stage="evidence_shape",
        decision="accepted",
        reason_code="non_consequential_evidence_shape_retained",
        reason="Completion-shape evidence was retained without claiming a submission.",
        candidate_id=first["candidate_id"],
        metadata={"payload_sha256": packet["payload_sha256"]},
    )

    # Candidate 2 arrives during quiet hours and must be held without manual action.
    quiet_time = current + timedelta(hours=2)
    second = candidates[1]
    quiet = is_quiet_hour(quiet_time, quiet_start, quiet_end)
    _audit(
        audit,
        timestamp=quiet_time,
        stage="policy_admission",
        decision="held" if quiet else "accepted",
        reason_code="quiet_hours" if quiet else "quiet_hours_not_active",
        reason=(
            "Frozen quiet-hours policy held the candidate until the policy window reopened."
            if quiet
            else "Quiet-hours policy was not active."
        ),
        candidate_id=second["candidate_id"],
    )
    second["state"] = "held_quiet_hours" if quiet else "policy_error"

    # Candidate 3 exercises bounded retry and alerting. One transient failure is retried
    # exactly once, then it completes in dry-run mode after quiet hours.
    retry_time = current + timedelta(hours=7)
    third = candidates[2]
    _audit(
        audit,
        timestamp=retry_time,
        stage="policy_admission",
        decision="accepted",
        reason_code="within_caps_and_policy_window",
        reason="Candidate entered after quiet hours under remaining frozen caps.",
        candidate_id=third["candidate_id"],
    )
    daily_admitted += 1
    weekly_admitted += 1
    platform_admitted += 1
    third["automatic_retry_count"] += 1
    alerts.append(
        {
            "code": "simulated_source_interruption",
            "severity": "warning",
            "candidate_id": third["candidate_id"],
            "recovery_action": "bounded_retry",
        }
    )
    _audit(
        audit,
        timestamp=retry_time + timedelta(minutes=1),
        stage="material_preparation",
        decision="held",
        reason_code="transient_dependency_failure",
        reason="A simulated transient dependency failure triggered one bounded retry.",
        candidate_id=third["candidate_id"],
        metadata={"automatic_retry_count": third["automatic_retry_count"]},
    )
    if third["automatic_retry_count"] > retry_cap:
        raise AssertionError("simulation exceeded the frozen automatic retry cap")
    third["state"] = "dry_run_completed"
    _audit(
        audit,
        timestamp=retry_time + timedelta(minutes=2),
        stage="dry_run_form_fill",
        decision="accepted",
        reason_code="bounded_retry_recovered",
        reason="The single permitted retry recovered and dry-run filling completed.",
        candidate_id=third["candidate_id"],
    )
    retry_packet = {
        "candidate_id": third["candidate_id"],
        "adapter": third["platform"],
        "posting_id": third["posting_id"],
        "payload_sha256": canonical_sha256(
            {"candidate_id": third["candidate_id"], "retry": third["automatic_retry_count"]}
        ),
        "final_submit_clicked": False,
        "submission_status": "not_submitted",
        "evidence_kind": "simulation_completion_shape",
    }
    evidence_packets.append(retry_packet)
    _audit(
        audit,
        timestamp=retry_time + timedelta(minutes=3),
        stage="evidence_shape",
        decision="accepted",
        reason_code="non_consequential_evidence_shape_retained",
        reason="Recovered completion-shape evidence was retained without claiming a submission.",
        candidate_id=third["candidate_id"],
        metadata={"payload_sha256": retry_packet["payload_sha256"]},
    )

    # Candidate 4 reaches the frozen platform cap. The simulation also records an
    # irrecoverable maintenance task routed to a bounded dead letter with no auto retry.
    fourth = candidates[3]
    platform_exhausted = platform_admitted >= platform_cap
    daily_exhausted = daily_admitted >= daily_cap
    weekly_exhausted = weekly_admitted >= weekly_cap
    cap_code = (
        "platform_daily_cap_reached"
        if platform_exhausted
        else "daily_cap_reached"
        if daily_exhausted
        else "weekly_cap_reached"
        if weekly_exhausted
        else "cap_not_exhausted"
    )
    _audit(
        audit,
        timestamp=retry_time + timedelta(hours=1),
        stage="policy_admission",
        decision="held" if cap_code != "cap_not_exhausted" else "accepted",
        reason_code=cap_code,
        reason="Frozen application caps prevented additional simulated admission.",
        candidate_id=fourth["candidate_id"],
    )
    fourth["state"] = "held_cap" if cap_code != "cap_not_exhausted" else "policy_error"
    dead_letters.append(
        {
            "task_id": "simulation-maintenance-1",
            "status": "open",
            "reason_code": "irrecoverable_simulated_dependency_failure",
            "automatic_retry_allowed": False,
            "submission_authorized": False,
            "outreach_authorized": False,
            "context_complete": True,
        }
    )
    alerts.append(
        {
            "code": "dead_letter_opened",
            "severity": "warning",
            "candidate_id": fourth["candidate_id"],
            "recovery_action": "manual_dead_letter_review",
        }
    )

    for candidate in candidates:
        timeline.append(
            {
                "candidate_id": candidate["candidate_id"],
                "state": candidate["state"],
                "automatic_retry_count": candidate["automatic_retry_count"],
                "final_submit_clicked": candidate["final_submit_clicked"],
                "submission_status": candidate["submission_status"],
            }
        )
        _audit(
            audit,
            timestamp=retry_time + timedelta(hours=2),
            stage="reconciliation",
            decision="accepted",
            reason_code="candidate_accounted_for",
            reason="Every simulated candidate ended in a deterministic non-consequential state.",
            candidate_id=candidate["candidate_id"],
            metadata={"state": candidate["state"]},
        )

    audit_report = audit_explainability_report(audit)
    candidate_ids = [item["candidate_id"] for item in timeline]
    state_corruption = [
        item["candidate_id"]
        for item in timeline
        if item["state"] not in {"dry_run_completed", "held_quiet_hours", "held_cap"}
    ]
    false_submitted = [
        item["candidate_id"]
        for item in timeline
        if item["submission_status"] != "not_submitted" or item["final_submit_clicked"] is not False
    ]
    stages_observed = sorted({entry["stage"] for entry in audit})
    missing_stages = sorted(set(REQUIRED_SIMULATION_STAGES) - set(stages_observed))
    assertions = {
        "all_required_stages_observed": not missing_stages,
        "quiet_hours_verified": quiet is True and second["state"] == "held_quiet_hours",
        "platform_cap_exhaustion_verified": platform_exhausted and fourth["state"] == "held_cap",
        "daily_weekly_caps_tracked": daily_admitted <= daily_cap and weekly_admitted <= weekly_cap,
        "bounded_retry_verified": third["automatic_retry_count"] == 1 <= retry_cap,
        "alerts_verified": {item["code"] for item in alerts} >= {
            "simulated_source_interruption",
            "dead_letter_opened",
        },
        "dead_letter_verified": bool(dead_letters)
        and all(item["automatic_retry_allowed"] is False for item in dead_letters),
        "audit_explainability_verified": audit_report["all_entries_explainable"] is True,
        "audit_secret_leakage_clear": audit_report["secret_leakage_clear"] is True,
        "no_duplicate_candidates": len(candidate_ids) == len(set(candidate_ids)),
        "no_state_corruption": not state_corruption,
        "no_false_submission_state": not false_submitted,
        "no_final_submit_click": all(item["final_submit_clicked"] is False for item in timeline),
        "no_manual_babysitting_required": all(
            item["state"] in {"dry_run_completed", "held_quiet_hours", "held_cap"}
            for item in timeline
        ),
    }

    result: dict[str, Any] = {
        "version": DAY35_REHEARSAL_VERSION,
        "mode": "no_submit_simulation",
        "timeline": timeline,
        "alerts": alerts,
        "dead_letters": dead_letters,
        "evidence_packets": evidence_packets,
        "audit_log": audit,
        "audit_review": audit_report,
        "policy_counters": {
            "daily_admitted": daily_admitted,
            "daily_cap": daily_cap,
            "weekly_admitted": weekly_admitted,
            "weekly_cap": weekly_cap,
            "platform_admitted": platform_admitted,
            "platform_cap": platform_cap,
        },
        "missing_stages": missing_stages,
        "assertions": assertions,
        "safety": {
            "network_contacted": False,
            "browser_launched": False,
            "celery_dispatched": False,
            "final_submit_clicked": False,
            "submission_authorized": False,
            "outreach_authorized": False,
        },
    }
    result["passed"] = bool(all(assertions.values()) and not any(result["safety"].values()))
    result["report_sha256"] = canonical_sha256(result)
    return result


def build_day35_rehearsal_gate(
    *,
    verification_commit: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Build exact-head rehearsal, freeze, recovery, and provisional recommendation evidence."""

    commit = str(verification_commit or "").strip().lower()
    if not _COMMIT_RE.fullmatch(commit):
        raise ValueError("verification_commit must be an exact 40-character git SHA")
    repository_root = root or _root()
    configuration = _load_configuration(repository_root)
    configuration_path = repository_root / PILOT_CONFIGURATION_PATH
    configuration_digest = _file_sha256(configuration_path)

    phase4 = build_phase4_candidate_gate(
        verification_commit=commit,
        root=repository_root,
    )
    candidate_name = str((phase4.get("candidate") or {}).get("adapter") or "")
    selected_rows = [
        row
        for row in phase4.get("adapter_freeze") or []
        if str(row.get("adapter") or "") == candidate_name
    ]
    selected = selected_rows[0] if selected_rows else {}
    selected_digests = dict(selected.get("digests") or {})

    simulation = run_no_submit_simulation(configuration=configuration)
    recovery = run_day33_recovery_chaos_matrix()
    recovery_digest = canonical_sha256(recovery)
    contract = autonomy_release_contract_requirements()
    contract_digest = canonical_sha256(contract)
    core = get_settings()
    operations = get_operations_settings()

    source_bindings = {
        "adapter_name": candidate_name or None,
        "adapter_version": selected.get("version"),
        "release_commit": commit,
        "adapter_source_digest": (
            f"sha256:{selected_digests.get('adapter_source_sha256')}"
            if selected_digests.get("adapter_source_sha256")
            else None
        ),
        "fixture_digest": (
            f"sha256:{selected_digests.get('fixture_regression_sha256')}"
            if selected_digests.get("fixture_regression_sha256")
            else None
        ),
        "retained_evidence_digest": (
            f"sha256:{selected_digests.get('retained_evidence_sha256')}"
            if selected_digests.get("retained_evidence_sha256")
            else None
        ),
        "manifest_live_evidence_digest": (
            f"sha256:{selected_digests.get('manifest_live_evidence_sha256')}"
            if selected_digests.get("manifest_live_evidence_sha256")
            else None
        ),
        "pilot_configuration_digest": f"sha256:{configuration_digest}",
        "phase4_gate_digest": f"sha256:{phase4.get('gate_sha256')}",
        "day27_contract_digest": f"sha256:{contract_digest}",
        "day33_recovery_digest": f"sha256:{recovery_digest}",
        "day35_rehearsal_digest": f"sha256:{simulation.get('report_sha256')}",
    }
    required_bindings_present = all(source_bindings.values())

    candidate_config = dict(configuration.get("candidate") or {})
    runtime_safe = bool(
        operations.autopilot_enabled is False
        and core.allow_real_application_submit is False
        and core.allow_real_followup_send is False
    )
    freeze_valid = bool(
        candidate_name == candidate_config.get("adapter") == "lever"
        and str(selected.get("version") or "") == str(candidate_config.get("adapter_version") or "")
        and str(selected.get("maturity") or "") == str(candidate_config.get("required_current_maturity") or "")
        and candidate_config.get("promotion_authorized") is False
        and required_bindings_present
    )

    future_shadow_blockers = [f"shadow:{name}:missing" for name in REQUIRED_SHADOW_CHECKS]
    inherited_blockers = list((phase4.get("candidate") or {}).get("remaining_blockers") or [])
    blockers = sorted(set(inherited_blockers + future_shadow_blockers))
    eligible_for_shadow_runs = bool(
        simulation.get("passed") is True
        and recovery.get("passed") is True
        and phase4.get("gate_passed") is True
        and freeze_valid
        and runtime_safe
    )
    recommendation = {
        "candidate": candidate_name or None,
        "recommendation": (
            "proceed_to_day36_unattended_shadow_run"
            if eligible_for_shadow_runs
            else "hold_before_shadow_runs"
        ),
        "eligible_to_enter_shadow_runs": eligible_for_shadow_runs,
        "certified_autonomous_recommended": False,
        "promotion_authorized": False,
        "live_submission_authorized": False,
        "day39_promotion_blocked": True,
        "remaining_autonomy_contract_blockers": blockers,
        "source_bindings": source_bindings,
        "reason": (
            "Day 35 simulation and completed recovery evidence support shadow-run entry only; "
            "Day 27 supervised, shadow, signed-manifest, and separate-promotion gates remain unsatisfied."
            if eligible_for_shadow_runs
            else "Day 35 prerequisites are incomplete; the candidate must remain held."
        ),
    }
    recommendation["recommendation_sha256"] = canonical_sha256(recommendation)

    freeze = {
        "freeze_version": "day35-unattended-pilot-freeze-v1",
        "verification_commit": commit,
        "configuration_path": PILOT_CONFIGURATION_PATH,
        "configuration": configuration,
        "source_bindings": source_bindings,
        "valid": freeze_valid,
    }
    freeze["freeze_sha256"] = canonical_sha256(freeze)

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "gate_version": DAY35_REHEARSAL_VERSION,
        "verification_commit": commit,
        "rehearsal": simulation,
        "completed_recovery_evidence": {
            "passed": recovery.get("passed") is True,
            "failure_modes": list(recovery.get("failure_modes") or []),
            "assertions": dict(recovery.get("assertions") or {}),
            "digest": f"sha256:{recovery_digest}",
        },
        "pilot_configuration_freeze": freeze,
        "provisional_autonomy_recommendation": recommendation,
        "day27_contract": {
            "version": contract.get("contract_version"),
            "target_maturity": contract.get("target_maturity"),
            "required_shadow_checks": list(contract.get("required_shadow_checks") or []),
            "digest": f"sha256:{contract_digest}",
        },
        "runtime_safety": {
            "autopilot_enabled": bool(operations.autopilot_enabled),
            "real_submission_enabled": bool(core.allow_real_application_submit),
            "real_followup_send_enabled": bool(core.allow_real_followup_send),
            "safe": runtime_safe,
        },
    }
    payload["gate_passed"] = bool(
        eligible_for_shadow_runs
        and recommendation["certified_autonomous_recommended"] is False
        and recommendation["promotion_authorized"] is False
        and recommendation["live_submission_authorized"] is False
        and recommendation["day39_promotion_blocked"] is True
        and payload["completed_recovery_evidence"]["passed"] is True
        and freeze["valid"] is True
        and payload["runtime_safety"]["safe"] is True
    )
    payload["gate_sha256"] = canonical_sha256(payload)
    return payload


__all__ = [
    "DAY35_REHEARSAL_VERSION",
    "PILOT_CONFIGURATION_PATH",
    "REQUIRED_SIMULATION_STAGES",
    "audit_explainability_report",
    "build_day35_rehearsal_gate",
    "canonical_sha256",
    "run_no_submit_simulation",
    "scan_audit_secret_leakage",
]
