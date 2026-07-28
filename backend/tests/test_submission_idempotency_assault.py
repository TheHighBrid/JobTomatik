from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import time

from sqlalchemy.exc import OperationalError

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    SubmissionEvidence,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.submission_integrity import (
    SubmissionAttempt,
    SubmissionAttemptStatus,
    SubmissionEvidenceReceipt,
    SubmissionIdentityAlias,
)
from app.models.user import User
from app.services.submission_integrity import (
    DuplicateSubmissionIdentityError,
    SubmissionAttemptReservationError,
    approval_submission_binding_hash,
    build_submission_identity_aliases,
    claim_submission_attempt,
    claim_submission_identity_aliases,
    finalize_submission_attempt,
    find_existing_application_for_aliases,
    prepare_submission_evidence_receipt,
    register_submission_evidence_receipt,
    reserve_submission_attempt,
    submission_attempt_replay_result,
)
from tests.conftest import TestingSessionLocal


def _user(db, *, email="idempotency@example.com"):
    item = User(
        email=email,
        hashed_password="not-used-in-test",
        full_name="Idempotency Candidate",
    )
    db.add(item)
    db.flush()
    return item


def _job(
    db,
    *,
    title="Fraud Investigator",
    company="Example Bank",
    url="https://jobs.example.test/apply",
    external_id=None,
    metadata=None,
):
    raw_data = {}
    if metadata is not None:
        raw_data["supervised_target_metadata"] = metadata
    item = Job(
        external_id=external_id,
        title=title,
        company=company,
        url=url,
        source=JobSource.manual,
        status=JobStatus.approved,
        raw_data=raw_data,
    )
    db.add(item)
    db.flush()
    return item


def _application(db, user, job, *, key=None):
    item = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        source_listing_url=job.url,
        submission_idempotency_key=key or f"test:{user.id}:{job.id}",
    )
    db.add(item)
    db.flush()
    claim_submission_identity_aliases(
        db,
        item,
        build_submission_identity_aliases(job, application=item),
    )
    return item


def _approval(db, user, application, *, reference="lvsup-day-five"):
    now = datetime.utcnow()
    item = SubmissionApproval(
        reference=reference,
        application_id=application.id,
        user_id=user.id,
        platform="lever",
        status=SubmissionApprovalStatus.active.value,
        employer="Example Bank",
        role="Fraud Investigator",
        application_url="https://jobs.lever.co/example/posting-1/apply",
        submission_idempotency_key=application.submission_idempotency_key,
        profile_snapshot_hash="1" * 64,
        resume_hash="2" * 64,
        cover_letter_hash="3" * 64,
        answer_payload_hash="4" * 64,
        combined_payload_hash="5" * 64,
        approved_at=now,
        expires_at=now + timedelta(minutes=20),
        approval_metadata={
            "adapter_version": "lever-v1",
            "target_identity_hash": "6" * 64,
        },
    )
    db.add(item)
    db.flush()
    item.approval_metadata = {
        **dict(item.approval_metadata or {}),
        "submission_binding_hash": approval_submission_binding_hash(item),
    }
    return item


def _lever_identity(*, canonical_url, posting_id="posting-1"):
    return {
        "platform": "lever",
        "adapter": "lever",
        "adapter_version": "lever-v1",
        "verified": True,
        "site": "example",
        "posting_id": posting_id,
        "region": "global",
        "canonical_application_url": canonical_url,
        "posting_metadata_hash": "a" * 64,
        "identity_hash": "b" * 64,
    }


def test_changed_url_same_verified_posting_is_one_identity(db_session):
    user = _user(db_session)
    first_job = _job(
        db_session,
        url="https://jobs.lever.co/example/posting-1",
        metadata=_lever_identity(
            canonical_url="https://jobs.lever.co/example/posting-1/apply"
        ),
    )
    first = _application(db_session, user, first_job)

    second_job = _job(
        db_session,
        url="https://jobs.eu.lever.co/example/posting-1?lever-source=redirect",
        metadata=_lever_identity(
            canonical_url="https://jobs.eu.lever.co/example/posting-1/apply"
        ),
    )
    second_aliases = build_submission_identity_aliases(second_job)

    existing = find_existing_application_for_aliases(
        db_session,
        user.id,
        second_aliases,
    )
    assert existing.id == first.id

    second = Application(
        user_id=user.id,
        job_id=second_job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        submission_idempotency_key=f"test:{user.id}:{second_job.id}",
    )
    db_session.add(second)
    db_session.flush()
    try:
        claim_submission_identity_aliases(db_session, second, second_aliases)
    except DuplicateSubmissionIdentityError as exc:
        assert exc.existing_application_id == first.id
        assert exc.alias_type == "verified_platform_posting"
    else:
        raise AssertionError("same verified posting was not rejected")


