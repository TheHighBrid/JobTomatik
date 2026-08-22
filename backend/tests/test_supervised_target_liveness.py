from types import SimpleNamespace

import httpx
import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services import supervised_submission as approval_service
from app.services.supervised_submission import SupervisedSubmissionApprovalError


LIVE_URL = "https://job-boards.greenhouse.io/example/jobs/123456"
CLOSED_URL = "https://job-boards.greenhouse.io/example?error=true"


def _selected_application(db_session, tmp_path):
    resume = tmp_path / "phase-b-liveness-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nPhase B target liveness regression\n")
    user = User(
        email="phase-b-liveness@example.test",
        hashed_password="not-used",
        full_name="Phase B Liveness Operator",
        resume_path=str(resume),
        profile_data={},
    )
    db_session.add(user)
    db_session.flush()

    job = Job(
        external_id="phase-b-liveness-job",
        title="Compliance Analyst",
        company="Example",
        url=LIVE_URL,
        source=JobSource.manual,
        status=JobStatus.queued,
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": LIVE_URL,
            "selection_source": approval_service.MANUAL_GREENHOUSE_PHASE_B_SOURCE,
            "selection_policy": "user_selected_exact_application",
        },
    )
    db_session.add(job)
    db_session.flush()

    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        submission_idempotency_key=f"greenhouse-phase-b:{user.id}:liveness",
        cover_letter="Source-backed supervised Phase B cover letter.",
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(job)
    db_session.refresh(application)
    return application, user, job


def _enable_production_pilot(monkeypatch):
    monkeypatch.setattr(approval_service.settings, "app_environment", "production")
    monkeypatch.setattr(
        approval_service.settings,
        "allow_real_application_submit",
        True,
    )
    monkeypatch.setattr(
        approval_service.settings,
        "greenhouse_supervised_pilot_enabled",
        True,
    )


def _stable_verified_form_schema(monkeypatch):
    """Keep liveness regressions focused on URL state, not schema transport."""

    monkeypatch.setattr(
        approval_service,
        "_greenhouse_form_schema_status",
        lambda _url: {
            "checked": True,
            "verified": True,
            "status_code": 200,
            "board_token": "example",
            "job_id": "123456",
            "schema_hash": "a" * 64,
            "fingerprint_version": approval_service.FORM_SCHEMA_FINGERPRINT_VERSION,
            "question_count": 1,
            "required_question_count": 1,
            "required_uploads": ["Resume"],
            "unsupported_fields": [],
            "blocker": None,
        },
    )


def test_greenhouse_target_liveness_accepts_same_exact_job(monkeypatch):
    monkeypatch.setattr(
        approval_service.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            url=LIVE_URL,
        ),
    )

    result = approval_service._greenhouse_target_liveness(LIVE_URL)

    assert result["checked"] is True
    assert result["live"] is True
    assert result["blocker"] is None
    assert result["status_code"] == 200
    assert result["final_url"] == LIVE_URL


def test_greenhouse_target_liveness_blocks_closed_board_redirect(monkeypatch):
    monkeypatch.setattr(
        approval_service.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            url=CLOSED_URL,
        ),
    )

    result = approval_service._greenhouse_target_liveness(LIVE_URL)

    assert result["checked"] is True
    assert result["live"] is False
    assert result["blocker"] == "application_target_closed_or_expired"


def test_greenhouse_target_liveness_fails_closed_when_network_is_unverified(
    monkeypatch,
):
    def fail_request(*args, **kwargs):
        request = httpx.Request("GET", LIVE_URL)
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr(approval_service.httpx, "get", fail_request)

    result = approval_service._greenhouse_target_liveness(LIVE_URL)

    assert result["checked"] is True
    assert result["live"] is False
    assert result["blocker"] == "application_target_liveness_unverified"


def test_liveness_probe_is_scoped_to_production_manual_greenhouse_phase_b(
    monkeypatch,
):
    job = Job(
        external_id="phase-b-liveness",
        title="Compliance Analyst",
        company="Example",
        url=LIVE_URL,
        raw_data={
            "selection_source": approval_service.MANUAL_GREENHOUSE_PHASE_B_SOURCE,
        },
    )

    monkeypatch.setattr(approval_service.settings, "app_environment", "production")
    assert approval_service._should_probe_target_liveness(job, "greenhouse") is True

    monkeypatch.setattr(approval_service.settings, "app_environment", "test")
    assert approval_service._should_probe_target_liveness(job, "greenhouse") is False

    monkeypatch.setattr(approval_service.settings, "app_environment", "production")
    assert approval_service._should_probe_target_liveness(job, "lever") is False

    job.raw_data = {"selection_source": "manual"}
    assert approval_service._should_probe_target_liveness(job, "greenhouse") is False


def test_supervised_preflight_blocks_closed_selected_greenhouse_target(
    db_session,
    tmp_path,
    monkeypatch,
):
    application, user, job = _selected_application(db_session, tmp_path)
    _enable_production_pilot(monkeypatch)
    _stable_verified_form_schema(monkeypatch)
    monkeypatch.setattr(
        approval_service.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200, url=CLOSED_URL),
    )

    preflight = approval_service.build_supervised_preflight(
        db_session,
        application,
        user,
        job,
    )

    assert preflight["ready"] is False
    assert preflight["target_liveness"]["checked"] is True
    assert preflight["target_liveness"]["live"] is False
    assert "application_target_closed_or_expired" in preflight["blockers"]


def test_approval_validation_rechecks_target_liveness_before_consume(
    db_session,
    tmp_path,
    monkeypatch,
):
    application, user, job = _selected_application(db_session, tmp_path)
    _enable_production_pilot(monkeypatch)
    _stable_verified_form_schema(monkeypatch)
    target_state = {"url": LIVE_URL}
    monkeypatch.setattr(
        approval_service.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            url=target_state["url"],
        ),
    )

    approval = approval_service.issue_supervised_approval(
        db_session,
        application,
        user,
        job,
        confirm_employer="Example",
        confirm_role="Compliance Analyst",
        confirm_application_url=LIVE_URL,
        confirm_final_submit=True,
        expires_in_minutes=20,
    )
    db_session.commit()
    assert approval.status == "active"

    target_state["url"] = CLOSED_URL
    with pytest.raises(
        SupervisedSubmissionApprovalError,
        match="application_target_closed_or_expired",
    ):
        approval_service.validate_supervised_approval(
            db_session,
            application,
            user,
            job,
            reference=approval.reference,
            consume=True,
        )

    db_session.refresh(approval)
    assert approval.status == "active"
    assert approval.consumed_at is None
