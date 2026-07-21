from datetime import datetime, timedelta

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.handoff import HandoffChallengeType, HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job
from app.models.user import User
from app.services import browser_handoff
from app.tasks import handoffs as handoff_tasks


class _FakeLocator:
    def __init__(self, text):
        self._text = text

    async def inner_text(self):
        return self._text


class _FakePage:
    def __init__(self):
        self.url = (
            "https://job-boards.greenhouse.io/embed/job_app/confirmation"
            "?for=fanduel&token=7951203"
        )

    def locator(self, selector):
        assert selector == "body"
        return _FakeLocator(
            "Thank you for applying. Your application has been received. "
            "If there is a fit, someone will be getting back to you."
        )


class _FakeContext:
    async def storage_state(self):
        return {"cookies": [], "origins": []}


class _FakePlaywright:
    async def stop(self):
        return None


class _SessionProxy:
    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        return None


@pytest.mark.asyncio
async def test_greenhouse_confirmation_page_outweighs_missing_captcha_response(monkeypatch):
    page = _FakePage()
    session = ManualHandoffSession(
        public_id="confirmation-test",
        application_id=1,
        manual_review_id=1,
        user_id=1,
        challenge_type=HandoffChallengeType.captcha.value,
        browser_provider="local_cdp",
    )

    async def fake_connect(_session):
        return _FakePlaywright(), object(), _FakeContext(), page

    async def fake_fingerprint(_page):
        return "confirmation-fingerprint"

    monkeypatch.setattr(browser_handoff, "_connect_local_cdp", fake_connect)
    monkeypatch.setattr(browser_handoff, "page_fingerprint", fake_fingerprint)

    verification = await browser_handoff.verify_browser_handoff_completion(session)

    assert verification.challenge_cleared is True
    assert verification.current_url.endswith("for=fanduel&token=7951203")
    assert verification.evidence["submission_confirmed"] is True
    assert verification.evidence["verification_method"] == "explicit_submission_confirmation"
    evidence = verification.evidence["confirmation_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["evidence_type"] == "confirmation_page"
    assert evidence[0]["is_sufficient"] is True
    assert evidence[0]["confirmation_text"] == "thank you for applying"


@pytest.mark.asyncio
async def test_resume_short_circuits_on_confirmation_even_when_handoff_started_as_dry_run(monkeypatch):
    page = _FakePage()
    session = ManualHandoffSession(
        public_id="confirmation-resume-test",
        application_id=1,
        manual_review_id=1,
        user_id=1,
        challenge_type=HandoffChallengeType.captcha.value,
        browser_provider="local_cdp",
        handoff_metadata={"dry_run": True, "adapter": "greenhouse", "adapter_version": "1.1.1"},
    )

    async def fake_connect(_session):
        return _FakePlaywright(), object(), _FakeContext(), page

    monkeypatch.setattr(browser_handoff, "_connect_local_cdp", fake_connect)

    result = await browser_handoff.resume_handoff_application(
        session,
        user_profile={},
        cover_letter="",
        resume_path="",
        dry_run=True,
    )

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["submission_confirmed"] is True
    assert result["ready_to_submit"] is False
    assert result["requires_manual_review"] is False
    assert result["ats_adapter"] == "greenhouse"
    assert result["confirmation_evidence"][0]["is_sufficient"] is True
    assert any(
        item["action"] == "handoff_submission_confirmation_detected"
        for item in result["log"]
    )


def test_worker_records_evidence_and_confirms_application_started_as_dry_run(db_session, monkeypatch):
    user = User(
        email="handoff-confirmation@example.com",
        hashed_password="test",
        full_name="Confirmation User",
        profile_data={},
        automation_settings={"auto_followup": False},
    )
    job = Job(
        title="Lead Product Manager, Payments",
        company="FanDuel",
        url="https://job-boards.greenhouse.io/fanduel/jobs/7951203",
    )
    db_session.add_all([user, job])
    db_session.flush()

    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.needs_review.value,
        submission_idempotency_key="confirmation-worker-test",
        cover_letter="Prepared cover letter",
    )
    db_session.add(application)
    db_session.flush()

    review = ManualReviewTask(
        application_id=application.id,
        reason_code=ManualReviewReason.captcha_detected.value,
        status=ManualReviewStatus.in_progress.value,
        summary="Complete the human verification challenge.",
    )
    db_session.add(review)
    db_session.flush()

    handoff = ManualHandoffSession(
        public_id="confirmed-worker-handoff",
        application_id=application.id,
        manual_review_id=review.id,
        user_id=user.id,
        challenge_type=HandoffChallengeType.captcha.value,
        status=HandoffSessionStatus.ready_to_resume.value,
        idempotency_key="confirmed-worker-handoff-v1",
        resume_token_hash="a" * 64,
        encrypted_resume_token="encrypted",
        resume_token_prefix="prefix",
        browser_provider="local_cdp",
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        handoff_metadata={"dry_run": True, "adapter": "greenhouse", "adapter_version": "1.1.1"},
    )
    db_session.add(handoff)
    db_session.commit()

    async def fake_resume(*args, **kwargs):
        return {
            "success": True,
            "dry_run": True,
            "submitted_at": datetime.utcnow().isoformat(),
            "url": "https://job-boards.greenhouse.io/embed/job_app/confirmation?for=fanduel",
            "log": [{"action": "handoff_submission_confirmation_detected"}],
            "error": None,
            "fields_filled": 0,
            "requires_manual_review": False,
            "review_items": [],
            "ready_to_submit": False,
            "submission_confirmed": True,
            "confirmation_evidence": [{
                "evidence_type": "confirmation_page",
                "is_sufficient": True,
                "final_url": "https://job-boards.greenhouse.io/embed/job_app/confirmation?for=fanduel",
                "confirmation_text": "thank you for applying",
                "selector": "body",
                "metadata": {"verification_method": "explicit_confirmation_text"},
            }],
            "ats_adapter": "greenhouse",
            "ats_adapter_version": "1.1.1",
        }

    monkeypatch.setattr(handoff_tasks, "SessionLocal", lambda: _SessionProxy(db_session))
    monkeypatch.setattr(handoff_tasks, "resume_handoff_application", fake_resume)
    monkeypatch.setattr(handoff_tasks, "terminate_retained_browser", lambda session: True)

    result = handoff_tasks.resume_handoff_session_task.run(handoff.public_id)

    assert result["submission_confirmed"] is True
    db_session.expire_all()
    refreshed_app = db_session.query(Application).filter(Application.id == application.id).one()
    refreshed_review = db_session.query(ManualReviewTask).filter(ManualReviewTask.id == review.id).one()
    refreshed_handoff = db_session.query(ManualHandoffSession).filter(
        ManualHandoffSession.id == handoff.id
    ).one()
    evidence = db_session.query(SubmissionEvidence).filter(
        SubmissionEvidence.application_id == application.id
    ).all()

    assert refreshed_app.status == ApplicationStatus.applied
    assert refreshed_app.automation_state == ApplicationAutomationState.confirmed.value
    assert refreshed_app.applied_at is not None
    assert refreshed_review.status == ManualReviewStatus.resolved.value
    assert refreshed_handoff.status == HandoffSessionStatus.completed.value
    assert len(evidence) == 1
    assert evidence[0].evidence_type == "confirmation_page"
    assert evidence[0].is_sufficient is True
