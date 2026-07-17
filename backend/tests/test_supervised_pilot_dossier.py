import json
from datetime import datetime, timedelta

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.submission_evidence_review import SubmissionEvidenceReview
from app.models.user import User
from app.services.supervised_pilot_dossier import (
    SupervisedPilotDossierError,
    build_supervised_pilot_dossier,
)


def _fixture(db_session, tmp_path, *, greenhouse=True):
    resume = tmp_path / "phase-b-dossier.pdf"
    resume.write_bytes(b"%PDF-1.4\nphase-b-dossier\n")
    user = User(
        email="phase-b-dossier@example.test",
        hashed_password="not-used",
        full_name="Phase B Dossier",
        phone="6135550199",
        resume_path=str(resume),
        profile_data={"secret_profile_value": "profile-secret-do-not-copy"},
    )
    job = Job(
        external_id="phase-b-dossier-job",
        company="Dossier Employer",
        title="Dossier Role",
        url=(
            "https://job-boards.greenhouse.io/dossier/jobs/123"
            if greenhouse
            else "https://jobs.lever.co/dossier/123"
        ),
        raw_data={"application_method": "external_url"},
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        submission_idempotency_key="application:dossier:123",
        submission_attempt_count=0,
        cover_letter="Prepared cover letter with private prose",
    )
    db_session.add(application)
    db_session.flush()
    return user, job, application


def _readiness(confirmed=0):
    return {
        "summary": {
            "qualifying_dry_run_count": 30,
            "distinct_dry_run_employer_count": 30,
            "supervised_confirmed_count": confirmed,
        }
    }


def test_dossier_is_deterministic_and_excludes_raw_sensitive_values(db_session, tmp_path):
    user, job, application = _fixture(db_session, tmp_path)
    db_session.add(
        ManualReviewTask(
            application_id=application.id,
            reason_code="ambiguous_question",
            status="open",
            summary="secret legal answer must never enter dossier",
            details={"raw_answer": "manual-review-secret"},
        )
    )
    evidence = SubmissionEvidence(
        application_id=application.id,
        evidence_type="confirmation_page",
        is_sufficient=True,
        final_url="https://job-boards.greenhouse.io/dossier/confirmation",
        confirmation_text="sensitive confirmation body",
        screenshot_path="evidence/confirmation.png",
        payload_hash="e" * 64,
        evidence_metadata={"raw_page": "evidence-secret"},
    )
    db_session.add(evidence)
    db_session.flush()
    approval = SubmissionApproval(
        application_id=application.id,
        user_id=user.id,
        platform="greenhouse",
        status="consumed",
        employer=job.company,
        role=job.title,
        application_url=job.url,
        submission_idempotency_key=application.submission_idempotency_key,
        profile_snapshot_hash="1" * 64,
        resume_hash="2" * 64,
        cover_letter_hash="3" * 64,
        answer_payload_hash="4" * 64,
        combined_payload_hash="5" * 64,
        expires_at=datetime.utcnow() + timedelta(minutes=20),
        consumed_at=datetime.utcnow(),
        notes="private approval notes",
        approval_metadata={"raw_answer": "approval-secret"},
    )
    db_session.add(approval)
    db_session.flush()
    db_session.add(
        SubmissionEvidenceReview(
            application_id=application.id,
            evidence_id=evidence.id,
            reviewer_user_id=user.id,
            approval_reference=approval.reference,
            decision="accepted",
            evidence_snapshot_hash="6" * 64,
            application_payload_hash="5" * 64,
            review_notes="private review notes",
            review_metadata={"raw_answer": "review-secret"},
        )
    )
    db_session.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="submission_evidence_captured",
            from_state="submitted",
            to_state="submitted",
            payload={"raw_answer": "event-secret"},
        )
    )
    db_session.commit()

    first = build_supervised_pilot_dossier(
        db_session, application, user, job, readiness=_readiness(confirmed=2)
    )
    second = build_supervised_pilot_dossier(
        db_session, application, user, job, readiness=_readiness(confirmed=2)
    )

    assert first["dossier_sha256"] == second["dossier_sha256"]
    assert len(first["dossier_sha256"]) == 64
    assert first["read_only"] is True
    assert first["selection_policy"] == "user_selected_exact_application_no_ranking"
    assert first["exact_payload"]["raw_answer_values_included"] is False
    assert first["preflight"]["technical_ready"] is False
    assert first["preflight"]["open_manual_review_reasons"] == ["ambiguous_question"]
    assert first["submission_evidence_state"]["sufficient_count"] == 1
    assert first["independent_review_state"]["accepted_count"] == 1
    assert first["pilot_progress"]["phase_a_complete"] is True
    assert first["pilot_progress"]["phase_b_remaining"] == 8

    serialized = json.dumps(first, sort_keys=True)
    for forbidden in [
        "6135550199",
        "profile-secret-do-not-copy",
        "Prepared cover letter with private prose",
        "secret legal answer must never enter dossier",
        "manual-review-secret",
        "sensitive confirmation body",
        "evidence-secret",
        "private approval notes",
        "approval-secret",
        "private review notes",
        "review-secret",
        "event-secret",
    ]:
        assert forbidden not in serialized


def test_dossier_digest_changes_when_exact_payload_changes(db_session, tmp_path):
    user, job, application = _fixture(db_session, tmp_path)
    db_session.commit()

    before = build_supervised_pilot_dossier(db_session, application, user, job)
    application.cover_letter = "A different exact cover letter"
    db_session.commit()
    db_session.refresh(application)
    after = build_supervised_pilot_dossier(db_session, application, user, job)

    assert before["exact_payload"]["combined_payload_hash"] != after["exact_payload"]["combined_payload_hash"]
    assert before["dossier_sha256"] != after["dossier_sha256"]


def test_dossier_rejects_non_greenhouse_application(db_session, tmp_path):
    user, job, application = _fixture(db_session, tmp_path, greenhouse=False)
    db_session.commit()

    with pytest.raises(SupervisedPilotDossierError, match="only for Greenhouse"):
        build_supervised_pilot_dossier(db_session, application, user, job)


def test_dossier_endpoint_is_authenticated_owned_and_read_only(auth_client, db_session, tmp_path):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    resume = tmp_path / "endpoint-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nendpoint\n")
    user.resume_path = str(resume)
    job = Job(
        external_id="phase-b-endpoint-job",
        company="Endpoint Employer",
        title="Endpoint Role",
        url="https://job-boards.greenhouse.io/endpoint/jobs/456",
        raw_data={"application_method": "external_url"},
    )
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        submission_idempotency_key="application:endpoint:456",
        cover_letter="Endpoint cover letter",
    )
    db_session.add(application)
    db_session.commit()

    response = auth_client.get(
        f"/api/supervised-pilot/applications/{application.id}/dossier"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["application_id"] == application.id
    assert payload["target"]["employer"] == "Endpoint Employer"
    assert payload["read_only"] is True
    assert payload["kill_switches"]["global_flag_enabled"] is False
    assert payload["kill_switches"]["platform_flag_enabled"] is False
    assert payload["pilot_progress"]["phase_a_qualifying_dry_runs"] == 30
    assert payload["pilot_progress"]["phase_a_distinct_employers"] == 30
