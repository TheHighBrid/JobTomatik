from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import ManualHandoffSession
from app.models.job import Job
from app.models.user import User
from app.services.handoff_integration import _attach_handoff_session
from app.services.handoff_session import decrypt_handoff_secret
from conftest import TestingSessionLocal


def test_review_integration_extracts_browser_secrets_from_result():
    db = TestingSessionLocal()
    try:
        user = User(
            email="handoff-integration@example.com",
            hashed_password="not-used",
        )
        job = Job(
            title="Integration Role",
            company="Integration Company",
            url="https://example.test/integration",
        )
        db.add_all([user, job])
        db.flush()
        application = Application(
            user_id=user.id,
            job_id=job.id,
            status=ApplicationStatus.pending,
            automation_state=ApplicationAutomationState.needs_review.value,
            submission_idempotency_key=f"handoff-integration-{user.id}-{job.id}",
        )
        db.add(application)
        db.flush()
        review = ManualReviewTask(
            application_id=application.id,
            reason_code=ManualReviewReason.captcha_detected.value,
            status=ManualReviewStatus.open.value,
            summary="CAPTCHA requires a human.",
            blocking_url=job.url,
        )
        db.add(review)
        db.flush()

        result = {
            "dry_run": True,
            "ats_adapter": "greenhouse",
            "ats_adapter_version": "1.1.0",
            "handoff_snapshot": {
                "browser_provider": "local_cdp",
                "browser_session_id": "browser-session-123",
                "browser_endpoint": "http://127.0.0.1:9777",
                "browser_node_id": "node-a",
                "browser_process_id": 12345,
                "browser_profile_path": "/tmp/handoff/profile",
                "active_page_hint": job.url,
                "current_url": job.url,
                "current_fingerprint": "fingerprint-123",
                "storage_state_path": "/tmp/handoff/storage.json",
                "storage_state_hash": "storage-hash",
                "screenshot_path": "/tmp/handoff/screenshot.png",
                "html_snapshot_path": "/tmp/handoff/page.html",
                "metadata": {"fields_filled": 12},
            },
        }

        _attach_handoff_session(
            db,
            application,
            result,
            ManualReviewReason.captcha_detected,
        )
        db.commit()

        session = db.query(ManualHandoffSession).one()
        assert result["handoff_public_id"] == session.public_id
        assert "handoff_snapshot" not in result
        assert "browser_endpoint" not in str(result)
        assert "resume_token" not in str(result)
        assert review.details["handoff_public_id"] == session.public_id
        assert "browser_endpoint" not in str(review.details)
        assert decrypt_handoff_secret(session.encrypted_browser_endpoint) == "http://127.0.0.1:9777"
        assert session.browser_session_id == "browser-session-123"
        assert session.handoff_metadata["html_snapshot_path"] == "/tmp/handoff/page.html"
    finally:
        db.close()
