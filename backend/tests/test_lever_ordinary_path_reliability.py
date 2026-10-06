from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.lever_ordinary_path_reliability import (
    LeverOrdinaryPathError,
    reconcile_lever_confirmation,
    record_answer_vault_interruption,
    recover_stranded_application,
    resume_same_application,
)
from tests.conftest import TestingSessionLocal


LEVER_URL = "https://jobs.lever.co/maple/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
THANKS_URL = LEVER_URL + "/thanks"
OTHER_URL = "https://jobs.lever.co/maple/11111111-2222-3333-4444-555555555555"


@pytest.fixture
def records(auth_client):
    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").one()
    job = Job(
        external_id="lever-ordinary-path",
        title="Support Analyst",
        company="Maple",
        url=LEVER_URL,
        source=JobSource.lever,
        status=JobStatus.approved,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applying,
        automation_state=ApplicationAutomationState.applying.value,
        submission_idempotency_key="lever-ordinary-1",
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    ids = {"application_id": application.id, "job_id": job.id}
    db.close()
    return ids


def _load(ids):
    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == ids["application_id"]).one()
    job = db.query(Job).filter(Job.id == ids["job_id"]).one()
    return db, application, job


def test_repeated_answer_vault_interruptions_resume_same_application(records):
    db, application, job = _load(records)
    first = record_answer_vault_interruption(db, application, job, question="Work eligibility", current_url=LEVER_URL)
    second = record_answer_vault_interruption(db, application, job, question="Salary expectation", current_url=LEVER_URL)
    resumed = resume_same_application(db, application, job, current_url=LEVER_URL)
    db.commit()
    db.close()
    assert first["application_id"] == second["application_id"] == resumed["application_id"]
    assert second["interruption_count"] == 2
    assert resumed["opened_new_application"] is False
    assert resumed["resume_count"] == 1


def test_resume_rejects_a_different_posting(records):
    db, application, job = _load(records)
    with pytest.raises(LeverOrdinaryPathError) as caught:
        resume_same_application(db, application, job, current_url=OTHER_URL)
    assert caught.value.code == "target_continuity_broken"
    db.close()


def test_confirmation_persists_evidence_before_promotion_and_closes_handoff(records):
    db, application, job = _load(records)
    review = ManualReviewTask(
        application_id=application.id,
        reason_code="answer_required",
        status=ManualReviewStatus.open.value,
        summary="Need salary expectation",
    )
    db.add(review)
    db.flush()
    db.add(
        ManualHandoffSession(
            application_id=application.id,
            manual_review_id=review.id,
            user_id=application.user_id,
            challenge_type="final_submit",
            status=HandoffSessionStatus.awaiting_user.value,
            idempotency_key="lever-handoff-1",
            resume_token_hash="a" * 64,
            encrypted_resume_token="encrypted",
            resume_token_prefix="prefix",
            expires_at=datetime.utcnow() + timedelta(minutes=20),
        )
    )
    db.commit()
    result = reconcile_lever_confirmation(
        db,
        application,
        job,
        final_url=THANKS_URL,
        confirmation_text="Application submitted!",
        target_verified=True,
        approval_reference="lvsup-test",
    )
    db.commit()
    evidence = db.query(SubmissionEvidence).filter(SubmissionEvidence.id == result["evidence_id"]).one()
    events = db.query(ApplicationEvent).filter(ApplicationEvent.application_id == application.id).all()
    event_types = [item.event_type for item in events]
    review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review.id).one()
    handoff = db.query(ManualHandoffSession).filter(ManualHandoffSession.application_id == application.id).one()
    db.close()
    assert evidence.is_sufficient is True
    assert event_types.index("lever_confirmation_evidence_persisted") < event_types.index("lever_ordinary_path_confirmed")
    assert result["status"] == "applied"
    assert result["automation_state"] == "confirmed"
    assert review.status == ManualReviewStatus.resolved.value
    assert handoff.status == HandoffSessionStatus.completed.value


def test_thanks_url_without_explicit_phrase_is_uncertain(records):
    db, application, job = _load(records)
    with pytest.raises(LeverOrdinaryPathError) as caught:
        reconcile_lever_confirmation(
            db,
            application,
            job,
            final_url=THANKS_URL,
            confirmation_text="We'll be in touch",
            target_verified=True,
        )
    db.commit()
    state = db.query(Application).filter(Application.id == application.id).one().automation_state
    db.close()
    assert caught.value.code == "confirmation_not_explicit"
    assert state == "submission_uncertain"


def test_stale_target_does_not_confirm(records):
    db, application, job = _load(records)
    with pytest.raises(LeverOrdinaryPathError) as caught:
        reconcile_lever_confirmation(
            db,
            application,
            job,
            final_url=OTHER_URL + "/thanks",
            confirmation_text="Application submitted!",
            target_verified=False,
        )
    db.commit()
    status = db.query(Application).filter(Application.id == application.id).one().status
    db.close()
    assert caught.value.code == "stale_or_unverified_target"
    assert status == ApplicationStatus.applying


def test_confirmed_posting_blocks_a_new_application(records):
    db, application, job = _load(records)
    reconcile_lever_confirmation(
        db,
        application,
        job,
        final_url=THANKS_URL,
        confirmation_text="Thanks for applying",
        target_verified=True,
    )
    duplicate = Application(
        user_id=application.user_id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.preparing.value,
        submission_idempotency_key="lever-ordinary-2",
    )
    db.add(duplicate)
    db.commit()
    with pytest.raises(LeverOrdinaryPathError) as caught:
        resume_same_application(db, duplicate, job, current_url=LEVER_URL)
    db.close()
    assert caught.value.code == "duplicate_lever_submission_blocked"


def test_stranded_applying_without_evidence_becomes_uncertain(records):
    db, application, job = _load(records)
    application.updated_at = datetime.utcnow() - timedelta(hours=8)
    db.commit()
    result = recover_stranded_application(db, application, job, now=datetime.utcnow())
    db.commit()
    db.close()
    assert result["confirmed"] is False
    assert result["automation_state"] == "submission_uncertain"


def test_stranded_with_sufficient_evidence_reconciles(records):
    db, application, job = _load(records)
    db.add(
        SubmissionEvidence(
            application_id=application.id,
            evidence_type="confirmation_page",
            is_sufficient=True,
            final_url=THANKS_URL,
            confirmation_text="Application submitted!",
        )
    )
    application.automation_state = ApplicationAutomationState.applying.value
    db.commit()
    result = recover_stranded_application(db, application, job)
    db.commit()
    db.close()
    assert result["confirmed"] is True
    assert result["status"] == "applied"


def test_module_does_not_attempt_captcha():
    from app.services import lever_ordinary_path_reliability as reliability

    source = open(reliability.__file__, encoding="utf-8").read()
    assert "solve_captcha" not in source
    assert "hcaptcha" not in source.lower()
