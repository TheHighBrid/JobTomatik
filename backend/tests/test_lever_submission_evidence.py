from datetime import datetime, timedelta

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services.application_state import record_submission_evidence
from app.services.platform_submission_evidence import (
    build_platform_evidence_review_preflight,
    build_platform_supervised_pilot_record,
    review_platform_submission_evidence,
)


SITE = "lever-pilot"
POSTING_ID = "12345678-1234-1234-1234-123456789abc"
CANONICAL_URL = f"https://jobs.lever.co/{SITE}/{POSTING_ID}/apply"
CONFIRMATION_URL = f"https://jobs.lever.co/{SITE}/thank-you"
IDENTITY = {
    "platform": "lever",
    "adapter": "lever",
    "adapter_version": "1.1.0",
    "site": SITE,
    "posting_id": POSTING_ID,
    "region": "global",
    "canonical_application_url": CANONICAL_URL,
    "posting_metadata_hash": "9" * 64,
    "identity_hash": "8" * 64,
    "verified": True,
    "blockers": [],
}


def _fixture(
    db_session,
    *,
    final_url=CANONICAL_URL,
    confirmation_text="Thank you for applying",
    payload_hash="5" * 64,
    evidence_metadata=None,
):
    user = User(
        email="lever-evidence@example.test",
        hashed_password="not-used",
        full_name="Lever Evidence Reviewer",
        resume_path="/tmp/lever-evidence.pdf",
        profile_data={},
    )
    job = Job(
        external_id=POSTING_ID,
        title="Fraud Operations Analyst",
        company="Lever Pilot Employer",
        url=CANONICAL_URL,
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": CANONICAL_URL,
            "supervised_target_metadata": IDENTITY,
        },
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applied,
        automation_state=ApplicationAutomationState.submitted.value,
        submission_idempotency_key="application:lever:evidence:1",
        submission_attempt_count=1,
        last_submission_attempt_at=datetime.utcnow(),
        cover_letter="Prepared cover letter",
    )
    db_session.add(application)
    db_session.flush()
    approval = SubmissionApproval(
        application_id=application.id,
        user_id=user.id,
        platform="lever",
        status=SubmissionApprovalStatus.consumed.value,
        employer=job.company,
        role=job.title,
        application_url=CANONICAL_URL,
        submission_idempotency_key=application.submission_idempotency_key,
        profile_snapshot_hash="1" * 64,
        resume_hash="2" * 64,
        cover_letter_hash="3" * 64,
        answer_payload_hash="4" * 64,
        combined_payload_hash="5" * 64,
        approved_at=datetime.utcnow() - timedelta(minutes=2),
        expires_at=datetime.utcnow() + timedelta(minutes=20),
        consumed_at=datetime.utcnow() - timedelta(minutes=1),
        approval_metadata={
            "policy_count": 3,
            "adapter_version": "1.1.0",
            "target_identity_hash": IDENTITY["identity_hash"],
            "target_identity": IDENTITY,
        },
    )
    db_session.add(approval)
    db_session.flush()
    metadata = {
        "source": "lever_confirmation",
        "adapter": "lever",
        "adapter_version": "1.1.0",
    }
    metadata.update(dict(evidence_metadata or {}))
    evidence = record_submission_evidence(
        db_session,
        application,
        "confirmation_page",
        is_sufficient=True,
        final_url=final_url,
        confirmation_text=confirmation_text,
        screenshot_path="evidence/lever-confirmation.png",
        payload_hash=payload_hash,
        metadata=metadata,
    )
    db_session.flush()
    db_session.commit()
    return user, job, application, approval, evidence


def _review(db_session, user, job, application, evidence):
    return review_platform_submission_evidence(
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
        review_acknowledgement="REVIEWED",
        notes="Lever confirmation independently reviewed",
    )


