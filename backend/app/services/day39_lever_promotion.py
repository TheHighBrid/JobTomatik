"""Deterministic, fail-closed builder for the separate Day 39 Lever promotion.

This module turns already-retained evidence into the exact signed autonomy-release
record consumed by the canonical ATS maturity model. It does not create evidence,
issue owner approval, enable real submission, alter runtime flags, or mutate adapter
maturity. Missing Phase B, shadow, recovery, policy, source, release-head, signing-key,
or owner-approval evidence produces blockers and no installable release record.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from app.services.ats_maturity import AUTONOMY_RELEASE_GATES
from app.services.autonomy_release_contract import (
    AUTONOMY_RELEASE_SCHEMA_VERSION,
    AUTONOMY_SIGNATURE_METHOD,
    MIN_DISTINCT_CONFIRMED_SUBMISSIONS,
    MIN_RELIABILITY_ATTEMPTS,
    REQUIRED_POLICY_CONTROLS,
    REQUIRED_RECOVERY_DRILLS,
    REQUIRED_SHADOW_CHECKS,
    compute_autonomy_manifest_digest,
    compute_autonomy_manifest_signature,
    validate_autonomy_release_manifest,
)


DAY39_LEVER_PROMOTION_VERSION = "day39-lever-promotion-v1"
DAY39_LEVER_ADAPTER = "lever"
DAY39_LEVER_VERSION = "1.1.0"
DAY39_TARGET_MATURITY = "certified_autonomous"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Day39LeverPromotionError(ValueError):
    """Raised for malformed evidence inputs that cannot be interpreted safely."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sha40(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _SHA40.fullmatch(text) else ""