def test_same_url_changed_posting_remains_distinct(db_session):
    user = _user(db_session)
    first_job = _job(
        db_session,
        title="Fraud Investigator",
        url="https://careers.example.test/apply",
    )
    first = _application(db_session, user, first_job)

    second_job = _job(
        db_session,
        title="AML Analyst",
        url="https://careers.example.test/apply",
    )
    aliases = build_submission_identity_aliases(second_job)

    assert find_existing_application_for_aliases(db_session, user.id, aliases) is None
    second = _application(db_session, user, second_job)
    assert second.id != first.id


def test_api_collapses_duplicate_job_rows_with_same_posting(auth_client, db_session):
    first_job = _job(
        db_session,
        url="https://jobs.lever.co/example/posting-1",
        metadata=_lever_identity(
            canonical_url="https://jobs.lever.co/example/posting-1/apply"
        ),
    )
    second_job = _job(
        db_session,
        url="https://jobs.lever.co/example/posting-1?utm_source=mirror",
        metadata=_lever_identity(
            canonical_url="https://jobs.lever.co/example/posting-1/apply?lever-source=mirror"
        ),
    )
    db_session.commit()

    first = auth_client.post(
        "/api/applications",
        json={"job_id": first_job.id, "cover_letter": "Reviewed letter"},
    )
    second = auth_client.post(
        "/api/applications",
        json={"job_id": second_job.id, "cover_letter": "Reviewed letter"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert db_session.query(Application).count() == 1
    assert db_session.query(SubmissionIdentityAlias).count() >= 1


def test_confirmation_evidence_replay_returns_existing_evidence(db_session):
    user = _user(db_session)
    job = _job(db_session)
    application = _application(db_session, user, job)

    fingerprint, existing = prepare_submission_evidence_receipt(
        db_session,
        application,
        evidence_type="confirmation_email",
        final_url="https://careers.example.test/thanks",
        confirmation_text="Application received",
        external_application_id="message-123",
        payload_hash="payload-123",
        metadata={"platform": "email"},
    )
    assert existing is None
    evidence = SubmissionEvidence(
        application_id=application.id,
        evidence_type="confirmation_email",
        is_sufficient=True,
        final_url="https://careers.example.test/thanks",
        confirmation_text="Application received",
        external_application_id="message-123",
        payload_hash="payload-123",
        evidence_metadata={"platform": "email"},
    )
    db_session.add(evidence)
    db_session.flush()
    register_submission_evidence_receipt(
        db_session,
        application,
        evidence,
        fingerprint=fingerprint,
        evidence_type="confirmation_email",
        final_url=evidence.final_url,
        external_application_id=evidence.external_application_id,
        payload_hash=evidence.payload_hash,
        metadata=evidence.evidence_metadata,
    )

    repeated_fingerprint, repeated = prepare_submission_evidence_receipt(
        db_session,
        application,
        evidence_type="confirmation_email",
        final_url=evidence.final_url,
        confirmation_text=evidence.confirmation_text,
        external_application_id=evidence.external_application_id,
        payload_hash=evidence.payload_hash,
        metadata=evidence.evidence_metadata,
    )
    assert repeated_fingerprint == fingerprint
    assert repeated.id == evidence.id
    assert db_session.query(SubmissionEvidenceReceipt).count() == 1


def test_confirmation_receipt_cannot_attach_to_another_application(db_session):
    user = _user(db_session)
    first = _application(db_session, user, _job(db_session, title="Role One"))
    second = _application(
        db_session,
        user,
        _job(db_session, title="Role Two", url="https://jobs.example.test/role-two"),
    )

    fingerprint, _ = prepare_submission_evidence_receipt(
        db_session,
        first,
        evidence_type="confirmation_email",
        final_url="https://careers.example.test/thanks",
        confirmation_text="Application received",
        external_application_id="shared-message-id",
        payload_hash=None,
        metadata={"platform": "email"},
    )
    evidence = SubmissionEvidence(
        application_id=first.id,
        evidence_type="confirmation_email",
        is_sufficient=True,
        external_application_id="shared-message-id",
        evidence_metadata={"platform": "email"},
    )
    db_session.add(evidence)
    db_session.flush()
    register_submission_evidence_receipt(
        db_session,
        first,
        evidence,
        fingerprint=fingerprint,
        evidence_type="confirmation_email",
        final_url=None,
        external_application_id="shared-message-id",
        payload_hash=None,
        metadata={"platform": "email"},
    )

    try:
        prepare_submission_evidence_receipt(
            db_session,
            second,
            evidence_type="confirmation_email",
            final_url="https://careers.example.test/thanks",
            confirmation_text="Application received",
            external_application_id="shared-message-id",
            payload_hash=None,
            metadata={"platform": "email"},
        )
    except DuplicateSubmissionIdentityError as exc:
        assert exc.existing_application_id == first.id
        assert exc.alias_type == "confirmation_evidence"
    else:
        raise AssertionError("reused confirmation receipt was not rejected")


def test_same_approval_reserves_only_one_queue_attempt(db_session):
    user = _user(db_session)
    application = _application(db_session, user, _job(db_session))
    approval = _approval(db_session, user, application)

    first, first_created = reserve_submission_attempt(
        db_session,
        application,
        approval,
        task_id="task-one",
    )
    second, second_created = reserve_submission_attempt(
        db_session,
        application,
        approval,
        task_id="task-two",
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert second.task_id == "task-one"
    assert db_session.query(SubmissionAttempt).count() == 1


def test_different_approval_cannot_overlap_active_attempt(db_session):
    user = _user(db_session)
    application = _application(db_session, user, _job(db_session))
    first_approval = _approval(db_session, user, application, reference="lvsup-first")
    reserve_submission_attempt(
        db_session,
        application,
        first_approval,
        task_id="task-one",
    )
    second_approval = _approval(db_session, user, application, reference="lvsup-second")

    try:
        reserve_submission_attempt(
            db_session,
            application,
            second_approval,
            task_id="task-two",
        )
    except SubmissionAttemptReservationError as exc:
        assert "active submission attempt" in str(exc)
    else:
        raise AssertionError("overlapping attempt was not rejected")


def test_two_database_workers_only_one_claims_the_attempt(db_session):
    user = _user(db_session)
    application = _application(db_session, user, _job(db_session))
    approval = _approval(db_session, user, application)
    attempt, _ = reserve_submission_attempt(
        db_session,
        application,
        approval,
        task_id="race-task",
    )
    db_session.commit()

    def claim_once():
        for retry in range(2):
            session = TestingSessionLocal()
            try:
                app = session.query(Application).filter(Application.id == application.id).first()
                item = session.query(SubmissionApproval).filter(
                    SubmissionApproval.id == approval.id
                ).first()
                claimed_attempt, claimed = claim_submission_attempt(
                    session,
                    app,
                    item,
                    attempt_reference=attempt.reference,
                )
                session.commit()
                return claimed, claimed_attempt.status
            except OperationalError:
                session.rollback()
                if retry == 0:
                    time.sleep(0.05)
                    continue
                raise
            finally:
                session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim_once(), range(2)))

    assert sum(1 for claimed, _ in results if claimed) == 1
    assert all(status == SubmissionAttemptStatus.in_progress.value for _, status in results)


def test_succeeded_attempt_replay_never_repeats_final_action(db_session):
    user = _user(db_session)
    application = _application(db_session, user, _job(db_session))
    approval = _approval(db_session, user, application)
    attempt, _ = reserve_submission_attempt(
        db_session,
        application,
        approval,
        task_id="completed-task",
    )
    claimed, is_owner = claim_submission_attempt(
        db_session,
        application,
        approval,
        attempt_reference=attempt.reference,
    )
    assert is_owner is True
    finalize_submission_attempt(
        db_session,
        claimed,
        status=SubmissionAttemptStatus.succeeded,
        result={"confirmation": "accepted"},
    )
    db_session.flush()

    replay, second_owner = claim_submission_attempt(
        db_session,
        application,
        approval,
        attempt_reference=attempt.reference,
    )
    result = submission_attempt_replay_result(replay)

    assert second_owner is False
    assert result["idempotent"] is True
    assert result["duplicate_final_action_prevented"] is True
    assert result["automatic_retry_allowed"] is False
    assert result["attempt_status"] == SubmissionAttemptStatus.succeeded.value


def test_approval_binding_detects_documents_answers_adapter_and_context_changes(db_session):
    user = _user(db_session)
    application = _application(db_session, user, _job(db_session))
    approval = _approval(db_session, user, application)
    original = approval_submission_binding_hash(approval)

    approval.resume_hash = "7" * 64
    assert approval_submission_binding_hash(approval) != original
    approval.resume_hash = "2" * 64

    approval.answer_payload_hash = "8" * 64
    assert approval_submission_binding_hash(approval) != original
    approval.answer_payload_hash = "4" * 64

    approval.approval_metadata = {
        **dict(approval.approval_metadata or {}),
        "adapter_version": "lever-v2",
    }
    assert approval_submission_binding_hash(approval) != original


def test_queue_endpoint_double_click_returns_same_reservation(
    auth_client,
    db_session,
    monkeypatch,
):
    user = db_session.query(User).filter(User.email == "test@example.com").first()
    job = _job(db_session)
    application = _application(db_session, user, job)
    approval = _approval(db_session, user, application)
    db_session.commit()

    monkeypatch.setattr(
        "app.api.supervised_submissions.validate_supervised_approval",
        lambda *args, **kwargs: approval,
    )
    first = auth_client.post(
        f"/api/supervised-submissions/applications/{application.id}/approvals/{approval.reference}/submit"
    )
    second = auth_client.post(
        f"/api/supervised-submissions/applications/{application.id}/approvals/{approval.reference}/submit"
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["attempt_reference"] == first.json()["attempt_reference"]
    assert second.json()["task_id"] == first.json()["task_id"]
    assert second.json()["idempotent"] is True
    assert second.json()["duplicate_final_action_prevented"] is True
    assert db_session.query(SubmissionAttempt).count() == 1
