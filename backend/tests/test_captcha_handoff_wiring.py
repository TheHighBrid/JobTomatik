import asyncio

from app.celery_app import celery_app
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import ManualHandoffSession
from app.models.job import Job
from app.models.user import User
from app.services import form_filler
from app.services.handoff_integration import _attach_handoff_session


def test_dry_run_always_uses_retainable_browser(monkeypatch):
    calls = []

    async def retained(*args, **kwargs):
        calls.append(("retained", args, kwargs))
        return {"runner": "retained"}

    async def standard(*args, **kwargs):
        calls.append(("standard", args, kwargs))
        return {"runner": "standard"}

    monkeypatch.setattr(form_filler, "fill_and_submit_application_with_handoff", retained)
    monkeypatch.setattr(form_filler, "fill_and_submit_application_standard", standard)
    monkeypatch.setattr(form_filler, "resumable_handoffs_enabled", lambda: False)

    result = asyncio.run(form_filler.fill_and_submit_application(
        job_url="https://boards.greenhouse.io/example/jobs/123",
        user_profile={},
        cover_letter="",
        resume_path="resume.pdf",
        dry_run=True,
    ))

    assert result == {"runner": "retained"}
    assert [item[0] for item in calls] == ["retained"]


def test_non_dry_run_keeps_standard_runner_when_handoffs_disabled(monkeypatch):
    calls = []

    async def retained(*args, **kwargs):
        calls.append("retained")
        return {"runner": "retained"}

    async def standard(*args, **kwargs):
        calls.append("standard")
        return {"runner": "standard"}

    monkeypatch.setattr(form_filler, "fill_and_submit_application_with_handoff", retained)
    monkeypatch.setattr(form_filler, "fill_and_submit_application_standard", standard)
    monkeypatch.setattr(form_filler, "resumable_handoffs_enabled", lambda: False)

    result = asyncio.run(form_filler.fill_and_submit_application(
        "https://boards.greenhouse.io/example/jobs/123",
        {},
        "",
        "resume.pdf",
        False,
    ))

    assert result == {"runner": "standard"}
    assert calls == ["standard"]


def test_celery_worker_registers_handoff_resume_task_module():
    assert "app.tasks.handoffs" in tuple(celery_app.conf.include or ())
    assert celery_app.conf.task_routes["app.tasks.handoffs.*"] == {"queue": "applications"}


def test_snapshot_attaches_to_captcha_review_even_when_fallback_is_ambiguous(db_session):
    user = User(email="captcha-routing@example.com", hashed_password="not-used")
    job = Job(
        title="CAPTCHA Routing Role",
        company="Routing Company",
        url="https://boards.greenhouse.io/routing/jobs/123",
    )
    db_session.add_all([user, job])
    db_session.flush()

    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.needs_review.value,
        submission_idempotency_key=f"captcha-routing-{user.id}-{job.id}",
    )
    db_session.add(application)
    db_session.flush()

    ambiguous_review = ManualReviewTask(
        application_id=application.id,
        reason_code=ManualReviewReason.ambiguous_question.value,
        status=ManualReviewStatus.open.value,
        summary="A question needs an answer.",
        blocking_url=job.url,
    )
    captcha_review = ManualReviewTask(
        application_id=application.id,
        reason_code=ManualReviewReason.captcha_detected.value,
        status=ManualReviewStatus.open.value,
        summary="CAPTCHA requires a human.",
        blocking_url=job.url,
    )
    db_session.add_all([ambiguous_review, captcha_review])
    db_session.flush()

    result = {
        "dry_run": True,
        "ats_adapter": "greenhouse",
        "ats_adapter_version": "1.1.1",
        "review_items": [
            {"reason_code": ManualReviewReason.ambiguous_question.value},
            {"reason_code": ManualReviewReason.captcha_detected.value},
        ],
        "handoff_snapshot": {
            "browser_provider": "local_cdp",
            "browser_session_id": "captcha-browser-session",
            "browser_endpoint": "http://127.0.0.1:9777",
            "browser_node_id": "node-a",
            "browser_process_id": 12345,
            "browser_profile_path": "/tmp/captcha-handoff/profile",
            "active_page_hint": job.url,
            "current_url": job.url,
            "current_fingerprint": "captcha-fingerprint",
            "storage_state_path": "/tmp/captcha-handoff/storage.json",
            "storage_state_hash": "captcha-storage-hash",
            "screenshot_path": "/tmp/captcha-handoff/screenshot.png",
            "html_snapshot_path": "/tmp/captcha-handoff/page.html",
            "metadata": {"fields_filled": 20},
        },
    }

    _attach_handoff_session(
        db_session,
        application,
        result,
        ManualReviewReason.ambiguous_question,
    )
    db_session.commit()

    session = db_session.query(ManualHandoffSession).one()
    assert session.manual_review_id == captcha_review.id
    assert session.manual_review_id != ambiguous_review.id
    assert result["handoff_public_id"] == session.public_id
    assert "handoff_snapshot" not in result
