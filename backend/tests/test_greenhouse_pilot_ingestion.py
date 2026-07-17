import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    SubmissionEvidence,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services.greenhouse_pilot_ingestion import (
    PHASE_A_BASELINE_SHA256,
    GreenhousePilotIngestionError,
    ingest_confirmed_supervised_application,
    load_phase_a_baseline,
    read_greenhouse_pilot_readiness,
)
from app.services.submission_evidence_review import review_submission_evidence


BASELINE = Path("evidence/greenhouse-phase-a-baseline.csv")


def _confirmed_fixture(db_session):
    user = User(
        email="ledger-pilot@example.test",
        hashed_password="not-used",
        full_name="Ledger Pilot",
        resume_path="/tmp/ledger-pilot.pdf",
        profile_data={},
    )
    job = Job(
        external_id="ledger-greenhouse-1",
        title="Compliance Analyst",
        company="Ledger Employer",
        url="https://job-boards.greenhouse.io/ledger/jobs/1",
        raw_data={"application_method": "external_url"},
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applied,
        automation_state=ApplicationAutomationState.submitted.value,
        submission_idempotency_key="application:ledger:1",
        submission_attempt_count=1,
        last_submission_attempt_at=datetime.utcnow(),
        cover_letter="Prepared cover letter",
    )
    db_session.add(application)
    db_session.flush()
    evidence = SubmissionEvidence(
        application_id=application.id,
        evidence_type="confirmation_page",
        is_sufficient=True,
        final_url="https://job-boards.greenhouse.io/ledger/confirmation",
        confirmation_text="Thank you for applying",
        screenshot_path="evidence/ledger-confirmation.png",
        payload_hash="e" * 64,
        evidence_metadata={"source": "greenhouse_confirmation"},
    )
    db_session.add(evidence)
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
        approval_metadata={"policy_count": 4},
    )
    db_session.add(approval)
    db_session.flush()
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
        review_acknowledgement="REVIEWED",
        notes="Concrete confirmation independently reviewed",
    )
    db_session.commit()
    db_session.refresh(application)
    return user, job, application


def _paths(tmp_path):
    return {
        "ledger_path": tmp_path / "pilot-ledger.jsonl",
        "summary_json_path": tmp_path / "readiness.json",
        "summary_markdown_path": tmp_path / "readiness.md",
    }


def test_verified_phase_a_baseline_is_complete_and_fail_safe():
    records = load_phase_a_baseline(BASELINE)
    employers = {record["employer"].strip().lower() for record in records}

    assert len(records) == 30
    assert len(employers) == 30
    assert all(record["mode"] == "dry_run" for record in records)
    assert all(record["qualifies_for_dry_run_matrix"] is True for record in records)
    assert all(record["final_submit_clicked"] is False for record in records)
    assert all(record.get("approval_reference") is None for record in records)
    assert all(record.get("confirmation_evidence_reference") is None for record in records)


def test_phase_a_baseline_digest_is_pinned():
    import hashlib

    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == PHASE_A_BASELINE_SHA256


def test_empty_runtime_ledger_starts_at_phase_a_30_of_30(tmp_path):
    readiness = read_greenhouse_pilot_readiness(ledger_path=tmp_path / "empty.jsonl")

    assert readiness["baseline_record_count"] == 30
    assert readiness["runtime_record_count"] == 0
    assert readiness["ledger_record_count"] == 30
    assert readiness["baseline_sha256"] == PHASE_A_BASELINE_SHA256
    assert readiness["runtime_ledger_sha256"] is None
    assert len(readiness["ledger_sha256"]) == 64
    assert readiness["summary"]["qualifying_dry_run_count"] == 30
    assert readiness["summary"]["distinct_dry_run_employer_count"] == 30
    assert readiness["summary"]["supervised_confirmed_count"] == 0
    assert readiness["summary"]["human_reviewed_submit_ready"] is False


