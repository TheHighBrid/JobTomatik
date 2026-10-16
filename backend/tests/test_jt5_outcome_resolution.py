"""Outcome recovery must preserve evidence, ownership and once-only execution."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.models.application import (
    Application, ApplicationEvent, ApplicationStatus, ManualReviewTask, SubmissionEvidence,
)
from app.models.handoff import ManualHandoffSession
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services.application_attempt_jt5 import reserve_jt5_attempt
from app.services.application_execution_gate import ApplyDecision
from app.services.jt5_outcome_resolution import JT5ResolutionError, require_idle_onehost_worker
from app.services.submission_evidence_review import build_evidence_snapshot
from tests.test_jt5_reservation_and_worker import _application, _job


@pytest.fixture
def recovery(auth_client, db_session, monkeypatch):
    owner = db_session.query(User).filter_by(email="test@example.com").one()
    application = _application(db_session, owner, _job(db_session))
    _, attempt = reserve_jt5_attempt(db_session, application_id=application.id, authenticated_user_id=owner.id)
    attempt.status = "uncertain"
    attempt.attempt_metadata = {**attempt.attempt_metadata, "result": {"outcome": "submission_uncertain"}}
    application.automation_state = "submission_uncertain"
    db_session.commit()
    idle = MagicMock()
    monkeypatch.setattr("app.services.jt5_outcome_resolution.require_idle_onehost_worker", idle)
    data = {
        "attempt_reference": attempt.reference, "outcome": "not_submitted",
        "evidence_source": "employer_response", "evidence_reference": "Employer case JT5-42",
        "notes": "Employer verified this exact posting has no submission from the applicant.",
        "outcome_verified": True,
    }
    return application, attempt, data, idle


def _resolve(client, application, data):
    return client.post(f"/api/applications/{application.id}/jt5/reconcile", json=data)


def _confirmed_data(db, application, data):
    evidence = SubmissionEvidence(
        application_id=application.id, evidence_type="confirmation_page", is_sufficient=True,
        confirmation_text="Application received", final_url=application.application_target_url,
        captured_at=datetime.utcnow(),
        evidence_metadata={"attempt_reference": data["attempt_reference"]},
    )
    db.add(evidence)
    db.commit()
    value = {
        **data, "outcome": "confirmed", "evidence_source": "retained_confirmation",
        "evidence_id": evidence.id, "evidence_reference": f"submission-evidence:{evidence.id}",
        "evidence_snapshot_hash": build_evidence_snapshot(evidence)["evidence_snapshot_hash"],
    }
    return evidence, value


def test_non_submission_is_audited_without_dispatch_and_exact_replay_is_idempotent(auth_client, db_session, recovery):
    import app.api.jt5_applications as api

    application, attempt, data, idle = recovery
    result = _resolve(auth_client, application, data)
    assert result.status_code == 200
    assert result.json()["automatic_retry_allowed"] is False
    assert result.json()["finding_source"] == "authenticated_owner_review"
    assert result.json()["original_result"] == {"outcome": "submission_uncertain"}
    idle.assert_called_once()
    api.execute_reserved_application.apply_async.assert_not_called()
    db_session.expire_all()
    assert db_session.get(SubmissionAttempt, attempt.id).status == "failed"
    assert db_session.get(Application, application.id).automation_state == "ready_to_apply"
    count = db_session.query(ApplicationEvent).count()
    replay = _resolve(auth_client, application, data)
    assert replay.status_code == 200
    assert replay.json()["idempotent"] is True
    assert db_session.query(ApplicationEvent).count() == count
    decision, _ = reserve_jt5_attempt(db_session, application_id=application.id, authenticated_user_id=application.user_id)
    assert decision.decision is ApplyDecision.EXECUTE
    db_session.rollback()


def test_confirmation_requires_current_evidence_and_blocks_another_attempt(auth_client, db_session, recovery):
    application, attempt, data, idle = recovery
    _, data = _confirmed_data(db_session, application, data)
    result = _resolve(auth_client, application, data)
    assert result.status_code == 200
    idle.assert_not_called()
    db_session.expire_all()
    saved = db_session.get(Application, application.id)
    assert saved.automation_state == "confirmed"
    assert saved.status == ApplicationStatus.applied
    assert saved.applied_at is not None
    assert db_session.get(SubmissionAttempt, attempt.id).status == "succeeded"
    decision, _ = reserve_jt5_attempt(db_session, application_id=application.id, authenticated_user_id=saved.user_id)
    assert decision.decision is ApplyDecision.ALREADY_CONFIRMED


@pytest.mark.parametrize("outcome", ["interviewing", "offer", "rejected"])
def test_confirmation_preserves_later_owner_status(auth_client, db_session, recovery, outcome):
    application, _, data, _ = recovery
    application.status = ApplicationStatus(outcome)
    db_session.commit()
    _, data = _confirmed_data(db_session, application, data)
    assert _resolve(auth_client, application, data).status_code == 200
    db_session.refresh(application)
    assert application.status.value == outcome


def test_resolution_cannot_be_changed_after_it_is_recorded(auth_client, recovery):
    application, _, data, _ = recovery
    assert _resolve(auth_client, application, data).status_code == 200
    assert _resolve(auth_client, application, {**data, "evidence_reference": "different-case"}).status_code == 409


@pytest.mark.parametrize("change", [
    {"outcome_verified": False}, {"notes": "not enough"}, {"outcome": "unknown"}, {"unexpected_field": True},
])
def test_invalid_or_unverified_decision_writes_nothing(auth_client, db_session, recovery, change):
    application, attempt, data, _ = recovery
    count = db_session.query(ApplicationEvent).count()
    assert _resolve(auth_client, application, {**data, **change}).status_code == 422
    db_session.refresh(attempt)
    assert attempt.status == "uncertain"
    assert db_session.query(ApplicationEvent).count() == count


@pytest.mark.parametrize("status", ["applied", "interviewing", "withdrawn"])
def test_non_submission_cannot_erase_owner_history(auth_client, db_session, recovery, status):
    application, attempt, data, _ = recovery
    application.status = ApplicationStatus(status)
    db_session.commit()
    assert _resolve(auth_client, application, data).status_code == 409
    db_session.refresh(attempt)
    assert attempt.status == "uncertain"


def test_missing_confirmation_does_not_establish_non_submission(auth_client, recovery):
    application, _, data, _ = recovery
    assert _resolve(auth_client, application, {**data, "evidence_source": "retained_confirmation"}).status_code == 409
    assert _resolve(auth_client, application, {**data, "outcome": "confirmed"}).status_code == 409


def test_existing_sufficient_evidence_blocks_non_submission(auth_client, db_session, recovery):
    application, _, data, _ = recovery
    _confirmed_data(db_session, application, data)
    assert _resolve(auth_client, application, data).status_code == 409


@pytest.mark.parametrize("mutation", ["changed", "old", "wrong_attempt", "insufficient"])
def test_stale_or_inadequate_confirmation_is_rejected(auth_client, db_session, recovery, mutation):
    application, attempt, data, _ = recovery
    evidence, data = _confirmed_data(db_session, application, data)
    if mutation == "changed":
        evidence.confirmation_text = "Changed after the owner loaded it"
    elif mutation == "old":
        evidence.captured_at = attempt.queued_at - timedelta(days=1)
    elif mutation == "wrong_attempt":
        evidence.evidence_metadata = {"attempt_reference": "another-attempt"}
    else:
        evidence.is_sufficient = False
    db_session.commit()
    assert _resolve(auth_client, application, data).status_code == 409
    db_session.refresh(attempt)
    assert attempt.status == "uncertain"


def test_non_owner_is_hidden_before_attempt_or_worker_inspection(auth_client, db_session, recovery):
    application, _, data, idle = recovery
    stranger = User(email="stranger@example.test", full_name="Another Owner", hashed_password="unused")
    db_session.add(stranger)
    db_session.flush()
    application.user_id = stranger.id
    db_session.commit()
    assert _resolve(auth_client, application, data).status_code == 404
    assert auth_client.get(f"/api/applications/{application.id}/jt5/reconciliation").status_code == 404
    idle.assert_not_called()


def test_unauthenticated_resolution_is_rejected(client, db_session, recovery):
    application, _, data, idle = recovery
    client.headers.pop("Authorization", None)
    assert _resolve(client, application, data).status_code == 401
    idle.assert_not_called()


def test_different_and_non_jt5_attempts_cannot_be_resolved(auth_client, db_session, recovery):
    application, attempt, data, _ = recovery
    assert _resolve(auth_client, application, {**data, "attempt_reference": "missing"}).status_code == 404
    attempt.attempt_metadata = {"execution_contract": "supervised"}
    db_session.commit()
    assert _resolve(auth_client, application, data).status_code == 409


def test_queued_lost_publication_can_be_closed_without_replay(auth_client, db_session, recovery):
    application, attempt, data, _ = recovery
    attempt.status = "queued"
    attempt.attempt_metadata = {**attempt.attempt_metadata, "dispatch_status": "reconciliation_required"}
    application.automation_state = "ready_to_apply"
    db_session.commit()
    assert _resolve(auth_client, application, data).status_code == 200
    db_session.refresh(attempt)
    assert attempt.status == "failed"


def test_live_handoff_keeps_non_submission_blocked(auth_client, db_session, recovery):
    application, _, data, idle = recovery
    review = ManualReviewTask(application_id=application.id, reason_code="submission_confirmation_uncertain", summary="Uncertain")
    db_session.add(review)
    db_session.flush()
    session = ManualHandoffSession(
        application_id=application.id, manual_review_id=review.id, user_id=application.user_id,
        status="ready_to_resume", challenge_type="final_submit", idempotency_key="recovery-handoff",
        resume_token_hash="unused", encrypted_resume_token="unused", resume_token_prefix="unused",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db_session.add(session)
    db_session.commit()
    assert _resolve(auth_client, application, data).status_code == 409
    idle.assert_not_called()


def test_busy_or_unreachable_worker_prevents_recovery(auth_client, monkeypatch, recovery):
    application, _, data, _ = recovery

    def busy():
        raise JT5ResolutionError("Worker state is unavailable")

    monkeypatch.setattr("app.services.jt5_outcome_resolution.require_idle_onehost_worker", busy)
    assert _resolve(auth_client, application, data).status_code == 409


@pytest.mark.parametrize("responses", [
    (None, None, None), ({}, {}, {}),
    ({"one": [{"id": "active"}]}, {"one": []}, {"one": []}),
    ({"one": []}, {"two": []}, {"one": []}),
    ({"one": [], "two": []}, {"one": []}, {"one": []}),
])
def test_worker_inspection_fails_closed(monkeypatch, responses):
    from app.celery_app import celery_app

    inspector = MagicMock()
    inspector.active.return_value, inspector.reserved.return_value, inspector.scheduled.return_value = responses
    monkeypatch.setattr(celery_app.control, "inspect", lambda **kwargs: inspector)
    with pytest.raises(JT5ResolutionError):
        require_idle_onehost_worker()


def test_context_lists_only_current_confirmation_without_worker_contact(auth_client, db_session, recovery):
    application, attempt, data, idle = recovery
    evidence, _ = _confirmed_data(db_session, application, data)
    response = auth_client.get(f"/api/applications/{application.id}/jt5/reconciliation")
    assert response.status_code == 200
    assert response.json()["attempt_reference"] == attempt.reference
    assert response.json()["confirmation_evidence"][0]["id"] == evidence.id
    idle.assert_not_called()
