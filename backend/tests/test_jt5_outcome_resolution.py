"""JT5 recovery confirms retained receipts without reopening uncertain attempts."""
from datetime import datetime, timedelta

import pytest

from app.models.application import Application, ApplicationEvent, ApplicationStatus, ManualReviewTask, SubmissionEvidence
from app.models.handoff import ManualHandoffSession
from app.models.submission_integrity import SubmissionAttempt
from app.models.submission_evidence_review import SubmissionEvidenceReview
from app.models.user import User
from app.services.application_attempt_jt5 import reserve_jt5_attempt
from app.services.application_execution_gate import ApplyDecision
from app.services.submission_evidence_review import build_evidence_snapshot
from tests.test_jt5_reservation_and_worker import _application, _job


@pytest.fixture
def recovery(auth_client, db_session):
    owner = db_session.query(User).filter_by(email="test@example.com").one()
    application = _application(db_session, owner, _job(db_session))
    _, attempt = reserve_jt5_attempt(db_session, application_id=application.id, authenticated_user_id=owner.id)
    attempt.status = "uncertain"
    attempt.attempt_metadata = {**attempt.attempt_metadata, "dispatch_status": "reconciliation_required",
                                "result": {"outcome": "submission_uncertain", "final_submit_attempted": True}}
    application.automation_state = "submission_uncertain"
    evidence = SubmissionEvidence(
        application_id=application.id, evidence_type="confirmation_page", is_sufficient=True,
        confirmation_text="Application received for the exact posting", final_url=application.application_target_url,
        captured_at=datetime.utcnow(), evidence_metadata={"attempt_reference": attempt.reference, "jt5_worker_attempt_reference": attempt.reference},
    )
    db_session.add(evidence)
    db_session.commit()
    data = {
        "attempt_reference": attempt.reference, "outcome": "confirmed", "evidence_source": "retained_confirmation",
        "evidence_reference": f"submission-evidence:{evidence.id}", "evidence_id": evidence.id,
        "evidence_snapshot_hash": build_evidence_snapshot(evidence)["evidence_snapshot_hash"],
        "notes": "Reviewed retained employer confirmation for this exact posting and attempt.", "outcome_verified": True,
    }
    return application, attempt, evidence, data


def _resolve(client, application, data):
    return client.post(f"/api/applications/{application.id}/jt5/reconcile", json=data)


def test_confirmation_is_audited_idempotent_and_never_dispatches(auth_client, db_session, recovery):
    import app.api.jt5_applications as api

    application, attempt, _, data = recovery
    original = dict(attempt.attempt_metadata["result"])
    result = _resolve(auth_client, application, data)
    assert result.status_code == 200, result.text
    receipt = result.json()
    assert receipt["original_result"] == original
    assert receipt["automatic_retry_allowed"] is False
    api.execute_reserved_application.apply_async.assert_not_called()
    db_session.expire_all()
    assert db_session.get(Application, application.id).automation_state == "confirmed"
    assert db_session.get(Application, application.id).status == ApplicationStatus.applied
    assert db_session.get(SubmissionAttempt, attempt.id).status == "succeeded"
    count = db_session.query(ApplicationEvent).count()
    replay = _resolve(auth_client, application, data)
    assert replay.status_code == 200 and replay.json()["idempotent"] is True
    assert db_session.query(ApplicationEvent).count() == count
    decision, _ = reserve_jt5_attempt(db_session, application_id=application.id, authenticated_user_id=application.user_id)
    assert decision.decision is ApplyDecision.ALREADY_CONFIRMED
    db_session.rollback()
    assert _resolve(auth_client, application, {**data, "notes": "Another materially different review decision."}).status_code == 409


