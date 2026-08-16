from __future__ import annotations

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewTask,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from scripts import run_shadow_qualification_canary as canary


def _application_with_review(db_session, *, review_log):
    user = User(
        email="shadow-review-evidence@example.test",
        hashed_password="test-hash",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    job = Job(
        external_id="shadow-review-evidence-job",
        title="Risk Analyst",
        company="Example Bank",
        location="Ottawa, ON",
        source=JobSource.lever,
        status=JobStatus.approved,
        relevance_score=0.95,
        url="https://jobs.lever.co/example-bank/00000000-0000-0000-0000-000000000001",
        raw_data={"application_method": "external_url"},
    )
    db_session.add(job)
    db_session.flush()

    app = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.needs_review.value,
        submission_attempt_count=1,
        automation_log=[],
    )
    db_session.add(app)
    db_session.flush()

    db_session.add(
        ManualReviewTask(
            application_id=app.id,
            reason_code=ManualReviewReason.ambiguous_question.value,
            summary="Application question requires an approved answer policy.",
            details={
                "questions": [
                    {
                        "reason_code": "ambiguous_question",
                        "summary": "Approved answer required",
                        "details": {
                            "descriptor": "cards[opaque][field0]",
                            "control_type": "select",
                        },
                    }
                ],
                "log": list(review_log),
            },
            blocking_url=job.url,
        )
    )
    db_session.commit()
    return app


def test_canary_accepts_allowlisted_browser_evidence_from_same_application_review(db_session):
    app = _application_with_review(
        db_session,
        review_log=[
            {"action": "navigate"},
            {"action": "ats_adapter_detected"},
            {"action": "ats_step_filled"},
        ],
    )

    snapshot = canary._application_snapshot(db_session, app.id)

    assert snapshot["automation_actions"] == []
    assert snapshot["manual_review_browser_actions"] == [
        "navigate",
        "ats_adapter_detected",
    ]
    assert snapshot["browser_or_form_path_observed"] is True
    assert snapshot["legitimate_human_boundary"] is True
    assert snapshot["safe_terminal"] is True
    assert snapshot["consequential_state_observed"] is False


def test_canary_does_not_promote_non_browser_review_log_to_browser_evidence(db_session):
    app = _application_with_review(
        db_session,
        review_log=[
            {"action": "ats_step_filled"},
            {"action": "manual_review_created"},
        ],
    )

    snapshot = canary._application_snapshot(db_session, app.id)

    assert snapshot["manual_review_browser_actions"] == []
    assert snapshot["browser_or_form_path_observed"] is False
    assert snapshot["legitimate_human_boundary"] is False
    assert snapshot["safe_terminal"] is False


def test_canary_cli_main_delegates_to_original_base_without_recursion(monkeypatch):
    calls = []

    def fake_original_run_canary(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "pass"}

    def fake_base_main():
        result = canary._base.run_canary("cli-marker", user_id=4)
        assert result == {"status": "pass"}
        return 0

    original_base_symbol = canary._base.run_canary
    monkeypatch.setattr(canary, "_BASE_RUN_CANARY", fake_original_run_canary)
    monkeypatch.setattr(canary._base, "main", fake_base_main)

    assert canary.main() == 0
    assert calls == [(('cli-marker',), {"user_id": 4})]
    assert canary._base.run_canary is original_base_symbol
