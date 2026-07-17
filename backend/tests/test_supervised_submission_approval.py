from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.submission_approval import (
    SubmissionApproval,
    SubmissionApprovalStatus,
)
from app.models.user import User
from app.services import supervised_submission as approval_service
from app.services.supervised_submission import (
    SupervisedSubmissionApprovalError,
    validate_supervised_approval,
)
from app.tasks.applications import submit_application_task
from tests.conftest import TestingSessionLocal


GREENHOUSE_URL = "https://job-boards.greenhouse.io/safeco/jobs/123456"


def _prepare_application(auth_client, tmp_path, *, suffix="base"):
    resume = tmp_path / f"resume-{suffix}.pdf"
    resume.write_bytes(b"%PDF-1.4\nSynthetic supervised pilot resume\n")

    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").one()
    user.resume_path = str(resume)
    user.phone = "+1 613 555 0101"
    user.profile_data = {"languages": ["English", "French"]}
    job = Job(
        external_id=f"supervised-{suffix}",
        title="Fraud Operations Analyst",
        company="SafeCo",
        url=GREENHOUSE_URL,
        source=JobSource.manual,
        status=JobStatus.approved,
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": GREENHOUSE_URL,
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
            "cover_letter": "Exact supervised pilot cover letter.",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _enable_pilot(monkeypatch):
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


def _approval_payload():
    return {
        "confirm_employer": "SafeCo",
        "confirm_role": "Fraud Operations Analyst",
        "confirm_application_url": GREENHOUSE_URL,
        "confirm_final_submit": True,
        "expires_in_minutes": 20,
        "notes": "Explicit per-application supervised pilot approval.",
    }


def test_preflight_fails_closed_until_both_feature_flags_are_enabled(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path, suffix="flags")

    blocked = auth_client.get(
        f"/api/supervised-submissions/applications/{app_id}/preflight"
    )
    assert blocked.status_code == 200
    assert blocked.json()["ready"] is False
    assert "global_live_submit_disabled" in blocked.json()["blockers"]
    assert "greenhouse_supervised_pilot_disabled" in blocked.json()["blockers"]

    _enable_pilot(monkeypatch)
    ready = auth_client.get(
        f"/api/supervised-submissions/applications/{app_id}/preflight"
    )
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert ready.json()["platform"] == "greenhouse"
    assert ready.json()["resume_hash"]
    assert ready.json()["combined_payload_hash"]


def test_approval_is_exact_short_lived_and_contains_hashes_not_answers(
    auth_client,
    tmp_path,
    monkeypatch,
):
    _enable_pilot(monkeypatch)
    app_id = _prepare_application(auth_client, tmp_path, suffix="exact")

    mismatch = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json={**_approval_payload(), "confirm_employer": "Wrong Employer"},
    )
    assert mismatch.status_code == 409
    assert "employer" in mismatch.json()["detail"]

    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json=_approval_payload(),
    )
    assert created.status_code == 201
    data = created.json()
    assert data["reference"].startswith("ghsup-")
    assert data["status"] == SubmissionApprovalStatus.active.value
    assert data["employer"] == "SafeCo"
    assert data["role"] == "Fraud Operations Analyst"
    assert len(data["profile_snapshot_hash"]) == 64
    assert len(data["resume_hash"]) == 64
    assert len(data["cover_letter_hash"]) == 64
    assert len(data["answer_payload_hash"]) == 64
    assert len(data["combined_payload_hash"]) == 64
    serialized = str(data).lower()
    assert "613 555 0101" not in serialized
    assert "exact supervised pilot cover letter" not in serialized
    assert "browser_endpoint" not in serialized
    assert "resume_token" not in serialized


def test_payload_mutation_revokes_approval_before_queueing(
    auth_client,
    tmp_path,
    monkeypatch,
):
    _enable_pilot(monkeypatch)
    app_id = _prepare_application(auth_client, tmp_path, suffix="mutation")
    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json=_approval_payload(),
    )
    reference = created.json()["reference"]

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).one()
    application.cover_letter = "Changed after approval."
    db.commit()
    db.close()

    queued = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals/{reference}/submit"
    )
    assert queued.status_code == 409
    assert "payload changed" in queued.json()["detail"].lower()

    db = TestingSessionLocal()
    approval = db.query(SubmissionApproval).filter(
        SubmissionApproval.reference == reference
    ).one()
    assert approval.status == SubmissionApprovalStatus.revoked.value
    assert "cover_letter_hash" in approval.approval_metadata["mismatched_fields"]
    db.close()