def test_confirmed_owner_resolution_cannot_be_rejected_by_independent_review(
    auth_client, db_session, recovery,
):
    """The exact consumed confirmation snapshot must not later contradict success."""
    from app.models.job import Job
    from app.services.submission_evidence_review import (
        SubmissionEvidenceReviewError,
        review_submission_evidence,
    )

    application, attempt, evidence, data = recovery
    owner = db_session.get(User, application.user_id)
    job = db_session.get(Job, application.job_id)
    assert _resolve(auth_client, application, data).status_code == 200
    db_session.expire_all()
    application = db_session.get(Application, application.id)
    evidence = db_session.get(SubmissionEvidence, evidence.id)
    exact_review = db_session.query(SubmissionEvidenceReview).filter_by(
        evidence_id=evidence.id,
        evidence_snapshot_hash=data["evidence_snapshot_hash"],
    ).one()
    assert exact_review.decision == "accepted"
    assert exact_review.review_metadata["review_source"] == "jt5_owner_resolution"

    with pytest.raises(SubmissionEvidenceReviewError, match="conflicting review"):
        review_submission_evidence(
            db_session, application, owner, job, evidence,
            decision="rejected", confirm_employer=job.company,
            confirm_role=job.title,
            confirm_evidence_type=evidence.evidence_type,
            confirm_evidence_matches_application=True,
            review_acknowledgement="REVIEWED",
            notes="Contradictory review must be blocked",
        )
    db_session.rollback()
    db_session.expire_all()
    assert db_session.get(SubmissionAttempt, attempt.id).status == "succeeded"
    assert db_session.get(Application, application.id).automation_state == "confirmed"
    assert db_session.query(SubmissionEvidenceReview).filter_by(
        evidence_id=evidence.id,
        evidence_snapshot_hash=data["evidence_snapshot_hash"],
        decision="rejected",
    ).count() == 0

@pytest.mark.parametrize("status", ["interviewing", "offer", "rejected"])
def test_confirmation_preserves_later_owner_history(auth_client, db_session, recovery, status):
    application, _, _, data = recovery
    application.status = ApplicationStatus(status)
    db_session.commit()
    assert _resolve(auth_client, application, data).status_code == 200
    db_session.refresh(application)
    assert application.status.value == status


@pytest.mark.parametrize("source", ["employer_response", "employer_portal"])
def test_typed_non_submission_never_releases_retry_block(auth_client, db_session, recovery, monkeypatch, source):
    import app.services.jt5_outcome_resolution as service

    monkeypatch.setattr(service, "require_idle_onehost_worker", lambda: None, raising=False)
    application, attempt, evidence, data = recovery
    db_session.delete(evidence)
    db_session.commit()
    request = {**data, "outcome": "not_submitted", "evidence_source": source,
               "evidence_reference": "x", "evidence_id": None, "evidence_snapshot_hash": None}
    count = db_session.query(ApplicationEvent).count()
    assert _resolve(auth_client, application, request).status_code == 409
    db_session.refresh(attempt)
    db_session.refresh(application)
    assert attempt.status == "uncertain" and application.automation_state == "submission_uncertain"
    assert attempt.attempt_metadata["result"]["final_submit_attempted"] is True
    assert db_session.query(ApplicationEvent).count() == count
    decision, _ = reserve_jt5_attempt(db_session, application_id=application.id, authenticated_user_id=application.user_id)
    assert decision.decision is not ApplyDecision.EXECUTE


