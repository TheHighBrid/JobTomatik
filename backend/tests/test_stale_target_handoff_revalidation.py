from __future__ import annotations

from types import SimpleNamespace

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ApplicationTargetStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services import application_target_task_integration
from app.services.application_target_task_integration import (
    _prepare_target,
    _retire_stale_target_resolution_handoffs,
)
from app.services.handoff_session import issue_handoff_session
from tests.conftest import TestingSessionLocal


LINKEDIN_URL = "https://www.linkedin.com/jobs/view/4442675569"
GREENHOUSE_URL = "https://job-boards.greenhouse.io/affirm/jobs/7806920003"


def _application(db_session, *, target_status: str, target_url: str | None = None):
    user = User(
        email="handoff-revalidation@example.com",
        hashed_password="test",
        full_name="Test Candidate",
    )
    job = Job(
        external_id="linkedin:4442675569",
        title="Senior Machine Learning Engineer (Fraud)",
        company="Affirm",
        location="Ottawa, ON",
        url=LINKEDIN_URL,
        source=JobSource.linkedin,
        status=JobStatus.approved,
    )
    db_session.add_all([user, job])
    db_session.flush()

    app = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.needs_review.value,
        source_listing_url=LINKEDIN_URL,
        application_target_url=target_url,
        application_target_status=target_status,
        application_target_metadata={},
    )
    db_session.add(app)
    db_session.flush()
    return user, job, app


def _captcha_handoff(db_session, app, *, metadata, current_url):
    review = ManualReviewTask(
        application_id=app.id,
        reason_code=ManualReviewReason.captcha_detected.value,
        status=ManualReviewStatus.open.value,
        summary="A CAPTCHA requires manual completion.",
        details={},
        blocking_url=current_url,
    )
    db_session.add(review)
    db_session.flush()

    issued = issue_handoff_session(
        db_session,
        app,
        review,
        browser_provider="local_cdp",
        browser_session_id="browser-session-test",
        browser_endpoint="http://127.0.0.1:9222",
        current_url=current_url,
        current_fingerprint="fixture-fingerprint",
        metadata=metadata,
    )
    db_session.flush()
    return review, issued.session


def test_fresh_attempt_retires_old_target_resolution_security_handoff(db_session):
    _, _, app = _application(
        db_session,
        target_status=ApplicationTargetStatus.requires_human.value,
    )
    review, session = _captcha_handoff(
        db_session,
        app,
        current_url=LINKEDIN_URL,
        metadata={
            "stage": "application_target_security_boundary",
            "target_resolution_only": True,
            "source_listing_url": LINKEDIN_URL,
        },
    )
    db_session.commit()

    retired = _retire_stale_target_resolution_handoffs(db_session, app)
    db_session.commit()
    db_session.refresh(app)
    db_session.refresh(review)
    db_session.refresh(session)

    assert retired == 1
    assert session.status == HandoffSessionStatus.cancelled.value
    assert session.cancelled_at is not None
    assert session.handoff_metadata["superseded_by"] == (
        "fresh_application_target_revalidation"
    )
    assert review.status == ManualReviewStatus.dismissed.value
    assert app.application_target_status == ApplicationTargetStatus.unresolved.value
    assert app.application_target_metadata["stale_target_resolution_handoffs_retired"] == 1


def test_post_fill_ats_handoff_is_preserved_for_dedicated_resume(db_session):
    _, _, app = _application(
        db_session,
        target_status=ApplicationTargetStatus.resolved.value,
        target_url=GREENHOUSE_URL,
    )
    review, session = _captcha_handoff(
        db_session,
        app,
        current_url=GREENHOUSE_URL,
        metadata={
            "stage": "ats_application",
            "target_resolution_only": False,
            "resolved_target_url": GREENHOUSE_URL,
        },
    )
    db_session.commit()

    retired = _retire_stale_target_resolution_handoffs(db_session, app)
    db_session.commit()
    db_session.refresh(app)
    db_session.refresh(review)
    db_session.refresh(session)

    assert retired == 0
    assert session.status == HandoffSessionStatus.awaiting_user.value
    assert review.status == ManualReviewStatus.in_progress.value
    assert app.application_target_status == ApplicationTargetStatus.resolved.value
    assert app.application_target_url == GREENHOUSE_URL


def test_worker_target_preparation_revalidates_instead_of_reusing_stale_handoff(
    db_session,
    monkeypatch,
):
    _, _, app = _application(
        db_session,
        target_status=ApplicationTargetStatus.requires_human.value,
    )
    _review, session = _captcha_handoff(
        db_session,
        app,
        current_url=LINKEDIN_URL,
        metadata={
            "stage": "application_target_security_boundary",
            "target_resolution_only": True,
            "source_listing_url": LINKEDIN_URL,
        },
    )
    app_id = app.id
    session_id = session.id
    db_session.commit()

    calls = []

    async def fresh_resolver(source_url: str):
        calls.append(source_url)
        return {
            "success": True,
            "dry_run": True,
            "source_listing_url": source_url,
            "application_target_url": GREENHOUSE_URL,
            "application_target_status": ApplicationTargetStatus.resolved.value,
            "resolution_method": "acceptance_fixture",
            "application_form_detected": True,
            "form_evidence": {
                "present": True,
                "surface_url": GREENHOUSE_URL,
                "visible_controls": 5,
                "applicant_controls": 4,
                "upload_controls": 1,
                "email_controls": 1,
                "submit_controls": 1,
            },
            "requires_manual_review": False,
            "review_items": [],
            "error": None,
            "log": [{"action": "fresh_resolver_called"}],
        }

    monkeypatch.setattr(
        application_target_task_integration,
        "resolve_application_target_with_browser",
        fresh_resolver,
    )

    prepared = _prepare_target(
        SimpleNamespace(SessionLocal=TestingSessionLocal),
        app_id,
    )

    assert calls == [LINKEDIN_URL]
    assert prepared == {
        "target_url": GREENHOUSE_URL,
        "source_url": LINKEDIN_URL,
    }

    db = TestingSessionLocal()
    refreshed = db.query(Application).filter(Application.id == app_id).one()
    retired_session = db.query(ManualHandoffSession).filter(
        ManualHandoffSession.id == session_id
    ).one()
    assert retired_session.status == HandoffSessionStatus.cancelled.value
    assert refreshed.application_target_status == ApplicationTargetStatus.resolved.value
    assert refreshed.application_target_url == GREENHOUSE_URL
    assert refreshed.application_target_metadata["application_form_detected"] is True
    db.close()
