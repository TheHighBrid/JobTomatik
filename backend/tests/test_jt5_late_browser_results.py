"""Synthetic browser/checkpoint races retain receipts without rewriting history."""

from datetime import datetime, timezone

import pytest

from app.config import get_settings
from app.models.application import Application, ApplicationEvent, ApplicationStatus, SubmissionEvidence
from app.models.submission_integrity import SubmissionAttempt
from app.services.application_attempt_jt5 import reserve_jt5_attempt
from app.tasks.jt5_execution import execute_reserved_application
from tests.conftest import TestingSessionLocal
from tests.test_jt5_reservation_and_worker import _application, _job, _user


@pytest.fixture
def reserved(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_real_application_submit", True)
    monkeypatch.setattr("app.tasks.jt5_execution._profile_dict", lambda *args: {})
    owner = _user(db_session)
    application = _application(db_session, owner, _job(db_session))
    _, attempt = reserve_jt5_attempt(
        db_session, application_id=application.id, authenticated_user_id=owner.id,
    )
    db_session.commit()
    return application.id, attempt.reference


def _close_checkpoint(application_id, reference, status):
    session = TestingSessionLocal()
    try:
        application = session.get(Application, application_id)
        attempt = session.query(SubmissionAttempt).filter_by(reference=reference).one()
        application.automation_state = {
            "succeeded": "confirmed", "uncertain": "submission_uncertain",
            "failed": "ready_to_apply", "blocked": "needs_review",
        }[status]
        application.status = ApplicationStatus.interviewing
        application.applied_at = datetime(2026, 10, 1, 12)
        application.automation_log = [{"action": "independent_recovery_saved"}]
        attempt.status = status
        attempt.attempt_metadata = {
            **attempt.attempt_metadata,
            "result": {"outcome": "independent_recovery"},
            "owner_resolution": {"request_hash": "saved-receipt"},
        }
        session.commit()
    finally:
        session.close()


@pytest.mark.parametrize("status", ["succeeded", "uncertain", "failed", "blocked"])
@pytest.mark.parametrize("signal", [
    {"confirmation_text": "Application received"},
    {"external_application_id": "employer-receipt-42"},
    {"screenshot_path": "/evidence/receipt.png", "html_snapshot_path": "/evidence/receipt.html"},
])
def test_late_confirmation_keeps_complete_receipt_and_closed_outcome(
    db_session, monkeypatch, reserved, status, signal,
):
    application_id, reference = reserved

    def persistent_identity_map():
        session = TestingSessionLocal()
        session.expire_on_commit = False
        return session

    monkeypatch.setattr("app.tasks.jt5_execution.SessionLocal", persistent_identity_map)

    async def browser_finishes_after_recovery(*args, **kwargs):
        _close_checkpoint(application_id, reference, status)
        return {
            "success": True,
            "confirmation_evidence": {
                "evidence_type": "confirmation_page", "is_sufficient": True,
                "final_url": "https://boards.greenhouse.io/example/jobs/1/confirmation",
                "payload_hash": "original-browser-hash",
                "metadata": {"adapter": "synthetic-fixture"},
                **signal,
            },
        }

    monkeypatch.setattr(
        "app.tasks.jt5_execution.fill_and_submit_application", browser_finishes_after_recovery,
    )
    result = execute_reserved_application.run(application_id, reference)
    assert result["outcome"] == "reconciliation_required"
    assert result["automatic_retry_allowed"] is False
    db_session.expire_all()
    application = db_session.get(Application, application_id)
    attempt = db_session.query(SubmissionAttempt).filter_by(reference=reference).one()
    assert attempt.status == status
    assert attempt.attempt_metadata["result"] == {"outcome": "independent_recovery"}
    assert attempt.attempt_metadata["owner_resolution"] == {"request_hash": "saved-receipt"}
    assert application.status == ApplicationStatus.interviewing
    saved_time = application.applied_at
    if saved_time.tzinfo is None:
        saved_time = saved_time.replace(tzinfo=timezone.utc)
    assert saved_time == datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    assert application.automation_log == [{"action": "independent_recovery_saved"}]
    receipt = db_session.query(SubmissionEvidence).filter_by(application_id=application_id).one()
    for key, value in signal.items():
        assert getattr(receipt, key) == value
    assert receipt.is_sufficient is True
    assert receipt.payload_hash == "original-browser-hash"
    assert receipt.evidence_metadata["attempt_reference"] == reference
    assert receipt.evidence_metadata["jt5_worker_attempt_reference"] == reference
    assert receipt.evidence_metadata["jt5_late_result"] is True
    assert receipt.evidence_metadata["adapter"] == "synthetic-fixture"
    event = db_session.query(ApplicationEvent).filter_by(
        application_id=application_id, event_type="jt5_late_browser_result_retained",
    ).one()
    assert event.from_state == event.to_state == application.automation_state
    assert event.payload["retained_evidence_count"] == 1
    assert event.payload["observed_outcome"] == "confirmed"


def test_late_pre_submit_failure_cannot_demote_confirmed_outcome(db_session, monkeypatch, reserved):
    application_id, reference = reserved

    async def late_failure(*args, **kwargs):
        _close_checkpoint(application_id, reference, "succeeded")
        return {
            "success": False, "final_submit_attempted": False,
            "pre_submit_failure_verified": True, "error": "synthetic local failure",
        }

    monkeypatch.setattr("app.tasks.jt5_execution.fill_and_submit_application", late_failure)
    result = execute_reserved_application.run(application_id, reference)
    assert result["outcome"] == "reconciliation_required"
    db_session.expire_all()
    assert db_session.get(Application, application_id).automation_state == "confirmed"
    assert db_session.query(SubmissionAttempt).filter_by(reference=reference).one().status == "succeeded"
    event = db_session.query(ApplicationEvent).filter_by(event_type="jt5_late_browser_result_retained").one()
    assert event.payload["observed_outcome"] == "failed_pre_submit"
    assert event.payload["retained_evidence_count"] == 0


def test_current_result_keeps_observed_binding_and_adds_worker_provenance(
    db_session, monkeypatch, reserved,
):
    application_id, reference = reserved

    async def current_receipt(*args, **kwargs):
        return {
            "success": True,
            "confirmation_evidence": [{
                "is_sufficient": True, "confirmation_text": "Receipt retained",
                "metadata": {"attempt_reference": "conflicting-observed-binding"},
            }, "malformed-evidence"],
        }

    monkeypatch.setattr("app.tasks.jt5_execution.fill_and_submit_application", current_receipt)
    assert execute_reserved_application.run(application_id, reference)["outcome"] == "confirmed"
    receipt = db_session.query(SubmissionEvidence).filter_by(application_id=application_id).one()
    assert receipt.evidence_metadata["attempt_reference"] == "conflicting-observed-binding"
    assert receipt.evidence_metadata["jt5_worker_attempt_reference"] == reference
    assert receipt.evidence_metadata["jt5_late_result"] is False


def test_postgres_reconciliation_race_retains_late_receipt(db_session, monkeypatch, reserved):
    """Use real row locks and the reconciler to exercise simultaneous recovery."""
    from threading import Event, Thread, get_ident

    from sqlalchemy import event, text

    from app.services.jt5_reconciliation import _mark_uncertain

    engine = db_session.get_bind()
    if engine.dialect.name != "postgresql":
        pytest.skip("Real PostgreSQL row locks are required for this race")

    application_id, reference = reserved
    reconciler_locked = Event()
    worker_lock_requested = Event()
    failures = []
    worker_thread_id = get_ident()

    def observe_worker_lock(conn, cursor, statement, parameters, context, executemany):
        if (get_ident() == worker_thread_id and reconciler_locked.is_set()
                and "submission_attempts" in statement and "FOR UPDATE" in statement):
            worker_lock_requested.set()

    def recover_checkpoint():
        session = TestingSessionLocal()
        try:
            session.execute(text("SET lock_timeout = '2s'"))
            attempt = session.query(SubmissionAttempt).filter_by(
                reference=reference,
            ).with_for_update().one()
            reconciler_locked.set()
            assert worker_lock_requested.wait(10), "Worker never requested its final attempt lock"
            _mark_uncertain(session, attempt, datetime.now(timezone.utc), "worker_restarted_in_progress")
            session.commit()
        except Exception as exc:
            session.rollback()
            failures.append(exc)
        finally:
            session.close()

    reconciler = Thread(target=recover_checkpoint, daemon=True)

    async def delayed_receipt(*args, **kwargs):
        reconciler.start()
        assert reconciler_locked.wait(10), "Reconciler did not acquire the attempt lock"
        return {
            "success": True,
            "confirmation_evidence": {
                "evidence_type": "confirmation_page", "is_sufficient": True,
                "confirmation_text": "Employer received the application during recovery",
                "external_application_id": "concurrent-receipt-42",
            },
        }

    event.listen(engine, "before_cursor_execute", observe_worker_lock)
    monkeypatch.setattr("app.tasks.jt5_execution.fill_and_submit_application", delayed_receipt)
    try:
        result = execute_reserved_application.run(application_id, reference)
    finally:
        worker_lock_requested.set()
        if reconciler.ident is not None:
            reconciler.join(10)
        event.remove(engine, "before_cursor_execute", observe_worker_lock)

    assert not reconciler.is_alive(), "Reconciler did not complete"
    assert not failures, repr(failures)
    assert result["outcome"] == "reconciliation_required"
    assert result["automatic_retry_allowed"] is False
    db_session.expire_all()
    assert db_session.get(Application, application_id).automation_state == "submission_uncertain"
    attempt = db_session.query(SubmissionAttempt).filter_by(reference=reference).one()
    assert attempt.status == "uncertain"
    assert attempt.attempt_metadata["reconciliation_reason"] == "worker_restarted_in_progress"
    receipt = db_session.query(SubmissionEvidence).filter_by(application_id=application_id).one()
    assert receipt.confirmation_text == "Employer received the application during recovery"
    assert receipt.external_application_id == "concurrent-receipt-42"
    assert receipt.evidence_metadata["jt5_late_result"] is True
    saved_event = db_session.query(ApplicationEvent).filter_by(
        application_id=application_id, event_type="jt5_late_browser_result_retained",
    ).one()
    assert saved_event.payload["retained_evidence_count"] == 1
