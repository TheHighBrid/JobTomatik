from datetime import UTC, datetime

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
from app.models.submission_approval import SubmissionApproval
from app.services.browser_handoff import BrowserVerification
from tests.conftest import TestingSessionLocal
from tests.test_operator_assisted_submission import (
    LEVER_URL,
    _authorize_and_claim,
    _create_final_submit_boundary,
    _keep_automation_off,
    _mock_metadata,
    _prepare_application,
)


def _confirmed_verification(session, *, suffix=""):
    final_url = LEVER_URL.replace("/apply", "/thanks")
    return BrowserVerification(
        challenge_cleared=True,
        provider=session.browser_provider,
        current_url=final_url,
        current_fingerprint=f"lever-confirmed-fingerprint{suffix}",
        evidence={
            "submission_confirmed": True,
            "confirmation_url_signal": True,
            "confirmation_evidence": [{
                "evidence_type": "confirmation_page",
                "is_sufficient": True,
                "final_url": final_url,
                "confirmation_text": "thank you for applying",
                "selector": "body",
                "metadata": {"verification_method": "explicit_confirmation_text"},
            }],
            "target_verification": {"verified": True, "adapter": "lever"},
            "verification_method": "operator_final_submit_retained_human_confirmation",
            "storage_state_hash": f"storage-hash{suffix}",
        },
    )


def _complete_confirmed_handoff(auth_client, tmp_path, monkeypatch, *, suffix=""):
    app_id = _prepare_application(auth_client, tmp_path)
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)
    public_id = _create_final_submit_boundary(app_id)
    reference, lease_token = _authorize_and_claim(auth_client, app_id, public_id)

    async def fake_verification(session):
        return _confirmed_verification(session, suffix=suffix)

    monkeypatch.setattr("app.api.handoffs.verify_browser_handoff_completion", fake_verification)
    completed = auth_client.post(
        f"/api/handoffs/{public_id}/complete",
        json={"lease_token": lease_token},
    )
    assert completed.status_code == 200, completed.text
    return app_id, public_id, reference, completed


def test_retained_owner_final_click_confirmation_reconciles_application(auth_client, tmp_path, monkeypatch):
    app_id, public_id, reference, completed = _complete_confirmed_handoff(
        auth_client, tmp_path, monkeypatch
    )
    assert completed.json()["status"] == HandoffSessionStatus.completed.value

    db = TestingSessionLocal()
    try:
        application = db.query(Application).filter(Application.id == app_id).one()
        review = db.query(ManualReviewTask).filter(ManualReviewTask.id == completed.json()["manual_review_id"]).one()
        handoff = db.query(ManualHandoffSession).filter(ManualHandoffSession.public_id == public_id).one()
        approval = db.query(SubmissionApproval).filter(SubmissionApproval.reference == reference).one()
        evidence = db.query(SubmissionEvidence).filter(SubmissionEvidence.application_id == app_id, SubmissionEvidence.is_sufficient.is_(True)).all()
        assert application.status == ApplicationStatus.applied
        assert application.automation_state == ApplicationAutomationState.confirmed.value
        assert application.applied_at is not None
        assert review.status == ManualReviewStatus.resolved.value
        assert handoff.status == HandoffSessionStatus.completed.value
        assert handoff.completed_at is not None
        assert len(evidence) == 1
        assert evidence[0].evidence_type == "confirmation_page"
        assert dict(handoff.handoff_metadata or {})["operator_submit_confirmation_observed"] is True
        approval_metadata = dict(approval.approval_metadata or {})
        assert approval_metadata["operator_submit_action_result"] == "confirmed"
        assert approval_metadata["operator_submit_confirmation_observed"] is True
    finally:
        db.close()


def test_confirmed_application_is_closed_against_repeat_submission(auth_client, tmp_path, monkeypatch):
    app_id, _, _, _ = _complete_confirmed_handoff(
        auth_client, tmp_path, monkeypatch, suffix="-2"
    )
    preflight = auth_client.get(
        f"/api/supervised-submissions/applications/{app_id}/operator-assisted/preflight"
    )
    assert preflight.status_code == 409
    assert "already closed" in preflight.json()["detail"].lower()

    db = TestingSessionLocal()
    try:
        application = db.query(Application).filter(Application.id == app_id).one()
        assert application.status == ApplicationStatus.applied
        assert application.automation_state == ApplicationAutomationState.confirmed.value
        assert application.applied_at <= datetime.now(UTC).replace(tzinfo=None)
    finally:
        db.close()
