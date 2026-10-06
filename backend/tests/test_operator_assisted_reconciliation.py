from types import SimpleNamespace

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import HandoffChallengeType, HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services import operator_assisted_final_action as final_action
from app.services.operator_assisted_final_action import (
    claim_operator_final_action,
    finalize_operator_final_action,
)
from app.services.operator_assisted_submission import (
    OPERATOR_ASSISTED_APPROVAL_SOURCE,
    OperatorAssistedSubmissionError,
)


GREENHOUSE_URL = "https://job-boards.greenhouse.io/example/jobs/1234567"


def _fixture(db_session):
    user = User(
        email="operator-reconcile@example.test",
        hashed_password="not-used",
        full_name="Operator Reconcile",
    )
    job = Job(
        title="Support Engineer",
        company="Example Employer",
        url=GREENHOUSE_URL,
    )
    db_session.add_all([user, job])
    db_session.flush()

    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applying,
        automation_state=ApplicationAutomationState.applying.value,
        submission_idempotency_key="operator-reconcile:1",
        submission_attempt_count=1,
    )
    db_session.add(application)
    db_session.flush()

    review = ManualReviewTask(
        application_id=application.id,
        reason_code=ManualReviewReason.operator_final_submit_required.value,
        status=ManualReviewStatus.in_progress.value,
        summary="Owner final action is required.",
        blocking_url=job.url,
        details={"operator_final_click_required": True},
    )
    db_session.add(review)
    db_session.flush()

    session = ManualHandoffSession(
        application_id=application.id,
        manual_review_id=review.id,
        user_id=user.id,
        challenge_type=HandoffChallengeType.final_submit.value,
        status=HandoffSessionStatus.claimed.value,
        idempotency_key="handoff:operator-reconcile:1",
        resume_token_hash="a" * 64,
        encrypted_resume_token="synthetic",
        resume_token_prefix="synthetic",
        browser_provider="local",
        current_url=job.url,
        current_fingerprint="pre-submit",
        expires_at=review.created_at if review.created_at is not None else None,
        handoff_metadata={},
    )
    # SQLite fixtures assign created_at on flush; keep the handoff safely future-dated.
    from datetime import datetime, timedelta
    session.expires_at = datetime.utcnow() + timedelta(hours=1)
    db_session.add(session)
    db_session.flush()

    approval = SubmissionApproval(
        application_id=application.id,
        user_id=user.id,
        platform="greenhouse",
        status=SubmissionApprovalStatus.consumed.value,
        employer=job.company,
        role=job.title,
        application_url=job.url,
        submission_idempotency_key=application.submission_idempotency_key,
        profile_snapshot_hash="1" * 64,
        resume_hash="2" * 64,
        cover_letter_hash="3" * 64,
        answer_payload_hash="4" * 64,
        combined_payload_hash="5" * 64,
        approval_metadata={
            "approval_source": OPERATOR_ASSISTED_APPROVAL_SOURCE,
            "handoff_public_id": session.public_id,
            "operator_final_click_required": True,
            "automated_submission_authorized": False,
            "queue_submission_authorized": False,
        },
    )
    db_session.add(approval)
    db_session.commit()
    return user, application, review, session, approval


def test_unconfirmed_once_only_action_becomes_submission_uncertain(
    db_session,
    monkeypatch,
):
    user, application, review, session, approval = _fixture(db_session)
    monkeypatch.setattr(final_action, "_claim_runtime_blockers", lambda _url: [])

    claimed = claim_operator_final_action(
        db_session,
        application,
        session,
        user_id=user.id,
    )
    assert claimed.id == approval.id

    finalize_operator_final_action(
        db_session,
        application,
        session,
        approval,
        result={
            "submission_confirmed": False,
            "current_url": GREENHOUSE_URL,
            "current_fingerprint": "post-action-unconfirmed",
        },
    )
    db_session.commit()
    db_session.refresh(application)
    db_session.refresh(review)
    db_session.refresh(session)
    db_session.refresh(approval)

    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value
    assert application.status == ApplicationStatus.pending
    assert review.reason_code == ManualReviewReason.submission_confirmation_uncertain.value
    assert review.details["confirmation_reconciliation_required"] is True
    assert review.details["automatic_retry_allowed"] is False
    assert session.handoff_metadata["confirmation_reconciliation_required"] is True
    assert approval.approval_metadata["operator_submit_action_result"] == "awaiting_confirmation"
    assert approval.approval_metadata["automatic_retry_allowed"] is False

    with pytest.raises(OperatorAssistedSubmissionError, match="already requested"):
        claim_operator_final_action(
            db_session,
            application,
            session,
            user_id=user.id,
        )


def test_exception_after_claim_becomes_submission_uncertain(
    db_session,
    monkeypatch,
):
    user, application, review, session, approval = _fixture(db_session)
    monkeypatch.setattr(final_action, "_claim_runtime_blockers", lambda _url: [])
    claim_operator_final_action(
        db_session,
        application,
        session,
        user_id=user.id,
    )

    finalize_operator_final_action(
        db_session,
        application,
        session,
        approval,
        error=RuntimeError("synthetic browser interruption"),
    )
    db_session.commit()
    db_session.refresh(application)
    db_session.refresh(review)
    db_session.refresh(approval)

    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value
    assert review.reason_code == ManualReviewReason.submission_confirmation_uncertain.value
    assert approval.approval_metadata["operator_submit_action_result"] == "uncertain"
    assert approval.approval_metadata["automatic_retry_allowed"] is False


def test_runtime_gate_uses_the_registered_platform_pilot_switch(monkeypatch):
    monkeypatch.setattr(
        final_action,
        "get_operations_settings",
        lambda: SimpleNamespace(
            global_kill_switch=False,
            autopilot_enabled=False,
            disabled_platforms="",
        ),
    )
    monkeypatch.setattr(
        final_action,
        "get_settings",
        lambda: SimpleNamespace(
            allow_real_application_submit=False,
            greenhouse_supervised_pilot_enabled=True,
            lever_supervised_pilot_enabled=False,
        ),
    )

    assert final_action._claim_runtime_blockers(GREENHOUSE_URL) == [
        "operator_assisted_requires_platform_pilot_disabled"
    ]
