from app.config import Settings
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.supervised_platforms import (
    GREENHOUSE_PLATFORM_KEY,
    LEVER_PLATFORM_KEY,
    get_supervised_platform_policy,
    supervised_platform_keys,
)
from app.services.supervised_submission import SUPPORTED_PLATFORM
from app.tasks.applications import submit_application_task
from tests.conftest import TestingSessionLocal


LEVER_URL = "https://jobs.lever.co/safeco/12345678-1234-1234-1234-123456789abc/apply"


def _prepare_lever_application(auth_client, tmp_path):
    resume = tmp_path / "lever-registry-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nSynthetic registry safety resume\n")

    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").one()
    user.resume_path = str(resume)
    job = Job(
        external_id="supervised-registry-lever",
        title="Payments Risk Analyst",
        company="SafeCo",
        url=LEVER_URL,
        source=JobSource.manual,
        status=JobStatus.approved,
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": LEVER_URL,
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id
    db.close()

    response = auth_client.post(
        "/api/applications",
        json={
            "job_id": job_id,
            "cover_letter": "Synthetic registry safety cover letter.",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_supervised_platform_registry_preserves_greenhouse_contract():
    policy = get_supervised_platform_policy("greenhouse")

    assert policy is not None
    assert policy.key == GREENHOUSE_PLATFORM_KEY
    assert policy.display_name == "Greenhouse"
    assert policy.adapter_version == "1.1.1"
    assert policy.pilot_setting_name == "greenhouse_supervised_pilot_enabled"
    assert policy.pilot_disabled_blocker == "greenhouse_supervised_pilot_disabled"
    assert policy.requires_exact_target_identity is False
    assert SUPPORTED_PLATFORM == GREENHOUSE_PLATFORM_KEY


def test_registry_recognizes_lever_but_keeps_other_platforms_unsupported():
    assert supervised_platform_keys() == ("greenhouse", "lever")
    lever = get_supervised_platform_policy("lever")
    assert lever is not None
    assert lever.key == LEVER_PLATFORM_KEY
    assert lever.display_name == "Lever"
    assert lever.adapter_version == "1.1.0"
    assert lever.pilot_setting_name == "lever_supervised_pilot_enabled"
    assert lever.pilot_disabled_blocker == "lever_supervised_pilot_disabled"
    assert lever.requires_exact_target_identity is True
    assert get_supervised_platform_policy("ashby") is None
    assert get_supervised_platform_policy("smartrecruiters") is None
    assert get_supervised_platform_policy("workday") is None
    assert get_supervised_platform_policy("generic") is None


def test_platform_pilot_settings_remain_disabled_by_default():
    settings = Settings(_env_file=None)

    greenhouse = get_supervised_platform_policy("greenhouse")
    lever = get_supervised_platform_policy("lever")
    assert greenhouse is not None
    assert lever is not None
    assert greenhouse.pilot_enabled(settings) is False
    assert lever.pilot_enabled(settings) is False


def test_registered_lever_live_worker_still_requires_exact_approval(
    auth_client,
    tmp_path,
):
    app_id = _prepare_lever_application(auth_client, tmp_path)

    result = submit_application_task.run(app_id, dry_run=False)

    assert result["success"] is False
    assert result["platform"] == "lever"
    assert result["supervised_platform_supported"] is True
    assert result["approval_required"] is True
    assert "exact-payload approval" in result["error"]

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).one()
    assert application.automation_state == ApplicationAutomationState.ready_to_apply.value
    assert application.submission_attempt_count == 0
    events = db.query(ApplicationEvent).filter(
        ApplicationEvent.application_id == app_id,
        ApplicationEvent.event_type == "supervised_submission_blocked",
    ).all()
    assert len(events) == 1
    assert events[0].payload["platform"] == "lever"
    db.close()
