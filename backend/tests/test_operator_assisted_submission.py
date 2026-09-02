from types import SimpleNamespace

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ManualReviewReason,
)
from app.models.handoff import HandoffChallengeType, ManualHandoffSession
from app.models.job import Job, JobSource, JobStatus
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services import browser_handoff
from app.services import operator_assisted_submission as operator_service
from app.services import supervised_submission as approval_service
from app.services.application_state import create_manual_review_task
from app.services.handoff_session import issue_handoff_session
from app.services.operator_assisted_handoff_integration import (
    install_operator_assisted_handoff_integration,
)
from tests.conftest import TestingSessionLocal


POSTING_ID = "12345678-1234-1234-1234-123456789abc"
LEVER_URL = f"https://jobs.lever.co/safeco/{POSTING_ID}/apply"


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


def _create_final_submit_boundary(app_id: int) -> str:
    install_operator_assisted_handoff_integration()
    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).one()
    application.automation_state = ApplicationAutomationState.ready_to_apply.value
    review = create_manual_review_task(
        db,
        application,
        ManualReviewReason.operator_final_submit_required,
        "Review the filled Lever form and perform the final submit action.",
        details={
            "handoff_stage": "operator_final_submit",
            "operator_final_click_required": True,
            "submit_clicked": False,
        },
        blocking_url=LEVER_URL,
    )
    db.flush()
    issued = issue_handoff_session(
        db,
        application,
        review,
        browser_provider="local_cdp",
        browser_session_id="operator-assisted-test-browser",
        browser_endpoint="http://127.0.0.1:9222",
        current_url=LEVER_URL,
        current_fingerprint="fingerprint-before-submit",
        metadata={
            "dry_run": True,
            "adapter": "lever",
            "adapter_version": "1.1.0",
            "supervised_target": _valid_metadata(),
        },
    )
    public_id = issued.session.public_id
    db.commit()
    db.close()
    return public_id


def _approval_payload(handoff_public_id: str):
    return {
        "handoff_public_id": handoff_public_id,
        "confirm_employer": "SafeCo",
        "confirm_role": "Payments Risk Analyst",
        "confirm_application_url": LEVER_URL,
        "confirm_operator_final_click": True,
        "expires_in_minutes": 20,
        "notes": "Owner will trigger only the exact retained final Submit action.",
    }


def _authorize_and_claim(auth_client, app_id: int, handoff_public_id: str):
    bootstrapped = auth_client.post(f"/api/handoffs/{handoff_public_id}/bootstrap")
    assert bootstrapped.status_code == 200
    resume_token = bootstrapped.json()["resume_token"]

    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals",
        json=_approval_payload(handoff_public_id),
    )
    assert created.status_code == 201
    reference = created.json()["reference"]

    authorized = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals/{reference}/authorize-final-click"
    )
    assert authorized.status_code == 200

    claimed = auth_client.post(
        f"/api/handoffs/{handoff_public_id}/claim",
        json={"resume_token": resume_token},
    )
    assert claimed.status_code == 200
    return reference, claimed.json()["lease_token"]


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
    assert data["operator_final_submit_boundary"] is False
    assert "global_live_submit_disabled" not in data["blockers"]
    assert "lever_supervised_pilot_disabled" not in data["blockers"]

    monkeypatch.setattr(approval_service.settings, "allow_real_application_submit", True)
    blocked = auth_client.get(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/preflight"
    )
    assert blocked.status_code == 200
    assert blocked.json()["ready"] is False
    assert "operator_assisted_requires_global_submit_disabled" in blocked.json()["blockers"]


def test_prepare_endpoint_queues_only_dedicated_fill_and_retain_task(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path)
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)
    calls = []

    def fake_apply_async(*, args, queue):
        calls.append({"args": args, "queue": queue})
        return SimpleNamespace(id="operator-prepare-task-1")

    monkeypatch.setattr(
        "app.api.supervised_submissions.prepare_operator_assisted_application_task.apply_async",
        fake_apply_async,
    )

    response = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/prepare"
    )
    assert response.status_code == 202
    data = response.json()
    assert data["task_id"] == "operator-prepare-task-1"
    assert data["status"] == "preparing_retained_form"
    assert data["automated_submission_authorized"] is False
    assert data["final_submit_clicked_by_jobtomatik"] is False
    assert calls == [{"args": [app_id], "queue": "applications"}]