@pytest.mark.parametrize("status", ["awaiting_user", "claimed", "ready_to_resume", "resuming"])
def test_active_handoff_blocks_confirmation_without_mutation(auth_client, db_session, recovery, status):
    application, attempt, _, data = recovery
    review = ManualReviewTask(application_id=application.id, reason_code="submission_confirmation_uncertain", summary="Uncertain")
    db_session.add(review)
    db_session.flush()
    handoff = ManualHandoffSession(
        application_id=application.id, manual_review_id=review.id, user_id=application.user_id,
        status=status, challenge_type="final_submit", idempotency_key="synthetic-recovery-handoff",
        resume_token_hash="unused", encrypted_resume_token="unused", resume_token_prefix="unused",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db_session.add(handoff)
    db_session.commit()
    assert _resolve(auth_client, application, data).status_code == 409
    db_session.refresh(attempt)
    assert attempt.status == "uncertain"
    db_session.refresh(handoff)
    assert handoff.status == status


@pytest.mark.parametrize("mutation", ["changed", "old", "unbound", "wrong_attempt", "wrong_worker", "insufficient",
                                       "blank", "artifact_only", "rejected"])
def test_unreviewable_confirmation_cannot_resolve(auth_client, db_session, recovery, mutation):
    application, attempt, evidence, data = recovery
    if mutation == "changed":
        evidence.confirmation_text = "Changed after review"
    elif mutation == "old":
        evidence.captured_at = attempt.queued_at - timedelta(days=1)
    elif mutation == "unbound":
        evidence.evidence_metadata = {}
    elif mutation == "wrong_attempt":
        evidence.evidence_metadata = {"attempt_reference": "another-attempt"}
    elif mutation == "wrong_worker":
        evidence.evidence_metadata = {"attempt_reference": attempt.reference, "jt5_worker_attempt_reference": "other"}
    elif mutation == "insufficient":
        evidence.is_sufficient = False
    elif mutation in {"blank", "artifact_only"}:
        evidence.confirmation_text = "  "
        evidence.screenshot_path = "/synthetic/receipt.png" if mutation == "artifact_only" else None
    else:
        db_session.add(SubmissionEvidenceReview(
            application_id=application.id, evidence_id=evidence.id, reviewer_user_id=application.user_id,
            decision="rejected", evidence_snapshot_hash=data["evidence_snapshot_hash"],
        ))
    db_session.commit()
    # Recompute hash to prove the signal/binding checks work independently of drift.
    if mutation not in {"changed", "rejected"}:
        data["evidence_snapshot_hash"] = build_evidence_snapshot(evidence)["evidence_snapshot_hash"]
    assert _resolve(auth_client, application, data).status_code == 409
    db_session.refresh(attempt)
    assert attempt.status == "uncertain"


@pytest.mark.parametrize("change", [
    {"outcome_verified": False}, {"outcome_verified": 1}, {"outcome_verified": "true"}, {"notes": "short"},
    {"unexpected_field": True}, {"outcome": "unknown"},
])
def test_invalid_requests_write_nothing(auth_client, db_session, recovery, change):
    application, attempt, _, data = recovery
    count = db_session.query(ApplicationEvent).count()
    assert _resolve(auth_client, application, {**data, **change}).status_code == 422
    db_session.refresh(attempt)
    assert attempt.status == "uncertain"
    assert db_session.query(ApplicationEvent).count() == count


def test_non_owner_and_unauthenticated_requests_are_hidden(auth_client, client, db_session, recovery):
    application, _, _, data = recovery
    stranger = User(email="stranger@example.test", full_name="Other", hashed_password="unused")
    db_session.add(stranger)
    db_session.flush()
    application.user_id = stranger.id
    db_session.commit()
    assert _resolve(auth_client, application, data).status_code == 404
    assert auth_client.get(f"/api/applications/{application.id}/jt5/reconciliation").status_code == 404
    client.headers.pop("Authorization", None)
    assert _resolve(client, application, data).status_code == 401


def test_context_reads_retained_confirmation_without_side_effects(auth_client, db_session, recovery):
    application, attempt, evidence, _ = recovery
    count = db_session.query(ApplicationEvent).count()
    result = auth_client.get(f"/api/applications/{application.id}/jt5/reconciliation")
    assert result.status_code == 200
    assert result.json()["attempt_reference"] == attempt.reference
    assert result.json()["confirmation_evidence"][0]["id"] == evidence.id
    assert result.json()["non_submission_resolution_available"] is False
    assert result.json()["automatic_retry_allowed"] is False
    assert db_session.query(ApplicationEvent).count() == count


def test_unrelated_review_and_original_outcome_are_preserved(auth_client, db_session, recovery):
    application, attempt, _, data = recovery
    review = ManualReviewTask(application_id=application.id, reason_code="sensitive_answer_missing", summary="Answer required")
    db_session.add(review)
    db_session.commit()
    assert _resolve(auth_client, application, data).status_code == 200
    db_session.refresh(review)
    assert review.status == "open"
    db_session.refresh(attempt)
    assert attempt.attempt_metadata["owner_resolution"]["original_result"]["outcome"] == "submission_uncertain"


@pytest.mark.parametrize("locked_record", ["attempt", "application"])
def test_postgres_busy_recovery_returns_423_without_writes(auth_client, db_session, recovery, locked_record):
    from tests.conftest import TestingSessionLocal, engine

    if engine.dialect.name != "postgresql":
        pytest.skip("Row-lock isolation requires the dedicated PostgreSQL job")
    application, attempt, _, data = recovery
    application_id, attempt_id = application.id, attempt.id
    db_session.rollback()
    with TestingSessionLocal() as other:
        model, record_id = (SubmissionAttempt, attempt_id) if locked_record == "attempt" else (Application, application_id)
        other.query(model).filter(model.id == record_id).with_for_update().one()
        assert _resolve(auth_client, application, data).status_code == 423
        other.rollback()
    db_session.expire_all()
    assert db_session.get(SubmissionAttempt, attempt_id).status == "uncertain"
    assert db_session.get(Application, application_id).automation_state == "submission_uncertain"
    assert _resolve(auth_client, application, data).status_code == 200


@pytest.mark.parametrize("mutation", ["withdrawn", "wrong_reference", "non_jt5", "different_application"])
def test_unrelated_records_are_not_resolved(auth_client, db_session, recovery, mutation):
    application, attempt, evidence, data = recovery
    expected = 409
    if mutation == "withdrawn":
        application.status = ApplicationStatus.withdrawn
    elif mutation == "wrong_reference":
        data["attempt_reference"] = "missing"
        expected = 404
    elif mutation == "non_jt5":
        attempt.attempt_metadata = {"execution_contract": "supervised"}
    else:
        other = _application(db_session, db_session.get(User, application.user_id),
                             _job(db_session, url="https://boards.greenhouse.io/example/jobs/2"))
        evidence.application_id = other.id
    db_session.commit()
    assert _resolve(auth_client, application, data).status_code == expected
    db_session.refresh(attempt)
    assert attempt.status == "uncertain"


def test_missing_trusted_worker_binding_is_not_offered_or_accepted(auth_client, db_session, recovery):
    application, attempt, evidence, data = recovery
    evidence.evidence_metadata = {"attempt_reference": attempt.reference}
    db_session.commit()
    data["evidence_snapshot_hash"] = build_evidence_snapshot(evidence)["evidence_snapshot_hash"]
    context = auth_client.get(f"/api/applications/{application.id}/jt5/reconciliation").json()
    assert context["confirmation_evidence"] == []
    assert _resolve(auth_client, application, data).status_code == 409


def test_rejected_snapshot_is_excluded_from_recovery_choices(auth_client, db_session, recovery):
    application, _, evidence, data = recovery
    db_session.add(SubmissionEvidenceReview(
        application_id=application.id, evidence_id=evidence.id, reviewer_user_id=application.user_id,
        decision="rejected", evidence_snapshot_hash=data["evidence_snapshot_hash"],
    ))
    db_session.commit()
    context = auth_client.get(f"/api/applications/{application.id}/jt5/reconciliation").json()
    assert context["confirmation_evidence"] == []
    assert _resolve(auth_client, application, data).status_code == 409


@pytest.mark.parametrize("state", ["needs_review", "failed"])
def test_incompatible_state_exposes_blocker_instead_of_action(auth_client, db_session, recovery, state):
    application, _, _, data = recovery
    application.automation_state = state
    db_session.commit()
    context = auth_client.get(f"/api/applications/{application.id}/jt5/reconciliation").json()
    assert context["resolution_required"] is True
    assert context["confirmation_evidence"] == []
    assert context["resolution_available"] is False
    assert context["blockers"]
    assert _resolve(auth_client, application, data).status_code == 409


def test_reference_must_identify_selected_evidence(auth_client, recovery):
    application, _, _, data = recovery
    data["evidence_reference"] = "some-other-evidence"
    assert _resolve(auth_client, application, data).status_code == 409
