from __future__ import annotations

import hashlib
import json

from app.services.ats_maturity import AdapterMaturity, annotate_adapter_manifest
from app.services.autonomy_release_loader import load_lever_autonomy_release
from app.services.day39_lever_promotion import build_day39_lever_promotion


REVISION = "c" * 40
KEY = "day39-promotion-test-signing-key-0000000000001"
KEY_ID = "day39-test-key"


def _hash(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _sealed(value):
    result = dict(value)
    result["report_sha256"] = _hash(result)
    return result


def _promotion():
    value = {
        "passed": True,
        "promotion_authorized": True,
        "release_candidate_revision": REVISION,
        "target_adapter": "lever",
        "target_adapter_version": "1.1.0",
        "target_maturity": "certified_autonomous",
    }
    value["report_sha256"] = _hash(value)
    return value


def _lever_readiness(count=10):
    complete = count >= 10
    return {
        "ledger_sha256": "1" * 64,
        "runtime_ledger_sha256": "2" * 64 if count else None,
        "summary": {
            "raw_supervised_confirmed_count": count,
            "supervised_confirmed_count": count,
            "false_submitted_count": 0,
            "duplicate_submission_count": 0,
            "uncertain_status_violation_count": 0,
            "gates": {
                "ten_supervised_confirmed_submissions": complete,
                "all_success_evidence_independently_reviewed": complete,
                "all_evidence_hashes_match_consumed_approvals": complete,
                "zero_false_submitted_records": True,
                "zero_duplicate_submissions": True,
                "all_uncertain_outcomes_remain_uncertain": True,
            },
        },
    }


def _phase4():
    return {
        "adapters": {
            "lever": {
                "version": "1.1.0",
                "maturity": "dry_run",
                "digests": {
                    "adapter_scoped_fixture_regression_sha256": "3" * 64,
                },
            }
        }
    }


def _day35():
    failure_modes = [
        {
            "failure_mode": name,
            "passed": True,
        }
        for name in (
            "process_crash",
            "worker_restart",
            "redis_interruption",
            "database_lock",
            "browser_death",
        )
    ]
    return {
        "gate_passed": True,
        "gate_sha256": "4" * 64,
        "completed_recovery_evidence": {
            "passed": True,
            "failure_modes": failure_modes,
            "digest": "sha256:" + "5" * 64,
        },
        "rehearsal": {
            "assertions": {
                "daily_weekly_caps_tracked": True,
                "platform_cap_exhaustion_verified": True,
            }
        },
        "pilot_configuration_freeze": {
            "valid": True,
            "configuration": {
                "policy": {"maximum_automatic_retries_per_attempt": 1},
                "runtime_invariants": {
                    "real_application_submit_must_remain_false": True,
                },
            },
        },
        "provisional_autonomy_recommendation": {
            "source_bindings": {
                "phase4_gate_digest": "sha256:" + "6" * 64,
                "pilot_configuration_digest": "sha256:" + "7" * 64,
            }
        },
    }


def _day36():
    return _sealed(
        {
            "passed": True,
            "target_evidence_type": "shadow_run_4h",
            "checks": {"final_submit_disabled": True},
        }
    )


def _day37():
    return _sealed(
        {
            "passed": True,
            "target_evidence_type": "shadow_run_8h",
            "checks": {"final_submit_disabled": True},
            "incidents": {
                "observed_types": [
                    "source_outage",
                    "browser_crash",
                    "stale_posting",
                    "ambiguous_question",
                ],
                "checks": {
                    "source_outage_isolated_without_raw_exception": True,
                    "browser_controlled_page_recovered": True,
                    "stale_posting_terminal_without_retry": True,
                    "ambiguous_question_handed_off_without_guessing": True,
                },
            },
        }
    )


def _day38():
    return _sealed(
        {
            "passed": True,
            "day39_entry_eligible": True,
            "target_evidence_type": "shadow_run_24h",
            "checks": {
                "final_submit_disabled": True,
                "browser_cleanup_reconciled": True,
                "no_active_application_work": True,
                "zero_policy_escape": True,
                "zero_unexplained_records": True,
                "zero_duplicate_tasks": True,
                "zero_false_status": True,
                "zero_runaway_retry": True,
            },
            "production_policy_transitions": {
                "checks": {
                    "quiet_hours_transition_observed": True,
                    "production_diagnostic_never_authoritative": True,
                    "policy_diagnostic_never_changed_execution_authority": True,
                    "rolling_24h_semantics_exact": True,
                    "rolling_24h_membership_rollover_observed": True,
                }
            },
        }
    )


def _operations():
    return {
        "real_submission_enabled": False,
        "defaults": {"failure_threshold": 3},
        "invariants": {"repeated_failures_open_circuit_breaker": True},
    }


def _owner(commit=REVISION):
    return {
        "approved": True,
        "approval_reference": "day39-owner-promotion",
        "approved_for_commit": commit,
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "target_maturity": "certified_autonomous",
    }


def _build(*, count=10, key=KEY, owner=None):
    return build_day39_lever_promotion(
        promotion_readiness=_promotion(),
        lever_readiness=_lever_readiness(count),
        phase4_freeze=_phase4(),
        day35_gate=_day35(),
        day36_report=_day36(),
        day37_report=_day37(),
        day38_report=_day38(),
        operations_readiness=_operations(),
        owner_approval=owner or _owner(),
        signing_key=key,
        key_id=KEY_ID,
    )


def test_phase_b_zero_of_ten_cannot_generate_promotion():
    result = _build(count=0)

    assert result["promotion_record_generated"] is False
    assert result["autonomy_release"] is None
    assert "phase_b_ten_safe_confirmations" in result["blockers"]
    assert "phase_b_all_successes_reviewed" in result["blockers"]
    assert result["real_submission_enabled"] is False
    assert result["live_window_authorized"] is False


def test_wrong_owner_commit_or_missing_signing_key_blocks():
    wrong_commit = _build(owner=_owner("d" * 40))
    assert wrong_commit["promotion_record_generated"] is False
    assert "owner_approved_exact_commit" in wrong_commit["blockers"]

    missing_key = _build(key="")
    assert missing_key["promotion_record_generated"] is False
    assert "signing_key_present" in missing_key["blockers"]


def test_complete_evidence_builds_signed_record_but_does_not_enable_submit():
    result = _build()

    assert result["promotion_record_generated"] is True
    assert result["blockers"] == []
    assert result["real_submission_enabled"] is False
    assert result["live_window_authorized"] is False
    release = result["autonomy_release"]
    assert release is not None
    assert release["approved"] is True
    assert release["certification_manifest"]["source"]["release_commit"] == REVISION
    assert result["certification_validation"]["passed"] is True

    raw_adapter = {
        "name": "lever",
        "version": "1.1.0",
        "supported_hosts": ["jobs.lever.co"],
        "live_certification": {
            "synthetic_full_form_exercise": "certified",
            "verified_resume_upload": True,
            "final_submit_clicked": False,
        },
        "autonomy_release": release,
    }
    trusted = annotate_adapter_manifest(raw_adapter, trusted_signing_key=KEY)
    untrusted = annotate_adapter_manifest(raw_adapter, trusted_signing_key="")
    assert trusted["maturity"] == AdapterMaturity.CERTIFIED_AUTONOMOUS.value
    assert trusted["autonomous_submission_allowed"] is True
    assert untrusted["maturity"] == AdapterMaturity.DRY_RUN.value
    assert untrusted["autonomous_submission_allowed"] is False


def test_tampered_certification_manifest_fails_closed_to_dry_run():
    result = _build()
    release = dict(result["autonomy_release"])
    manifest = json.loads(json.dumps(release["certification_manifest"]))
    manifest["reliability_window"]["duplicate_submissions"] = 1
    release["certification_manifest"] = manifest

    annotated = annotate_adapter_manifest(
        {
            "name": "lever",
            "version": "1.1.0",
            "supported_hosts": ["jobs.lever.co"],
            "live_certification": {
                "synthetic_full_form_exercise": "certified",
                "verified_resume_upload": True,
                "final_submit_clicked": False,
            },
            "autonomy_release": release,
        },
        trusted_signing_key=KEY,
    )
    assert annotated["maturity"] == AdapterMaturity.DRY_RUN.value
    assert annotated["release_gate_status"]["certified_autonomous"]["passed"] is False


def test_loader_accepts_only_generated_lever_wrapper(tmp_path):
    blocked = _build(count=0)
    blocked_path = tmp_path / "blocked.json"
    blocked_path.write_text(json.dumps(blocked), encoding="utf-8")
    assert load_lever_autonomy_release(blocked_path) is None

    generated = _build()
    generated_path = tmp_path / "generated.json"
    generated_path.write_text(json.dumps(generated), encoding="utf-8")
    loaded = load_lever_autonomy_release(generated_path)
    assert loaded is not None
    assert loaded["approval_reference"] == "day39-owner-promotion"
