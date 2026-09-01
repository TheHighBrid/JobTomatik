from app.models.application import Application, ApplicationAutomationState, SubmissionEvidence
from app.models.job import Job, JobSource, JobStatus
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services import operator_assisted_submission as operator_service
from app.services import supervised_submission as approval_service
from tests.conftest import TestingSessionLocal


POSTING_ID = "12345678-1234-1234-1234-123456789abc"
LEVER_URL = f"https://jobs.lever.co/safeco/{POSTING_ID}/apply"
CONFIRMATION_URL = "https://jobs.lever.co/safeco/thank-you"


def _valid_metadata():
    return {
        "platform": "lever",
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "verified": True,
        "blockers": [],
        "target_url": LEVER_URL,
        "canonical_application_url": LEVER_URL,
        "site": "safeco",
        "posting_id": POSTING_ID,
        "region": "global",
        "official_title": "Payments Risk Analyst",
        "title_matches_local_job": True,
        "posting_metadata_hash": "a" * 64,
        "identity_hash": "b" * 64,
        "verification_error": None,
        "verified_at": "2026-09-01T20:00:00",
    }


def _mock_metadata(monkeypatch):
    async def resolved(_job):
        return _valid_metadata()

    monkeypatch.setattr(
        "app.api.supervised_submissions.resolve_supervised_target_metadata",
        resolved,
    )


def _keep_automation_off(monkeypatch):
    monkeypatch.setattr(approval_service.settings, "allow_real_application_submit", False)
    monkeypatch.setattr(approval_service.settings, "lever_supervised_pilot_enabled", False)
    monkeypatch.setattr(operator_service.settings, "autopilot_enabled", False)


def _prepare_application(auth_client, tmp_path):
    resume = tmp_path / "operator-assisted-lever.pdf"
    resume.write_bytes(b"%PDF-1.4\nOperator assisted Lever resume\n")

    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").one()
    user.resume_path = str(resume)
    user.phone = "+1 613 555 0101"
    job = Job(
        external_id="operator-assisted-lever",
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
            "cover_letter": "Exact operator-assisted Lever cover letter.",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _approval_payload():
    return {
        "confirm_employer": "SafeCo",
        "confirm_role": "Payments Risk Analyst",
        "confirm_application_url": LEVER_URL,
        "confirm_operator_final_click": True,
        "expires_in_minutes": 20,
        "notes": "Owner will make the final click directly on Lever.",
    }


def test_operator_assisted_preflight_requires_automation_to_remain_off(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path)
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)

    response = auth_client.get(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/preflight"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is True
    assert data["platform"] == "lever"
    assert data["global_live_submit_enabled"] is False
    assert data["platform_pilot_enabled"] is False
    assert data["autopilot_enabled"] is False
    assert data["operator_final_click_required"] is True
    assert data["automated_submission_authorized"] is False
    assert data["queue_submission_authorized"] is False
    assert "global_live_submit_disabled" not in data["blockers"]
    assert "lever_supervised_pilot_disabled" not in data["blockers"]

    monkeypatch.setattr(approval_service.settings, "allow_real_application_submit", True)
    blocked = auth_client.get(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/preflight"
    )
    assert blocked.status_code == 200
    assert blocked.json()["ready"] is False
    assert "operator_assisted_requires_global_submit_disabled" in blocked.json()["blockers"]


def test_operator_final_click_authorization_never_queues_worker_work(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path)
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)

    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals",
        json=_approval_payload(),
    )
    assert created.status_code == 201
    approval = created.json()
    reference = approval["reference"]
    assert reference.startswith("lvsup-")
    assert approval["status"] == SubmissionApprovalStatus.active.value
    assert approval["approval_metadata"]["operator_final_click_required"] is True
    assert approval["approval_metadata"]["automated_submission_authorized"] is False
    assert approval["approval_metadata"]["queue_submission_authorized"] is False

    authorized = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals/{reference}/authorize-final-click"
    )
    assert authorized.status_code == 200
    data = authorized.json()
    assert data["status"] == SubmissionApprovalStatus.consumed.value
    assert data["operator_final_click_required"] is True
    assert data["worker_task_created"] is False
    assert data["queue_created"] is False
    assert data["automated_submission_authorized"] is False

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).one()
    persisted = db.query(SubmissionApproval).filter(SubmissionApproval.reference == reference).one()
    attempts = db.query(SubmissionAttempt).filter(SubmissionAttempt.application_id == app_id).all()
    assert application.automation_state == ApplicationAutomationState.applying.value
    assert application.submission_attempt_count == 1
    assert persisted.status == SubmissionApprovalStatus.consumed.value
    assert attempts == []
    db.close()


def test_operator_confirmation_enters_existing_independent_review_pipeline(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path)
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)

    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals",
        json=_approval_payload(),
    )
    assert created.status_code == 201
    reference = created.json()["reference"]
    authorized = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals/{reference}/authorize-final-click"
    )
    assert authorized.status_code == 200

    recorded = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals/{reference}/confirmation",
        json={
            "confirm_submission_completed": True,
            "evidence_type": "confirmation_page",
            "final_url": CONFIRMATION_URL,
            "confirmation_text": "Thank you for applying",
            "notes": "Owner observed Lever confirmation after making the final click.",
        },
    )
    assert recorded.status_code == 200
    evidence_id = recorded.json()["evidence_id"]
    assert recorded.json()["automation_state"] == ApplicationAutomationState.submitted.value
    assert recorded.json()["independent_review_required"] is True
    assert recorded.json()["phase_b_credit_granted"] is False

    preflight = auth_client.get(
        f"/api/applications/{app_id}/evidence/{evidence_id}/review-preflight"
    )
    assert preflight.status_code == 200
    review_data = preflight.json()
    assert review_data["ready_for_acceptance"] is True
    assert review_data["blockers"] == []
    assert review_data["approval_reference"] == reference

    db = TestingSessionLocal()
    evidence = db.query(SubmissionEvidence).filter(SubmissionEvidence.id == evidence_id).one()
    assert evidence.payload_hash
    assert evidence.evidence_metadata["approval_reference"] == reference
    assert evidence.evidence_metadata["platform"] == "lever"
    assert evidence.evidence_metadata["adapter"] == "lever"
    assert evidence.evidence_metadata["adapter_version"] == "1.1.0"
    db.close()


def test_operator_confirmation_rejects_weak_or_unconfirmed_claims(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path)
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)

    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals",
        json=_approval_payload(),
    )
    reference = created.json()["reference"]
    auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals/{reference}/authorize-final-click"
    )

    not_confirmed = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals/{reference}/confirmation",
        json={
            "confirm_submission_completed": False,
            "evidence_type": "confirmation_page",
            "final_url": CONFIRMATION_URL,
            "confirmation_text": "Thank you for applying",
        },
    )
    assert not_confirmed.status_code == 409

    weak = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals/{reference}/confirmation",
        json={
            "confirm_submission_completed": True,
            "evidence_type": "screenshot",
            "final_url": CONFIRMATION_URL,
            "confirmation_text": "looks submitted",
        },
    )
    assert weak.status_code == 409