def test_open_manual_review_blocks_approval(
    auth_client,
    tmp_path,
    monkeypatch,
):
    _enable_pilot(monkeypatch)
    app_id = _prepare_application(auth_client, tmp_path, suffix="review")

    db = TestingSessionLocal()
    db.add(ManualReviewTask(
        application_id=app_id,
        reason_code=ManualReviewReason.legal_answer_missing.value,
        status=ManualReviewStatus.open.value,
        summary="A legal answer still requires explicit user policy.",
    ))
    db.commit()
    db.close()

    preflight = auth_client.get(
        f"/api/supervised-submissions/applications/{app_id}/preflight"
    )
    assert preflight.json()["ready"] is False
    assert "unresolved_manual_reviews" in preflight.json()["blockers"]

    response = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json=_approval_payload(),
    )
    assert response.status_code == 409


def test_consumption_is_one_time_and_expired_approvals_fail_closed(
    auth_client,
    tmp_path,
    monkeypatch,
):
    _enable_pilot(monkeypatch)
    app_id = _prepare_application(auth_client, tmp_path, suffix="consume")
    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json=_approval_payload(),
    )
    reference = created.json()["reference"]

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).one()
    user = db.query(User).filter(User.id == application.user_id).one()
    job = db.query(Job).filter(Job.id == application.job_id).one()
    approval = validate_supervised_approval(
        db,
        application,
        user,
        job,
        reference=reference,
        consume=True,
    )
    db.commit()
    assert approval.status == SubmissionApprovalStatus.consumed.value
    with pytest.raises(SupervisedSubmissionApprovalError, match="not active"):
        validate_supervised_approval(
            db,
            application,
            user,
            job,
            reference=reference,
            consume=True,
        )
    db.rollback()
    db.close()

    second = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json=_approval_payload(),
    )
    second_reference = second.json()["reference"]
    db = TestingSessionLocal()
    approval = db.query(SubmissionApproval).filter(
        SubmissionApproval.reference == second_reference
    ).one()
    approval.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    db.close()

    expired = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals/{second_reference}/submit"
    )
    assert expired.status_code == 409
    assert "expired" in expired.json()["detail"].lower()


def test_direct_greenhouse_live_worker_call_without_approval_is_blocked(
    auth_client,
    tmp_path,
    monkeypatch,
):
    _enable_pilot(monkeypatch)
    app_id = _prepare_application(auth_client, tmp_path, suffix="worker")

    result = submit_application_task.run(app_id, dry_run=False)
    assert result["success"] is False
    assert result["approval_required"] is True

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).one()
    assert application.automation_state == ApplicationAutomationState.ready_to_apply.value
    assert application.submission_attempt_count == 0
    events = db.query(ApplicationEvent).filter(
        ApplicationEvent.application_id == app_id,
        ApplicationEvent.event_type == "supervised_submission_blocked",
    ).all()
    assert len(events) == 1
    db.close()


def test_approved_submit_endpoint_queues_reference_without_consuming_it(
    auth_client,
    tmp_path,
    monkeypatch,
):
    _enable_pilot(monkeypatch)
    app_id = _prepare_application(auth_client, tmp_path, suffix="queue")
    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json=_approval_payload(),
    )
    reference = created.json()["reference"]

    fake_result = MagicMock(id="supervised-task-id")
    mock_task = MagicMock()
    mock_task.delay.return_value = fake_result
    monkeypatch.setattr(
        "app.api.supervised_submissions.submit_application_task",
        mock_task,
    )

    response = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals/{reference}/submit"
    )
    assert response.status_code == 200
    assert response.json()["task_id"] == "supervised-task-id"
    mock_task.delay.assert_called_once_with(
        app_id,
        dry_run=False,
        approval_reference=reference,
    )

    db = TestingSessionLocal()
    approval = db.query(SubmissionApproval).filter(
        SubmissionApproval.reference == reference
    ).one()
    assert approval.status == SubmissionApprovalStatus.active.value
    db.close()