def test_lever_evidence_is_bound_to_consumed_approval_and_exact_target(db_session):
    user, job, application, approval, evidence = _fixture(db_session)

    assert evidence.payload_hash == approval.combined_payload_hash
    assert evidence.evidence_metadata["platform"] == "lever"
    assert evidence.evidence_metadata["adapter"] == "lever"
    assert evidence.evidence_metadata["adapter_version"] == "1.1.0"
    assert evidence.evidence_metadata["expected_adapter_version"] == "1.1.0"
    assert evidence.evidence_metadata["expected_combined_payload_hash"] == approval.combined_payload_hash
    assert evidence.evidence_metadata["approval_reference"] == approval.reference
    assert evidence.evidence_metadata["site"] == SITE
    assert evidence.evidence_metadata["posting_id"] == POSTING_ID
    assert evidence.evidence_metadata["region"] == "global"
    assert evidence.evidence_metadata["target_identity_hash"] == IDENTITY["identity_hash"]

    preflight = build_platform_evidence_review_preflight(
        db_session, application, job, evidence
    )
    assert preflight["ready_for_acceptance"] is True
    assert preflight["blockers"] == []
    assert preflight["platform"] == "lever"

    review = _review(db_session, user, job, application, evidence)
    db_session.commit()
    db_session.refresh(application)
    assert application.automation_state == ApplicationAutomationState.confirmed.value

    record = build_platform_supervised_pilot_record(
        db_session, application, user, job
    )
    assert record["run_id"].startswith("lv-supervised-")
    assert record["platform"] == "lever"
    assert record["adapter"] == "lever"
    assert record["adapter_version"] == "1.1.0"
    assert record["site"] == SITE
    assert record["posting_id"] == POSTING_ID
    assert record["region"] == "global"
    assert record["canonical_application_url"] == CANONICAL_URL
    assert record["combined_payload_hash"] == approval.combined_payload_hash
    assert record["review_reference"] == review.reference


def test_capture_preserves_supplied_payload_and_metadata_drift(db_session):
    supplied_payload = "0" * 64
    supplied_metadata_payload = "a" * 64
    user, job, application, approval, evidence = _fixture(
        db_session,
        payload_hash=supplied_payload,
        evidence_metadata={
            "platform": "greenhouse",
            "combined_payload_hash": supplied_metadata_payload,
            "approval_reference": "wrong-approval",
            "posting_id": "wrong-posting",
        },
    )

    assert evidence.payload_hash == supplied_payload
    assert evidence.payload_hash != approval.combined_payload_hash
    assert evidence.evidence_metadata["platform"] == "greenhouse"
    assert evidence.evidence_metadata["combined_payload_hash"] == supplied_metadata_payload
    assert evidence.evidence_metadata["approval_reference"] == "wrong-approval"
    assert evidence.evidence_metadata["posting_id"] == "wrong-posting"
    assert evidence.evidence_metadata["expected_combined_payload_hash"] == approval.combined_payload_hash

    preflight = build_platform_evidence_review_preflight(
        db_session, application, job, evidence
    )
    assert preflight["ready_for_acceptance"] is False
    assert "lever_evidence_payload_hash_mismatch" in preflight["blockers"]
    assert "lever_evidence_metadata_payload_hash_mismatch" in preflight["blockers"]
    assert "lever_evidence_platform_mismatch" in preflight["blockers"]
    assert "lever_evidence_approval_reference_mismatch" in preflight["blockers"]
    assert "lever_evidence_posting_id_mismatch" in preflight["blockers"]

    review = _review(db_session, user, job, application, evidence)
    db_session.commit()
    assert review.decision == "rejected"
    assert "lever_evidence_payload_hash_mismatch" in review.review_metadata["platform_blockers"]


def test_strong_same_site_confirmation_route_is_accepted(db_session):
    user, job, application, _, evidence = _fixture(
        db_session,
        final_url=CONFIRMATION_URL,
        confirmation_text="Thank you for applying",
    )

    preflight = build_platform_evidence_review_preflight(
        db_session, application, job, evidence
    )
    assert preflight["ready_for_acceptance"] is True
    assert "lever_evidence_final_url_posting_mismatch" not in preflight["blockers"]