def test_final_boundary_is_allowed_but_cannot_be_claimed_before_exact_approval(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path)
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)
    handoff_public_id = _create_final_submit_boundary(app_id)

    preflight = auth_client.get(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/preflight"
    )
    assert preflight.status_code == 200
    data = preflight.json()
    assert data["ready"] is True
    assert data["automation_state"] == ApplicationAutomationState.needs_review.value
    assert data["unresolved_manual_review_count"] == 1
    assert data["operator_final_submit_boundary"] is True
    assert data["operator_handoff_public_id"] == handoff_public_id
    assert "application_not_ready_to_apply" not in data["blockers"]
    assert "unresolved_manual_reviews" not in data["blockers"]

    bootstrapped = auth_client.post(f"/api/handoffs/{handoff_public_id}/bootstrap")
    assert bootstrapped.status_code == 200
    resume_token = bootstrapped.json()["resume_token"]
    blocked_claim = auth_client.post(
        f"/api/handoffs/{handoff_public_id}/claim",
        json={"resume_token": resume_token},
    )
    assert blocked_claim.status_code == 409
    assert "Exact operator final-click approval is required" in blocked_claim.json()["detail"]


def test_exact_operator_authorization_unlocks_handoff_without_submission_attempt(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path)
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)
    handoff_public_id = _create_final_submit_boundary(app_id)

    bootstrapped = auth_client.post(f"/api/handoffs/{handoff_public_id}/bootstrap")
    resume_token = bootstrapped.json()["resume_token"]

    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals",
        json=_approval_payload(handoff_public_id),
    )
    assert created.status_code == 201
    approval = created.json()
    reference = approval["reference"]
    assert reference.startswith("lvsup-")
    assert approval["status"] == SubmissionApprovalStatus.active.value
    assert approval["approval_metadata"]["handoff_public_id"] == handoff_public_id
    assert approval["approval_metadata"]["operator_final_click_required"] is True
    assert approval["approval_metadata"]["automated_submission_authorized"] is False
    assert approval["approval_metadata"]["queue_submission_authorized"] is False

    authorized = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals/{reference}/authorize-final-click"
    )
    assert authorized.status_code == 200
    data = authorized.json()
    assert data["status"] == SubmissionApprovalStatus.consumed.value
    assert data["handoff_public_id"] == handoff_public_id
    assert data["worker_task_created"] is False
    assert data["queue_created"] is False
    assert data["automated_submission_authorized"] is False

    claim = auth_client.post(
        f"/api/handoffs/{handoff_public_id}/claim",
        json={"resume_token": resume_token},
    )
    assert claim.status_code == 200
    assert claim.json()["session"]["challenge_type"] == HandoffChallengeType.final_submit.value

    db = TestingSessionLocal()
    application = db.query(Application).filter(Application.id == app_id).one()
    persisted = db.query(SubmissionApproval).filter(SubmissionApproval.reference == reference).one()
    attempts = db.query(SubmissionAttempt).filter(SubmissionAttempt.application_id == app_id).all()
    assert application.automation_state == ApplicationAutomationState.applying.value
    assert application.submission_attempt_count == 1
    assert persisted.status == SubmissionApprovalStatus.consumed.value
    assert attempts == []
    db.close()


def test_same_retained_form_cannot_consume_a_second_owner_approval(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path)
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)
    handoff_public_id = _create_final_submit_boundary(app_id)
    _authorize_and_claim(auth_client, app_id, handoff_public_id)

    duplicate = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/approvals",
        json=_approval_payload(handoff_public_id),
    )
    assert duplicate.status_code == 409
    assert "second approval is forbidden" in duplicate.json()["detail"].lower()


