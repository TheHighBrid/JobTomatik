from __future__ import annotations

import copy

from app.services.day39_promotion_readiness import (
    DAY39_REQUIRED_DAY38_POLICY_CHECKS,
    DAY39_REQUIRED_RELEASE_WORKFLOWS,
    build_day39_promotion_readiness,
)


DAY38_SHA = "8" * 40
RELEASE_SHA = "9" * 40
REPORT_SHA = "a" * 64


def _day38_report() -> dict:
    return {
        "version": "day38-twenty-four-hour-shadow-v1",
        "target_evidence_type": "shadow_run_24h",
        "candidate_revision": DAY38_SHA,
        "persisted_elapsed_seconds": 86460.0,
        "passed": True,
        "day39_entry_eligible": True,
        "report_sha256": REPORT_SHA,
        "production_policy_transitions": {
            "observation_span_seconds": 84600.0,
            "rolling_24h_capacity": {
                "semantics": "rolling_previous_24_hours",
                "aged_out_member_application_ids": [101, 102],
            },
            "checks": {
                name: True for name in DAY39_REQUIRED_DAY38_POLICY_CHECKS
            },
        },
    }


def _review() -> dict:
    return {
        "evidence_id": 12,
        "review_status": "verified",
        "review_reference": "physical-day38-strict-review",
        "commit_sha": DAY38_SHA,
        "strict_report_sha256": REPORT_SHA,
    }


def _release_matrix() -> dict:
    return {
        "revision": RELEASE_SHA,
        "current_head": RELEASE_SHA,
        "passed": True,
        "workflows": {
            name: "success" for name in DAY39_REQUIRED_RELEASE_WORKFLOWS
        },
    }


def _adapter() -> dict:
    return {
        "name": "lever",
        "version": "1.1.0",
        "maturity": "dry_run",
        "autonomous_submission_allowed": False,
    }


def _safety() -> dict:
    return {
        "allow_real_application_submit": False,
        "allow_real_followup_send": False,
        "live_window_authorized": False,
    }


def _approval() -> dict:
    return {
        "approved": True,
        "approval_reference": "owner-day39-exact-head-approval",
        "approved_for_commit": RELEASE_SHA,
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "target_maturity": "certified_autonomous",
    }


def _evaluate(*, approval=None, report=None, review=None, matrix=None, safety=None):
    return build_day39_promotion_readiness(
        day38_report=report or _day38_report(),
        day38_review=review or _review(),
        release_matrix=matrix or _release_matrix(),
        adapter_state=_adapter(),
        runtime_safety=safety or _safety(),
        owner_approval=approval,
    )


def test_technical_readiness_does_not_self_grant_owner_approval_or_live_window():
    result = _evaluate()

    assert result["technical_ready"] is True
    assert result["passed"] is False
    assert result["promotion_authorized"] is False
    assert result["owner_approval_required"] is True
    assert result["live_window_authorized"] is False
    assert result["real_submission_authorized"] is False
    assert result["next_action"] == "obtain_owner_promotion_approval"
    assert result["report_sha256"]


def test_exact_owner_approval_can_authorize_promotion_but_not_live_window():
    result = _evaluate(approval=_approval())

    assert result["technical_ready"] is True
    assert result["passed"] is True
    assert result["promotion_authorized"] is True
    assert result["owner_approval_required"] is False
    assert result["live_window_authorized"] is False
    assert result["real_submission_authorized"] is False
    assert result["next_action"] == "open_separate_promotion_change"


def test_day38_must_use_real_rolling_24h_semantics_not_utc_reset_claim():
    report = _day38_report()
    report["production_policy_transitions"]["rolling_24h_capacity"]["semantics"] = "utc_midnight_reset"
    report["production_policy_transitions"]["checks"]["rolling_24h_semantics_exact"] = False

    result = _evaluate(report=report, approval=_approval())

    assert result["technical_ready"] is False
    assert result["passed"] is False
    assert "day38.day38_rolling_semantics_exact" in result["technical_blockers"]
    assert "day38.day38_policy:rolling_24h_semantics_exact" in result["technical_blockers"]
    assert result["invariants"]["legacy_utc_midnight_daily_reset_is_not_a_day38_requirement"] is True


def test_day38_review_must_bind_the_strict_report_and_original_revision():
    review = _review()
    review["commit_sha"] = "7" * 40
    review["strict_report_sha256"] = "b" * 64

    result = _evaluate(review=review, approval=_approval())

    assert result["technical_ready"] is False
    assert "day38_review.day38_review_commit_matches_report" in result["technical_blockers"]
    assert "day38_review.day38_review_binds_strict_report" in result["technical_blockers"]


def test_release_matrix_must_be_exact_current_head_and_every_required_workflow_green():
    matrix = _release_matrix()
    matrix["current_head"] = "6" * 40
    matrix["workflows"]["Backend tests"] = "cancelled"

    result = _evaluate(matrix=matrix, approval=_approval())

    assert result["technical_ready"] is False
    assert "release_matrix.release_matrix_exact_head" in result["technical_blockers"]
    assert "release_matrix.workflow:Backend tests" in result["technical_blockers"]


def test_live_submission_cannot_be_pre_enabled_to_make_promotion_pass():
    safety = _safety()
    safety["allow_real_application_submit"] = True
    safety["live_window_authorized"] = True

    result = _evaluate(safety=safety, approval=_approval())

    assert result["technical_ready"] is False
    assert "runtime_safety.real_submission_still_disabled" in result["technical_blockers"]
    assert "runtime_safety.live_window_not_pre_authorized" in result["technical_blockers"]
    assert result["promotion_authorized"] is False


def test_owner_approval_is_bound_to_exact_release_commit_adapter_and_target_maturity():
    approval = _approval()
    approval.update(
        {
            "approved_for_commit": DAY38_SHA,
            "adapter_version": "1.2.0",
            "target_maturity": "dry_run",
        }
    )

    result = _evaluate(approval=approval)

    assert result["technical_ready"] is True
    assert result["passed"] is False
    assert "owner_release_commit_exact" in result["owner_approval_blockers"]
    assert "owner_adapter_version_exact" in result["owner_approval_blockers"]
    assert "owner_target_maturity_exact" in result["owner_approval_blockers"]


def test_day38_revision_is_allowed_to_precede_post_shadow_release_candidate():
    result = _evaluate(approval=_approval())

    assert result["day38_candidate_revision"] == DAY38_SHA
    assert result["release_candidate_revision"] == RELEASE_SHA
    assert DAY38_SHA != RELEASE_SHA
    assert result["passed"] is True
    assert result["invariants"]["day38_revision_may_precede_release_candidate"] is True