def test_ingestion_appends_runtime_record_without_rewriting_baseline(db_session, tmp_path):
    user, job, application = _confirmed_fixture(db_session)
    paths = _paths(tmp_path)
    baseline_before = BASELINE.read_bytes()

    result = ingest_confirmed_supervised_application(
        db_session,
        application,
        user,
        job,
        **paths,
    )
    db_session.commit()

    assert result["added"] is True
    assert result["record"]["mode"] == "supervised_real_submission"
    assert result["record"]["final_status"] == "confirmed"
    assert result["record"]["final_submit_clicked"] is True
    assert result["baseline_record_count"] == 30
    assert result["runtime_record_count"] == 1
    assert result["ledger_record_count"] == 31
    assert result["summary"]["qualifying_dry_run_count"] == 30
    assert result["summary"]["distinct_dry_run_employer_count"] == 30
    assert result["summary"]["supervised_confirmed_count"] == 1
    assert result["summary"]["release_approval_reference"] is None
    assert result["summary"]["human_reviewed_submit_ready"] is False
    assert BASELINE.read_bytes() == baseline_before

    lines = paths["ledger_path"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["run_id"] == result["record"]["run_id"]
    assert paths["summary_json_path"].is_file()
    assert paths["summary_markdown_path"].is_file()

    events = (
        db_session.query(ApplicationEvent)
        .filter(ApplicationEvent.event_type == "supervised_pilot_record_ingested")
        .all()
    )
    assert len(events) == 1
    assert events[0].payload["baseline_record_count"] == 30
    assert events[0].payload["runtime_record_count"] == 1


def test_exact_replay_is_idempotent_and_creates_no_duplicate_event(db_session, tmp_path):
    user, job, application = _confirmed_fixture(db_session)
    paths = _paths(tmp_path)

    first = ingest_confirmed_supervised_application(db_session, application, user, job, **paths)
    db_session.commit()
    second = ingest_confirmed_supervised_application(db_session, application, user, job, **paths)
    db_session.commit()

    assert first["added"] is True
    assert second["added"] is False
    assert second["baseline_record_count"] == 30
    assert second["runtime_record_count"] == 1
    assert second["ledger_record_count"] == 31
    assert first["ledger_sha256"] == second["ledger_sha256"]
    assert (
        db_session.query(ApplicationEvent)
        .filter(ApplicationEvent.event_type == "supervised_pilot_record_ingested")
        .count()
        == 1
    )


def test_conflicting_replay_fails_closed_and_preserves_runtime_ledger(db_session, tmp_path):
    user, job, application = _confirmed_fixture(db_session)
    paths = _paths(tmp_path)
    first = ingest_confirmed_supervised_application(db_session, application, user, job, **paths)
    db_session.commit()
    original = paths["ledger_path"].read_bytes()

    job.company = "Mutated Employer"
    db_session.commit()
    with pytest.raises(GreenhousePilotIngestionError, match="conflicting evidence"):
        ingest_confirmed_supervised_application(db_session, application, user, job, **paths)

    assert paths["ledger_path"].read_bytes() == original
    assert first["ledger_record_count"] == 31


def test_unconfirmed_application_cannot_enter_ledger(db_session, tmp_path):
    user, job, application = _confirmed_fixture(db_session)
    application.automation_state = ApplicationAutomationState.submitted.value
    db_session.commit()

    with pytest.raises(GreenhousePilotIngestionError, match="not independently confirmed"):
        ingest_confirmed_supervised_application(
            db_session,
            application,
            user,
            job,
            **_paths(tmp_path),
        )


def test_readiness_reader_merges_baseline_and_runtime_under_shared_lock(db_session, tmp_path):
    user, job, application = _confirmed_fixture(db_session)
    paths = _paths(tmp_path)
    ingest_confirmed_supervised_application(db_session, application, user, job, **paths)
    db_session.commit()

    readiness = read_greenhouse_pilot_readiness(ledger_path=paths["ledger_path"])
    assert readiness["baseline_record_count"] == 30
    assert readiness["runtime_record_count"] == 1
    assert readiness["ledger_record_count"] == 31
    assert len(readiness["ledger_sha256"]) == 64
    assert readiness["summary"]["qualifying_dry_run_count"] == 30
    assert readiness["summary"]["supervised_confirmed_count"] == 1
    assert readiness["summary"]["gates"]["explicit_release_approval_reference"] is False
