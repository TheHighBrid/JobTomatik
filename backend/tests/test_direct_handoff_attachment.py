from tests.conftest import TestingSessionLocal

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ManualReviewTask,
)
from app.models.handoff import ManualHandoffSession
from app.models.job import Job, JobSource, JobStatus


def _create_ready_application(auth_client, *, external_id: str, title: str, url: str) -> tuple[int, int]:
    db = TestingSessionLocal()
    job = Job(
        title=title,
        company="Example Company",
        status=JobStatus.approved,
        source=JobSource.indeed,
        external_id=external_id,
        relevance_score=0.9,
        url=url,
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": url,
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id
    db.close()

    app_id = auth_client.post("/api/applications", json={"job_id": job_id}).json()["id"]

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).first()
    application.automation_state = ApplicationAutomationState.ready_to_apply.value
    db.commit()
    db.close()
    return app_id, job_id


def _patch_external_method(monkeypatch):
    monkeypatch.setattr("app.tasks.applications.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        "app.tasks.applications._ensure_application_method",
        lambda current_job: {
            "application_method": "external_url",
            "selected_apply_url": current_job.url,
        },
    )


def test_application_task_attaches_retained_handoff_without_worker_bootstrap(
    auth_client,
    monkeypatch,
):
    job_url = "https://boards.greenhouse.io/example/jobs/123"
    app_id, _job_id = _create_ready_application(
        auth_client,
        external_id="direct-handoff-attachment",
        title="Retained CAPTCHA Role",
        url=job_url,
    )
    _patch_external_method(monkeypatch)

    async def fake_fill_and_submit_application(**_kwargs):
        return {
            "success": False,
            "dry_run": True,
            "url": job_url,
            "application_url": job_url,
            "error": "CAPTCHA requires manual completion.",
            "requires_manual_review": True,
            "fields_filled": 20,
            "review_items": [{"reason_code": "captcha_detected"}],
            "log": [{"action": "browser_handoff_retained"}],
            "handoff_snapshot": {
                "browser_provider": "local_cdp",
                "browser_session_id": "direct-session",
            },
        }

    monkeypatch.setattr(
        "app.tasks.applications.fill_and_submit_application",
        fake_fill_and_submit_application,
    )

    calls = []

    def fake_attach(db, app, result, reason_code):
        calls.append((app.id, reason_code.value, result["handoff_snapshot"]["browser_session_id"]))
        result["handoff_public_id"] = "direct-public-id"
        result.pop("handoff_snapshot", None)

    monkeypatch.setattr("app.tasks.applications._attach_handoff_session", fake_attach)

    from app.tasks.applications import submit_application_task

    result = submit_application_task.run(app_id, dry_run=True)

    assert calls == [(app_id, "captcha_detected", "direct-session")]
    assert result["handoff_public_id"] == "direct-public-id"
    assert "handoff_snapshot" not in result

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).first()
    assert application.automation_state == ApplicationAutomationState.needs_review.value
    db.close()


def test_successful_dry_run_reaches_ready_to_apply_without_review_or_handoff(
    auth_client,
    monkeypatch,
):
    """Task-layer invariant for the exact premature-handoff failure class.

    The real-browser acceptance suite proves LinkedIn Apply navigation and ATS form
    filling return a successful, review-free dry-run result. This test proves the
    worker/task integration cannot reinterpret that ordinary success as a manual
    review or retained-browser handoff.
    """
    linkedin_url = "https://www.linkedin.com/jobs/view/4442675569"
    greenhouse_url = "https://job-boards.greenhouse.io/affirm/jobs/7806920003"
    app_id, _job_id = _create_ready_application(
        auth_client,
        external_id="premature-handoff-task-layer",
        title="Senior Machine Learning Engineer (Fraud)",
        url=linkedin_url,
    )
    _patch_external_method(monkeypatch)

    async def fake_successful_filled_dry_run(**_kwargs):
        return {
            "success": True,
            "dry_run": True,
            "ready_to_submit": True,
            "url": linkedin_url,
            "application_url": greenhouse_url,
            "application_form_detected": True,
            "ats_adapter": "greenhouse",
            "error": None,
            "requires_manual_review": False,
            "fields_filled": 6,
            "review_items": [],
            "log": [
                {"action": "application_entry_resolved"},
                {"action": "ats_final_submit_ready"},
            ],
            "handoff_snapshot": None,
        }

    monkeypatch.setattr(
        "app.tasks.applications.fill_and_submit_application",
        fake_successful_filled_dry_run,
    )

    def unexpected_attach(*_args, **_kwargs):
        raise AssertionError("A successful ordinary dry run must never attach a handoff")

    monkeypatch.setattr("app.tasks.applications._attach_handoff_session", unexpected_attach)

    from app.tasks.applications import submit_application_task

    result = submit_application_task.run(app_id, dry_run=True)

    assert result["success"] is True
    assert result["ready_to_submit"] is True
    assert result["requires_manual_review"] is False
    assert result["application_url"] == greenhouse_url

    db = TestingSessionLocal()
    try:
        application = db.query(Application).filter(Application.id == app_id).one()
        assert application.status.value == "pending"
        assert application.automation_state == ApplicationAutomationState.ready_to_apply.value
        assert (
            db.query(ManualReviewTask)
            .filter(ManualReviewTask.application_id == app_id)
            .count()
            == 0
        )
        assert (
            db.query(ManualHandoffSession)
            .filter(ManualHandoffSession.application_id == app_id)
            .count()
            == 0
        )
    finally:
        db.close()