def test_operator_final_action_is_checkpointed_before_external_submit_and_never_replayed(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path)
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)
    handoff_public_id = _create_final_submit_boundary(app_id)
    reference, lease_token = _authorize_and_claim(auth_client, app_id, handoff_public_id)
    calls = []

    async def fake_submit(session, *, action, **_kwargs):
        db = TestingSessionLocal()
        approval = db.query(SubmissionApproval).filter(
            SubmissionApproval.reference == reference
        ).one()
        metadata = dict(approval.approval_metadata or {})
        calls.append({
            "action": action,
            "checkpoint_present": bool(metadata.get("operator_submit_action_started_at")),
            "automatic_retry_allowed": metadata.get("automatic_retry_allowed"),
        })
        db.close()
        return {
            "action": "operator_submit",
            "current_url": LEVER_URL,
            "current_fingerprint": "after-submit",
            "submission_confirmed": False,
        }

    monkeypatch.setattr(
        "app.api.supervised_submissions.browser_handoff_service.perform_handoff_action",
        fake_submit,
    )

    first = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/handoffs/{handoff_public_id}/submit",
        json={"lease_token": lease_token},
    )
    assert first.status_code == 200
    assert first.json()["automatic_retry_allowed"] is False
    assert first.json()["submission_confirmed"] is False
    assert calls == [{
        "action": "operator_submit",
        "checkpoint_present": True,
        "automatic_retry_allowed": False,
    }]

    second = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/handoffs/{handoff_public_id}/submit",
        json={"lease_token": lease_token},
    )
    assert second.status_code == 409
    assert "automatic retry is forbidden" in second.json()["detail"].lower()
    assert len(calls) == 1

    db = TestingSessionLocal()
    approval = db.query(SubmissionApproval).filter(SubmissionApproval.reference == reference).one()
    metadata = dict(approval.approval_metadata or {})
    assert metadata["operator_submit_action_started"] is True
    assert metadata["operator_submit_action_completed"] is True
    assert metadata["operator_submit_action_result"] == "awaiting_confirmation"
    assert metadata["automatic_retry_allowed"] is False
    db.close()


def test_ambiguous_final_action_is_quarantined_and_never_replayed(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path)
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)
    handoff_public_id = _create_final_submit_boundary(app_id)
    reference, lease_token = _authorize_and_claim(auth_client, app_id, handoff_public_id)
    calls = []

    async def ambiguous_submit(_session, *, action, **_kwargs):
        calls.append(action)
        raise RuntimeError("browser transport disappeared after external action boundary")

    monkeypatch.setattr(
        "app.api.supervised_submissions.browser_handoff_service.perform_handoff_action",
        ambiguous_submit,
    )

    first = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/handoffs/{handoff_public_id}/submit",
        json={"lease_token": lease_token},
    )
    assert first.status_code == 409
    assert "outcome is uncertain" in first.json()["detail"].lower()
    assert calls == ["operator_submit"]

    second = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/handoffs/{handoff_public_id}/submit",
        json={"lease_token": lease_token},
    )
    assert second.status_code == 409
    assert "automatic retry is forbidden" in second.json()["detail"].lower()
    assert calls == ["operator_submit"]

    db = TestingSessionLocal()
    approval = db.query(SubmissionApproval).filter(SubmissionApproval.reference == reference).one()
    metadata = dict(approval.approval_metadata or {})
    assert metadata["operator_submit_action_result"] == "uncertain"
    assert metadata["operator_submit_action_completed"] is False
    assert metadata["automatic_retry_allowed"] is False
    db.close()


@pytest.mark.asyncio
async def test_final_submit_handoff_rejects_generic_browser_actions():
    install_operator_assisted_handoff_integration()
    session = ManualHandoffSession(
        application_id=1,
        manual_review_id=1,
        user_id=1,
        challenge_type=HandoffChallengeType.final_submit.value,
        status="claimed",
        idempotency_key="test-final-submit-action-lock",
        resume_token_hash="x",
        encrypted_resume_token="x",
        resume_token_prefix="x",
        browser_provider="local_cdp",
    )

    with pytest.raises(browser_handoff.BrowserHandoffError, match="review-only"):
        await browser_handoff.perform_handoff_action(
            session,
            action="click",
            x=10,
            y=10,
        )

    with pytest.raises(browser_handoff.BrowserHandoffError, match="review-only"):
        await browser_handoff.perform_handoff_action(
            session,
            action="type",
            text="changed answer",
        )
