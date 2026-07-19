from tests.conftest import TestingSessionLocal

from app.models.application import Application, ApplicationAutomationState
from app.models.job import Job, JobSource, JobStatus


def test_application_task_attaches_retained_handoff_without_worker_bootstrap(
    auth_client,
    monkeypatch,
):
    db = TestingSessionLocal()
    job = Job(
        title="Retained CAPTCHA Role",
        company="Example Company",
        status=JobStatus.approved,
        source=JobSource.indeed,
        external_id="direct-handoff-attachment",
        relevance_score=0.9,
        url="https://boards.greenhouse.io/example/jobs/123",
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": "https://boards.greenhouse.io/example/jobs/123",
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.close()

    app_id = auth_client.post("/api/applications", json={"job_id": job.id}).json()["id"]

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).first()
    application.automation_state = ApplicationAutomationState.ready_to_apply.value
    db.commit()
    db.close()

    monkeypatch.setattr("app.tasks.applications.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        "app.tasks.applications._ensure_application_method",
        lambda current_job: {
            "application_method": "external_url",
            "selected_apply_url": current_job.url,
        },
    )

    async def fake_fill_and_submit_application(**_kwargs):
        return {
            "success": False,
            "dry_run": True,
            "url": job.url,
            "application_url": job.url,
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
