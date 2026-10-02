from app.models.application import ApplicationAutomationState
from app.services.day33_recovery_chaos import (
    DAY33_RECOVERY_POLICY_VERSION,
    FAILURE_MODES,
    run_day33_recovery_chaos_matrix,
)


def _case(report, mode):
    return next(item for item in report["cases"] if item["failure_mode"] == mode)


def test_day33_chaos_matrix_exercises_all_required_failure_modes():
    report = run_day33_recovery_chaos_matrix()

    assert report["policy_version"] == DAY33_RECOVERY_POLICY_VERSION
    assert tuple(report["failure_modes"]) == FAILURE_MODES
    assert {item["failure_mode"] for item in report["cases"]} == set(FAILURE_MODES)
    assert report["passed"] is True
    assert all(report["assertions"].values())
    assert all(item["passed"] is True for item in report["cases"])
    assert len(report["report_sha256"]) == 64


def test_application_interruptions_never_claim_submission_success_or_retry():
    report = run_day33_recovery_chaos_matrix()

    expected = {
        "process_crash": ApplicationAutomationState.needs_review.value,
        "worker_restart": ApplicationAutomationState.submission_uncertain.value,
        "browser_death": ApplicationAutomationState.submission_uncertain.value,
        "device_reboot": ApplicationAutomationState.needs_review.value,
    }
    for mode, expected_state in expected.items():
        case = _case(report, mode)
        assert case["domain"] == "application"
        assert case["actual_state"] == expected_state
        assert case["submission_attempt_count"] == 1
        assert case["automatic_retry_allowed"] is False
        assert case["resume_performed"] is False
        assert case["checks"]["idempotency_key_preserved"] is True
        assert case["checks"]["submission_attempt_count_preserved"] is True
        assert case["checks"]["no_submission_event_created"] is True
        assert case["checks"]["repeat_recovery_is_noop"] is True
        assert case["checks"]["not_marked_submitted"] is True


def test_redis_interruption_reopens_verified_requeue_as_dead_letter():
    report = run_day33_recovery_chaos_matrix()
    case = _case(report, "redis_interruption")

    assert case["domain"] == "bounded_task"
    assert case["resume_performed"] is True
    assert case["resume_checkpoint_verified"] is True
    assert case["dead_letter_status"] == "open"
    assert case["automatic_retry_allowed"] is False
    assert case["requeue_count"] == 1
    assert case["checks"]["complete_context_retained"] is True
    assert case["checks"]["dispatch_failure_reopens_dead_letter"] is True
    assert case["checks"]["checkpoint_preserved"] is True
    assert case["checks"]["attempt_history_preserved"] is True
    assert case["checks"]["status_fail_closed"] is True


def test_database_lock_checkpoint_drift_blocks_resume_and_retains_context():
    report = run_day33_recovery_chaos_matrix()
    case = _case(report, "database_lock")

    assert case["domain"] == "bounded_task"
    assert case["resume_performed"] is False
    assert case["checkpoint_drift_blocked"] is True
    assert "checkpoint drift" in case["drift_error"].lower()
    assert case["dead_letter_status"] == "open"
    assert case["automatic_retry_allowed"] is False
    assert case["checks"]["complete_context_retained"] is True
    assert case["checks"]["task_remains_failed"] is True
    assert case["checks"]["submission_authorized_false"] is True
    assert case["checks"]["outreach_authorized_false"] is True


def test_day33_chaos_harness_is_nonconsequential_and_offline():
    report = run_day33_recovery_chaos_matrix()

    assert report["safety"] == {
        "browser_opened": False,
        "network_contacted": False,
        "celery_dispatched": False,
        "final_submit_clicked": False,
        "recruiter_outreach_sent": False,
        "submission_authorized": False,
        "outreach_authorized": False,
        "adapter_maturity_changed": False,
    }
    assert report["assertions"]["no_duplicate_submission"] is True
    assert report["assertions"]["no_status_corruption"] is True
    assert report["assertions"]["verified_checkpoint_required_for_resume"] is True
    assert report["assertions"]["irrecoverable_tasks_dead_lettered"] is True