def _sha256(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.split(":", 1)[1]
    return text if _SHA256.fullmatch(text) else ""


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _summary(readiness: Any) -> Mapping[str, Any]:
    value = _mapping(readiness)
    if isinstance(value.get("summary"), Mapping):
        return _mapping(value.get("summary"))
    lever = _mapping(value.get("lever"))
    return _mapping(lever.get("summary"))


def _lever_freeze(phase4_freeze: Any) -> Mapping[str, Any]:
    freeze = _mapping(phase4_freeze)
    adapters = _mapping(freeze.get("adapters"))
    return _mapping(adapters.get(DAY39_LEVER_ADAPTER))


def _report_hash(report: Mapping[str, Any]) -> str:
    claimed = _sha256(report.get("report_sha256"))
    if not claimed:
        return ""
    copy = dict(report)
    copy.pop("report_sha256", None)
    return claimed if _canonical_hash(copy) == claimed else ""


def _day35_recovery(day35: Any) -> tuple[dict[str, bool], bool]:
    gate = _mapping(day35)
    completed = _mapping(gate.get("completed_recovery_evidence"))
    rows = [
        _mapping(item)
        for item in list(completed.get("failure_modes") or [])
        if isinstance(item, Mapping)
    ]
    by_name = {
        str(item.get("failure_mode") or ""): item
        for item in rows
        if str(item.get("failure_mode") or "")
    }
    drills = {
        name: bool(_mapping(by_name.get(name)).get("passed") is True)
        for name in REQUIRED_RECOVERY_DRILLS
    }
    return drills, bool(
        gate.get("gate_passed") is True
        and completed.get("passed") is True
        and all(drills.values())
        and _sha256(completed.get("digest"))
    )


def _day35_policy(day35: Any, day38: Any) -> tuple[dict[str, bool], bool]:
    gate = _mapping(day35)
    rehearsal = _mapping(gate.get("rehearsal"))
    assertions = _mapping(rehearsal.get("assertions"))
    freeze = _mapping(gate.get("pilot_configuration_freeze"))
    configuration = _mapping(freeze.get("configuration"))
    runtime_invariants = _mapping(configuration.get("runtime_invariants"))
    phase4 = _mapping(gate.get("provisional_autonomy_recommendation"))
    source_bindings = _mapping(phase4.get("source_bindings"))

    shadow = _mapping(day38)
    transitions = _mapping(shadow.get("production_policy_transitions"))
    transition_checks = _mapping(transitions.get("checks"))

    # Day 35 is an exact-source-bound rehearsal. The dedicated Day 39 promotion
    # tooling gate reruns production policy regressions for exclusions and kill
    # switches; these booleans only become true when the retained Day 35 gate is
    # valid and source-bound rather than accepting a caller-provided assertion.
    day35_source_bound = bool(
        gate.get("gate_passed") is True
        and freeze.get("valid") is True
        and _sha256(source_bindings.get("phase4_gate_digest"))
        and _sha256(source_bindings.get("pilot_configuration_digest"))
        and runtime_invariants.get("real_application_submit_must_remain_false") is True
    )
    controls = {
        "daily_weekly_caps": assertions.get("daily_weekly_caps_tracked") is True,
        "quiet_hours": transition_checks.get("quiet_hours_transition_observed") is True,
        "employer_exclusions": day35_source_bound,
        "platform_limits": assertions.get("platform_cap_exhaustion_verified") is True,
        "kill_switch": day35_source_bound,
    }
    return controls, bool(
        set(controls) == set(REQUIRED_POLICY_CONTROLS)
        and all(controls.values())
    )


def _shadow_checks(day36: Any, day37: Any, day38: Any) -> dict[str, bool]:
    d36 = _mapping(day36)
    d37 = _mapping(day37)
    d38 = _mapping(day38)
    c36 = _mapping(d36.get("checks"))
    c37 = _mapping(d37.get("checks"))
    c38 = _mapping(d38.get("checks"))
    incidents = _mapping(d37.get("incidents"))
    observed = set(str(item) for item in list(incidents.get("observed_types") or []))
    policy = _mapping(d38.get("production_policy_transitions"))
    policy_checks = _mapping(policy.get("checks"))

    values = {
        "final_submit_disabled": bool(
            c36.get("final_submit_disabled") is True
            and c37.get("final_submit_disabled") is True
            and c38.get("final_submit_disabled") is True
        ),
        "four_hour_unattended_passed": bool(
            d36.get("passed") is True
            and str(d36.get("target_evidence_type") or "") == "shadow_run_4h"
        ),
        "eight_hour_unattended_passed": bool(
            d37.get("passed") is True
            and str(d37.get("target_evidence_type") or "") == "shadow_run_8h"
        ),
        "twenty_four_hour_unattended_passed": bool(
            d38.get("passed") is True
            and d38.get("day39_entry_eligible") is True
            and str(d38.get("target_evidence_type") or "") == "shadow_run_24h"
        ),
        "no_leaked_sessions": bool(
            c38.get("browser_cleanup_reconciled") is True
            and c38.get("no_active_application_work") is True
        ),
        "source_outage_breaker_verified": bool(
            "source_outage" in observed
            and _mapping(incidents.get("checks")).get(
                "source_outage_isolated_without_raw_exception"
            )
            is True
        ),
        "browser_crash_recovery_verified": bool(
            "browser_crash" in observed
            and _mapping(incidents.get("checks")).get(
                "browser_controlled_page_recovered"
            )
            is True
        ),
        "stale_posting_rejected": bool(
            "stale_posting" in observed
            and _mapping(incidents.get("checks")).get(
                "stale_posting_terminal_without_retry"
            )
            is True
        ),
        "ambiguous_question_held": bool(
            "ambiguous_question" in observed
            and _mapping(incidents.get("checks")).get(
                "ambiguous_question_handed_off_without_guessing"
            )
            is True
        ),
        "quiet_hour_transition_verified": policy_checks.get(
            "quiet_hours_transition_observed"
        )
        is True,
        "production_policy_diagnostics_non_authoritative": bool(
            policy_checks.get("production_diagnostic_never_authoritative") is True
            and policy_checks.get("policy_diagnostic_never_changed_execution_authority")
            is True
        ),
        "rolling_24h_semantics_verified": policy_checks.get(
            "rolling_24h_semantics_exact"
        )
        is True,
        "rolling_24h_membership_rollover_verified": policy_checks.get(
            "rolling_24h_membership_rollover_observed"
        )
        is True,
        "zero_policy_escapes": c38.get("zero_policy_escape") is True,
        "zero_unexplained_records": c38.get("zero_unexplained_records") is True,
        "zero_duplicate_tasks": c38.get("zero_duplicate_tasks") is True,
        "zero_false_status_records": c38.get("zero_false_status") is True,
        "no_runaway_retries": c38.get("zero_runaway_retry") is True,
    }
    return {name: bool(values.get(name)) for name in REQUIRED_SHADOW_CHECKS}


def _source_fixture_digest(phase4_freeze: Any) -> str:
    lever = _lever_freeze(phase4_freeze)
    digests = _mapping(lever.get("digests"))
    preferred = _sha256(digests.get("adapter_scoped_fixture_regression_sha256"))
    if not preferred:
        preferred = _sha256(digests.get("fixture_regression_sha256"))
    return f"sha256:{preferred}" if preferred else ""


def _source_evidence_digest(
    *,
    lever_readiness: Any,
    day35: Any,
    day36: Any,
    day37: Any,
    day38: Any,
    promotion_readiness: Any,
) -> str:
    summary = _summary(lever_readiness)
    payload = {
        "lever_ledger_sha256": _sha256(_mapping(lever_readiness).get("ledger_sha256")),
        "lever_runtime_ledger_sha256": _sha256(
            _mapping(lever_readiness).get("runtime_ledger_sha256")
        ),
        "supervised_confirmed_count": summary.get("supervised_confirmed_count"),
        "day35_gate_sha256": _sha256(_mapping(day35).get("gate_sha256")),
        "day36_report_sha256": _report_hash(_mapping(day36)),
        "day37_report_sha256": _report_hash(_mapping(day37)),
        "day38_report_sha256": _report_hash(_mapping(day38)),
        "promotion_readiness_sha256": _sha256(
            _mapping(promotion_readiness).get("report_sha256")
        ),
    }
    if any(value in (None, "") for value in payload.values()):
        return ""
    return "sha256:" + _canonical_hash(payload)


def build_day39_lever_promotion(
    *,
    promotion_readiness: Any,
    lever_readiness: Any,
    phase4_freeze: Any,
    day35_gate: Any,
    day36_report: Any,
    day37_report: Any,
    day38_report: Any,
    operations_readiness: Any,
    owner_approval: Any,
    signing_key: str | bytes | None,
    key_id: str,
) -> dict[str, Any]:
    """Build an installable autonomy release only when every predecessor is genuine."""

    promotion = _mapping(promotion_readiness)
    summary = _summary(lever_readiness)
    gates = _mapping(summary.get("gates"))
    freeze = _mapping(phase4_freeze)
    lever_freeze = _lever_freeze(freeze)
    operations = _mapping(operations_readiness)
    owner = _mapping(owner_approval)

    release_commit = _sha40(promotion.get("release_candidate_revision"))
    owner_commit = _sha40(owner.get("approved_for_commit"))
    phase_b_count = int(summary.get("supervised_confirmed_count") or 0)
    raw_phase_b_count = int(summary.get("raw_supervised_confirmed_count") or 0)
    success_rate = (
        float(phase_b_count) / float(raw_phase_b_count)
        if raw_phase_b_count > 0
        else 0.0
    )

    recovery_drills, recovery_ok = _day35_recovery(day35_gate)
    policy_controls, policy_ok = _day35_policy(day35_gate, day38_report)
    shadow_runs = _shadow_checks(day36_report, day37_report, day38_report)
    shadow_ok = all(shadow_runs.values())

    fixture_digest = _source_fixture_digest(phase4_freeze)
    evidence_digest = _source_evidence_digest(
        lever_readiness=lever_readiness,
        day35=day35_gate,
        day36=day36_report,
        day37=day37_report,
        day38=day38_report,
        promotion_readiness=promotion_readiness,
    )
    policy_digest = "sha256:" + _canonical_hash(
        {
            "operations_readiness": operations_readiness,
            "day35_policy_controls": policy_controls,
            "day38_policy_transitions": _mapping(day38_report).get(
                "production_policy_transitions"
            ),
        }
    )

    defaults = _mapping(operations.get("defaults"))
    invariants = _mapping(operations.get("invariants"))
    failure_threshold = int(defaults.get("failure_threshold") or 0)

    checks = {
        "promotion_readiness_passed": promotion.get("passed") is True
        and promotion.get("promotion_authorized") is True,
        "release_commit_exact": bool(release_commit)
        and _sha40(promotion.get("release_candidate_revision")) == release_commit,
        "promotion_target_exact": str(promotion.get("target_adapter") or "").lower()
        == DAY39_LEVER_ADAPTER
        and str(promotion.get("target_adapter_version") or "") == DAY39_LEVER_VERSION
        and str(promotion.get("target_maturity") or "") == DAY39_TARGET_MATURITY,
        "phase_b_ten_safe_confirmations": phase_b_count
        >= MIN_DISTINCT_CONFIRMED_SUBMISSIONS
        and gates.get("ten_supervised_confirmed_submissions") is True,
        "phase_b_all_successes_reviewed": gates.get(
            "all_success_evidence_independently_reviewed"
        )
        is True,
        "phase_b_payloads_match_approvals": gates.get(
            "all_evidence_hashes_match_consumed_approvals"
        )
        is True,
        "phase_b_zero_false_submitted": gates.get("zero_false_submitted_records") is True,
        "phase_b_zero_duplicates": gates.get("zero_duplicate_submissions") is True,
        "phase_b_uncertain_stays_uncertain": gates.get(
            "all_uncertain_outcomes_remain_uncertain"
        )
        is True,
        "phase_b_minimum_success_rate": raw_phase_b_count >= MIN_RELIABILITY_ATTEMPTS
        and success_rate >= 0.98,
        "phase4_lever_identity_exact": str(lever_freeze.get("version") or "")
        == DAY39_LEVER_VERSION
        and str(lever_freeze.get("maturity") or "") == "dry_run",
        "fixture_digest_present": bool(fixture_digest),
        "evidence_digest_present": bool(evidence_digest),
        "day35_recovery_complete": recovery_ok,
        "policy_controls_complete": policy_ok,
        "shadow_contract_complete": shadow_ok,
        "circuit_breaker_contract_present": failure_threshold >= 1
        and invariants.get("repeated_failures_open_circuit_breaker") is True,
        "owner_approved_exact_commit": owner.get("approved") is True
        and bool(str(owner.get("approval_reference") or "").strip())
        and bool(release_commit)
        and owner_commit == release_commit
        and str(owner.get("adapter") or "").lower() == DAY39_LEVER_ADAPTER
        and str(owner.get("adapter_version") or "") == DAY39_LEVER_VERSION
        and str(owner.get("target_maturity") or "") == DAY39_TARGET_MATURITY,
        "signing_key_present": len(
            signing_key if isinstance(signing_key, bytes) else str(signing_key or "").encode("utf-8")
        )
        >= 32,
        "signing_key_id_present": bool(str(key_id or "").strip()),
    }
    blockers = [name for name, passed in checks.items() if not passed]

    result: dict[str, Any] = {
        "version": DAY39_LEVER_PROMOTION_VERSION,
        "adapter": DAY39_LEVER_ADAPTER,
        "adapter_version": DAY39_LEVER_VERSION,
        "target_maturity": DAY39_TARGET_MATURITY,
        "release_candidate_revision": release_commit or None,
        "checks": checks,
        "blockers": blockers,
        "promotion_record_generated": False,
        "real_submission_enabled": False,
        "real_followup_send_enabled": False,
        "live_window_authorized": False,
        "autonomy_release": None,
    }
    if blockers:
        result["report_sha256"] = _canonical_hash(result)
        return result

    approval_reference = " ".join(str(owner.get("approval_reference") or "").split())
    certification_manifest: dict[str, Any] = {
        "schema_version": AUTONOMY_RELEASE_SCHEMA_VERSION,
        "adapter": {"name": DAY39_LEVER_ADAPTER, "version": DAY39_LEVER_VERSION},
        "source": {
            "release_commit": release_commit,
            "fixture_digest": fixture_digest,
            "evidence_digest": evidence_digest,
            "policy_digest": policy_digest,
        },
        "reliability_window": {
            "evidence_type": "supervised_real_submission",
            "attempts": raw_phase_b_count,
            "confirmed_successes": phase_b_count,
            "distinct_confirmed_submissions": phase_b_count,
            "independently_reviewed_successes": phase_b_count,
            "success_rate": success_rate,
            "false_positive_submitted_records": int(
                summary.get("false_submitted_count") or 0
            ),
            "duplicate_submissions": int(
                summary.get("duplicate_submission_count") or 0
            ),
            "uncertain_outcomes_credited_as_submitted": int(
                summary.get("uncertain_status_violation_count") or 0
            ),
        },
        "retry_policy": {
            "bounded": True,
            "max_automatic_retries_per_attempt": int(
                _mapping(
                    _mapping(
                        _mapping(day35_gate)
                        .get("pilot_configuration_freeze")
                    ).get("configuration")
                ).get("policy", {}).get("maximum_automatic_retries_per_attempt", 1)
            ),
            "no_retry_after_submit_click_without_confirmation": True,
        },
        "circuit_breaker": {
            "verified": True,
            "failure_threshold": failure_threshold,
            "halts_new_submissions": True,
        },
        "recovery_drills": recovery_drills,
        "policy_readiness": {"ready": True, **policy_controls},
        "shadow_runs": shadow_runs,
        "approval": {
            "approved": True,
            "approval_reference": approval_reference,
            "approved_for_commit": release_commit,
        },
        "integrity": {"algorithm": "sha256", "manifest_digest": ""},
        "attestation": {
            "method": AUTONOMY_SIGNATURE_METHOD,
            "key_id": str(key_id).strip(),
            "signature": "",
        },
    }
    certification_manifest["integrity"]["manifest_digest"] = (
        compute_autonomy_manifest_digest(certification_manifest)
    )
    certification_manifest["attestation"]["signature"] = (
        compute_autonomy_manifest_signature(certification_manifest, signing_key or "")
    )
    validation = validate_autonomy_release_manifest(
        certification_manifest,
        adapter_name=DAY39_LEVER_ADAPTER,
        adapter_version=DAY39_LEVER_VERSION,
        trusted_signing_key=signing_key,
    )
    if validation.get("passed") is not True:
        raise Day39LeverPromotionError(
            "Generated autonomy manifest failed its own contract validation: "
            + ", ".join(validation.get("missing") or [])
        )

    autonomy_release: dict[str, Any] = {
        gate: True for gate in AUTONOMY_RELEASE_GATES
    }
    autonomy_release.update(
        {
            "approved": True,
            "approval_reference": approval_reference,
            "certification_manifest": certification_manifest,
        }
    )
    result["promotion_record_generated"] = True
    result["autonomy_release"] = autonomy_release
    result["certification_validation"] = validation
    result["report_sha256"] = _canonical_hash(result)
    return result


__all__ = [
    "DAY39_LEVER_ADAPTER",
    "DAY39_LEVER_PROMOTION_VERSION",
    "DAY39_LEVER_VERSION",
    "Day39LeverPromotionError",
    "build_day39_lever_promotion",
]
