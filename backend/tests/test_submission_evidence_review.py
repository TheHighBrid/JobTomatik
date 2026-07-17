from datetime import datetime, timedelta

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.submission_evidence_review import SubmissionEvidenceReview
from app.models.user import User
from app.services.submission_evidence_review import (
    SubmissionEvidenceReviewError,
    build_evidence_review_preflight,
    build_supervised_pilot_record,
    review_submission_evidence,
)


def _fixture(db_session, *, evidence_sufficient=True, with_approval=True):
    user = User(
        email="pilot-review@example.test",
        hashed_password="not-used",
        full_name="Pilot Reviewer",
        resume_path="/tmp/pilot-review-resume.pdf",
        profile_data={},
    )
    job = Job(
        external_id="greenhouse-review-1",
        title="Fraud Analyst",
        company="Evidence Employer",
        url="https://job-boards.greenhouse.io/evidence/jobs/1",
        raw_data={"application_method": "external_url"},
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applied,
        automation_state=ApplicationAutomationState.submitted.value,
        submission_idempotency_key="application:review:1",
        submission_attempt_count=1,
        last_submission_attempt_at=datetime.utcnow(),
        cover_letter="Prepared cover letter",
    )
    db_session.add(application)
    db_session.flush()
    evidence = SubmissionEvidence(
        application_id=application.id,
        evidence_type="confirmation_page",
        is_sufficient=evidence_sufficient,
        final_url="https://job-boards.greenhouse.io/evidence/confirmation",
        confirmation_text="Thank you for applying",
        screenshot_path="evidence/confirmation.png",
        payload_hash="e" * 64,
        evidence_metadata={"source": "greenhouse_confirmation"},
    )
    db_session.add(evidence)
    db_session.flush()

    approval = None
    if with_approval:
        approval = SubmissionApproval(
            application_id=application.id,
            user_id=user.id,
            platform="greenhouse",
            status=SubmissionApprovalStatus.consumed.value,
            employer=job.company,
            role=job.title,
            application_url=job.url,
            submission_idempotency_key=application.submission_idempotency_key,
            profile_snapshot_hash="1" * 64,
            resume_hash="2" * 64,
            cover_letter_hash="3" * 64,
            answer_payload_hash="4" * 64,
            combined_payload_hash="5" * 64,
            approved_at=datetime.utcnow() - timedelta(minutes=2),
            expires_at=datetime.utcnow() + timedelta(minutes=20),
            consumed_at=datetime.utcnow() - timedelta(minutes=1),
            approval_metadata={"policy_count": 3},
        )
        db_session.add(approval)
        db_session.flush()
    db_session.commit()
    return user, job, application, evidence, approval


def _review(db_session, user, job, application, evidence, decision="accepted"):
    return review_submission_evidence(
        db_session,
        application,
        user,
        job,
        evidence,
        decision=decision,
        confirm_employer=job.company,
        confirm_role=job.title,
        confirm_evidence_type=evidence.evidence_type,
        confirm_evidence_matches_application=True,
        review_acknowledgement="REVIEWED",
        notes="Independent confirmation review",
    )


def test_acceptance_confirms_application_and_exports_pilot_record(db_session):
    user, job, application, evidence, approval = _fixture(db_session)

    preflight = build_evidence_review_preflight(db_session, application, job, evidence)
    assert preflight["ready_for_acceptance"] is True
    assert preflight["approval_reference"] == approval.reference
    assert "confirmation_text" not in preflight["evidence"]
    assert len(preflight["evidence"]["confirmation_text_hash"]) == 64

    review = _review(db_session, user, job, application, evidence)
    db_session.commit()
    db_session.refresh(application)
    db_session.refresh(review)

    assert application.automation_state == ApplicationAutomationState.confirmed.value
    assert review.decision == "accepted"
    assert review.approval_reference == approval.reference

    record = build_supervised_pilot_record(db_session, application, user, job)
    assert record["mode"] == "supervised_real_submission"
    assert record["final_status"] == "confirmed"
    assert record["final_submit_clicked"] is True
    assert record["approval_reference"] == approval.reference
    assert record["review_reference"] == review.reference
    assert record["duplicate_guard_verified"] is True
    assert record["synthetic_profile"] is False


def test_review_is_idempotent_for_exact_snapshot_and_conflicting_decision_is_blocked(db_session):
    user, job, application, evidence, _ = _fixture(db_session)
    first = _review(db_session, user, job, application, evidence)
    db_session.commit()

    second = _review(db_session, user, job, application, evidence)
    assert second.id == first.id

    with pytest.raises(SubmissionEvidenceReviewError, match="conflicting review"):
        _review(db_session, user, job, application, evidence, decision="rejected")


def test_evidence_mutation_invalidates_export(db_session):
    user, job, application, evidence, _ = _fixture(db_session)
    _review(db_session, user, job, application, evidence)
    db_session.commit()

    evidence.confirmation_text = "Changed after review"
    db_session.commit()

    with pytest.raises(SubmissionEvidenceReviewError, match="No accepted review remains valid"):
        build_supervised_pilot_record(db_session, application, user, job)


def test_acceptance_fails_closed_without_consumed_approval(db_session):
    user, job, application, evidence, _ = _fixture(db_session, with_approval=False)
    preflight = build_evidence_review_preflight(db_session, application, job, evidence)
    assert preflight["ready_for_acceptance"] is False
    assert "consumed_supervised_approval_missing" in preflight["blockers"]

    with pytest.raises(SubmissionEvidenceReviewError, match="acceptance is blocked"):
        _review(db_session, user, job, application, evidence)


def test_rejected_evidence_routes_submission_to_uncertain_review(db_session):
    user, job, application, evidence, _ = _fixture(db_session, evidence_sufficient=False)
    review = _review(db_session, user, job, application, evidence, decision="rejected")
    db_session.commit()
    db_session.refresh(application)

    assert review.decision == "rejected"
    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value
    manual = (
        db_session.query(ManualReviewTask)
        .filter(ManualReviewTask.application_id == application.id)
        .first()
    )
    assert manual is not None
    assert manual.reason_code == "submission_confirmation_uncertain"


def test_exact_confirmations_and_acknowledgement_are_required(db_session):
    user, job, application, evidence, _ = _fixture(db_session)

    with pytest.raises(SubmissionEvidenceReviewError, match="REVIEWED"):
        review_submission_evidence(
            db_session,
            application,
            user,
            job,
            evidence,
            decision="accepted",
            confirm_employer=job.company,
            confirm_role=job.title,
            confirm_evidence_type=evidence.evidence_type,
            confirm_evidence_matches_application=True,
            review_acknowledgement="reviewed",
        )

    with pytest.raises(SubmissionEvidenceReviewError, match="did not match"):
        review_submission_evidence(
            db_session,
            application,
            user,
            job,
            evidence,
            decision="accepted",
            confirm_employer="Wrong employer",
            confirm_role=job.title,
            confirm_evidence_type=evidence.evidence_type,
            confirm_evidence_matches_application=True,
            review_acknowledgement="REVIEWED",
        )


def test_review_table_enforces_single_decision_per_exact_snapshot(db_session):
    user, job, application, evidence, _ = _fixture(db_session)
    review = _review(db_session, user, job, application, evidence)
    db_session.commit()

    assert db_session.query(SubmissionEvidenceReview).count() == 1
    assert review.evidence_snapshot_hash
