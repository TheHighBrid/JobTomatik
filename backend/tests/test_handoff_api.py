from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import HandoffSessionEvent, HandoffSessionStatus
from app.models.job import Job
from app.models.user import User
from app.services.browser_handoff import BrowserVerification
from app.services.handoff_session import issue_handoff_session
from conftest import TestingSessionLocal


def create_session_for_authenticated_user():
    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").first()
    job = Job(
        title="Handoff API Role",
        company="Handoff API Company",
        url="https://example.test/handoff-api",
    )
    db.add(job)
    db.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.needs_review.value,
        submission_idempotency_key=f"handoff-api-{user.id}-{job.id}",
    )
    db.add(application)
    db.flush()
    review = ManualReviewTask(
        application_id=application.id,
        reason_code=ManualReviewReason.captcha_detected.value,
        status=ManualReviewStatus.open.value,
        summary="Complete the CAPTCHA.",
        blocking_url=job.url,
    )
    db.add(review)
    db.flush()
    issued = issue_handoff_session(
        db,
        application,
        review,
        browser_provider="local_cdp",
        browser_endpoint="http://127.0.0.1:9222",
        browser_node_id="test-node",
        current_url=job.url,
        metadata={"dry_run": True},
    )
    db.commit()
    public_id = issued.session.public_id
    application_id = application.id
    db.close()
    return public_id, application_id


def test_bootstrap_discloses_resume_token_only_once(auth_client):
    public_id, _ = create_session_for_authenticated_user()

    first = auth_client.post(f"/api/handoffs/{public_id}/bootstrap")
    assert first.status_code == 200
    payload = first.json()
    token = payload["resume_token"]
    assert len(token) >= 24
    serialized = str(payload)
    assert "encrypted_resume_token" not in serialized
    assert "resume_token_hash" not in serialized
    assert "encrypted_browser_endpoint" not in serialized

    second = auth_client.post(f"/api/handoffs/{public_id}/bootstrap")
    assert second.status_code == 409

    detail = auth_client.get(f"/api/handoffs/{public_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert "resume_token" not in detail_payload
    assert any(
        event["event_type"] == "handoff_resume_token_disclosed"
        for event in detail_payload["events"]
    )


def test_claim_rotates_to_lease_and_owner_can_heartbeat(auth_client):
    public_id, _ = create_session_for_authenticated_user()
    token = auth_client.post(f"/api/handoffs/{public_id}/bootstrap").json()["resume_token"]

    claim = auth_client.post(
        f"/api/handoffs/{public_id}/claim",
        json={"resume_token": token},
    )
    assert claim.status_code == 200
    lease = claim.json()["lease_token"]
    assert lease != token
    assert claim.json()["session"]["status"] == HandoffSessionStatus.claimed.value

    heartbeat = auth_client.post(
        f"/api/handoffs/{public_id}/heartbeat",
        json={"lease_token": lease},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["lease_expires_at"] is not None

    replay = auth_client.post(
        f"/api/handoffs/{public_id}/claim",
        json={"resume_token": token},
    )
    assert replay.status_code == 409


def test_browser_action_never_persists_typed_secret(auth_client, monkeypatch):
    public_id, _ = create_session_for_authenticated_user()
    token = auth_client.post(f"/api/handoffs/{public_id}/bootstrap").json()["resume_token"]
    lease = auth_client.post(
        f"/api/handoffs/{public_id}/claim",
        json={"resume_token": token},
    ).json()["lease_token"]

    async def fake_action(session, **kwargs):
        assert kwargs["text"] == "654321"
        return {
            "action": kwargs["action"],
            "current_url": session.current_url or "https://example.test/handoff-api",
            "current_fingerprint": "fingerprint-after-secret-entry",
            "sensitive_value_logged": False,
        }

    monkeypatch.setattr("app.api.handoffs.perform_handoff_action", fake_action)
    response = auth_client.post(
        f"/api/handoffs/{public_id}/actions",
        json={
            "lease_token": lease,
            "action": "type",
            "text": "654321",
        },
    )
    assert response.status_code == 200

    db = TestingSessionLocal()
    try:
        event = (
            db.query(HandoffSessionEvent)
            .filter(HandoffSessionEvent.event_type == "handoff_browser_action")
            .order_by(HandoffSessionEvent.id.desc())
            .first()
        )
        assert event.payload["action"] == "type"
        assert event.payload["sensitive_value_logged"] is False
        assert "654321" not in str(event.payload)
        assert "text" not in event.payload
    finally:
        db.close()


def test_complete_requires_browser_verified_clearance_and_queues_resume(auth_client, monkeypatch):
    public_id, _ = create_session_for_authenticated_user()
    token = auth_client.post(f"/api/handoffs/{public_id}/bootstrap").json()["resume_token"]
    lease = auth_client.post(
        f"/api/handoffs/{public_id}/claim",
        json={"resume_token": token},
    ).json()["lease_token"]

    async def fake_verification(session):
        return BrowserVerification(
            challenge_cleared=True,
            provider=session.browser_provider,
            current_url=session.current_url or "https://example.test/handoff-api",
            current_fingerprint="verified-fingerprint",
            evidence={
                "verification_method": "browser_state",
                "storage_state_hash": "storage-hash",
                "response_length": 256,
            },
        )

    monkeypatch.setattr(
        "app.api.handoffs.verify_browser_handoff_completion",
        fake_verification,
    )
    response = auth_client.post(
        f"/api/handoffs/{public_id}/complete",
        json={"lease_token": lease},
    )
    assert response.status_code == 200
    assert response.json()["status"] == HandoffSessionStatus.ready_to_resume.value
    assert response.json()["failure_reason"] is None


def test_application_handoff_listing_is_owner_scoped(auth_client):
    public_id, application_id = create_session_for_authenticated_user()
    response = auth_client.get(f"/api/handoffs/application/{application_id}/sessions")
    assert response.status_code == 200
    assert [item["public_id"] for item in response.json()] == [public_id]