def test_same_site_route_without_concrete_confirmation_is_blocked(db_session):
    user, job, application, _, evidence = _fixture(
        db_session,
        final_url=CONFIRMATION_URL,
        confirmation_text="",
    )
    evidence.screenshot_path = None
    db_session.commit()

    preflight = build_platform_evidence_review_preflight(
        db_session, application, job, evidence
    )
    assert preflight["ready_for_acceptance"] is False
    assert "concrete_confirmation_signal_missing" in preflight["blockers"]
    assert "lever_evidence_final_url_posting_mismatch" in preflight["blockers"]


def test_lever_evidence_drift_is_rejected_and_creates_manual_review(db_session):
    user, job, application, approval, evidence = _fixture(db_session)
    evidence.payload_hash = "0" * 64
    metadata = dict(evidence.evidence_metadata or {})
    metadata["posting_id"] = "wrong-posting"
    metadata["approval_reference"] = "wrong-approval"
    evidence.evidence_metadata = metadata
    db_session.commit()

    preflight = build_platform_evidence_review_preflight(
        db_session, application, job, evidence
    )
    assert preflight["ready_for_acceptance"] is False
    assert "lever_evidence_payload_hash_mismatch" in preflight["blockers"]
    assert "lever_evidence_posting_id_mismatch" in preflight["blockers"]
    assert "lever_evidence_approval_reference_mismatch" in preflight["blockers"]

    review = _review(db_session, user, job, application, evidence)
    db_session.commit()
    db_session.refresh(application)

    assert review.decision == "rejected"
    assert review.review_metadata["requested_decision"] == "accepted"
    assert "lever_evidence_payload_hash_mismatch" in review.review_metadata["platform_blockers"]
    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value

    manual_review = (
        db_session.query(ManualReviewTask)
        .filter(ManualReviewTask.application_id == application.id)
        .one()
    )
    assert manual_review.status == ManualReviewStatus.open.value
    assert manual_review.details["review_reference"] == review.reference


def test_observed_adapter_version_mismatch_is_not_overwritten(db_session):
    user, job, application, _, evidence = _fixture(
        db_session,
        evidence_metadata={"adapter_version": "0.9.0"},
    )

    assert evidence.evidence_metadata["adapter_version"] == "0.9.0"
    assert evidence.evidence_metadata["expected_adapter_version"] == "1.1.0"
    preflight = build_platform_evidence_review_preflight(
        db_session, application, job, evidence
    )
    assert preflight["ready_for_acceptance"] is False
    assert "lever_evidence_adapter_version_mismatch" in preflight["blockers"]


def test_greenhouse_base_review_behavior_remains_available(db_session):
    user = User(
        email="greenhouse-compat@example.test",
        hashed_password="not-used",
        full_name="Greenhouse Reviewer",
        profile_data={},
    )
    job = Job(
        external_id="greenhouse-compat-1",
        title="Analyst",
        company="Greenhouse Employer",
        url="https://job-boards.greenhouse.io/compat/jobs/1",
        raw_data={"application_method": "external_url"},
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applied,
        automation_state=ApplicationAutomationState.submitted.value,
        submission_idempotency_key="application:greenhouse:compat:1",
    )
    db_session.add(application)
    db_session.flush()
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
        approval_metadata={"policy_count": 1},
    )
    evidence = SubmissionEvidence(
        application_id=application.id,
        evidence_type="confirmation_page",
        is_sufficient=True,
        final_url=job.url,
        confirmation_text="Thank you for applying",
        screenshot_path="evidence/greenhouse.png",
        payload_hash="legacy-greenhouse-payload",
        evidence_metadata={"source": "greenhouse_confirmation"},
    )
    db_session.add_all([approval, evidence])
    db_session.flush()

    preflight = build_platform_evidence_review_preflight(
        db_session, application, job, evidence
    )
    assert preflight["ready_for_acceptance"] is True
    assert preflight["blockers"] == []
