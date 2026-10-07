"""Regression coverage for the fail-closed GH-OH1 readiness endpoint."""

from app.models.application import Application, ApplicationAutomationState, ApplicationEvent
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services.operations_settings import get_operations_settings


CANDIDATE = {
    "employer": "Example Employer",
    "role": "Support Engineer",
    "application_url": "https://job-boards.greenhouse.io/example/jobs/1234567",
    "location": "Remote, Canada",
    "source_reference": "gh-oh1-test",
}


def _ready_application(auth_client, db_session, tmp_path):
    response = auth_client.post("/api/supervised-pilot/candidates", json=CANDIDATE)
    assert response.status_code == 200
    application_id = response.json()["application_id"]

    user = db_session.query(User).filter(User.email == "test@example.com").one()
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"synthetic resume")
    user.resume_path = str(resume)

    application = db_session.query(Application).filter(
        Application.id == application_id
    ).one()
    application.automation_state = ApplicationAutomationState.ready_to_apply.value
    application.cover_letter = "Synthetic reviewed cover letter."

    db_session.add_all([user, application])
    db_session.commit()
    return application


def _onehost_runtime(monkeypatch):
    from app.services import greenhouse_oh1_preflight as preflight

    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "onehost")
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", "a" * 40)
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", "a" * 40)
    monkeypatch.setenv("AUTOMATION_GLOBAL_KILL_SWITCH", "false")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    get_operations_settings.cache_clear()

    monkeypatch.setattr(preflight.get_settings(), "application_browser_provider", "local")
    monkeypatch.setattr(preflight.get_settings(), "application_browser_cdp_endpoint", "")
    monkeypatch.setattr(preflight.get_settings(), "jobtomatik_browser_node_id", "onehost-primary")
    monkeypatch.setattr(preflight.get_settings(), "application_browser_profile_dir", "/state/browser-profile")
    monkeypatch.setattr(preflight.get_settings(), "handoff_storage_dir", "/state/handoffs")
    monkeypatch.setattr(preflight.get_settings(), "enable_resumable_handoffs", True)
    monkeypatch.setattr(preflight.get_settings(), "allow_real_application_submit", False)
    monkeypatch.setattr(preflight.get_settings(), "greenhouse_supervised_pilot_enabled", False)


def test_gh_oh1_preflight_reports_ready_without_mutating_execution(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    application = _ready_application(auth_client, db_session, tmp_path)
    _onehost_runtime(monkeypatch)

    events_before = db_session.query(ApplicationEvent).count()
    approvals_before = db_session.query(SubmissionApproval).count()
    attempts_before = db_session.query(SubmissionAttempt).count()

    response = auth_client.get(
        f"/api/supervised-pilot/applications/{application.id}/gh-oh1-preflight"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY FOR SUPERVISED EXECUTION"
    assert payload["ready"] is True
    assert payload["blockers"] == []
    assert payload["duplicate_defense"]["submission_idempotency_key_present"] is True
    assert payload["runtime_contract"]["runtime_mode"] == "onehost"
    assert payload["runtime_contract"]["browser_provider"] == "local"
    assert payload["safety_boundary"]["read_only"] is True
    assert payload["safety_boundary"]["browser_started"] is False
    assert payload["safety_boundary"]["submission_queued"] is False
    assert payload["safety_boundary"]["final_action_authorized"] is False

    assert db_session.query(ApplicationEvent).count() == events_before
    assert db_session.query(SubmissionApproval).count() == approvals_before
    assert db_session.query(SubmissionAttempt).count() == attempts_before

    get_operations_settings.cache_clear()


def test_gh_oh1_preflight_blocks_unsafe_runtime_flags(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    application = _ready_application(auth_client, db_session, tmp_path)
    _onehost_runtime(monkeypatch)

    from app.services import greenhouse_oh1_preflight as preflight

    monkeypatch.setattr(preflight.get_settings(), "allow_real_application_submit", True)
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    get_operations_settings.cache_clear()

    response = auth_client.get(
        f"/api/supervised-pilot/applications/{application.id}/gh-oh1-preflight"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "BLOCKED"
    assert "real_submit_flag_open_before_final_action_boundary" in payload["blockers"]
    assert "autopilot_must_be_disabled_for_gh_oh1" in payload["blockers"]

    get_operations_settings.cache_clear()


def test_gh_oh1_preflight_blocks_prior_attempt_history(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    application = _ready_application(auth_client, db_session, tmp_path)
    _onehost_runtime(monkeypatch)
    application.submission_attempt_count = 1
    db_session.add(application)
    db_session.commit()

    response = auth_client.get(
        f"/api/supervised-pilot/applications/{application.id}/gh-oh1-preflight"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is False
    assert "prior_submission_attempt_recorded" in payload["blockers"]

    get_operations_settings.cache_clear()


def test_gh_oh1_preflight_requires_authentication(client):
    response = client.get(
        "/api/supervised-pilot/applications/1/gh-oh1-preflight"
    )
    assert response.status_code == 401
