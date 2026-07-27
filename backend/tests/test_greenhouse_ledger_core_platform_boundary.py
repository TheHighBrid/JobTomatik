from datetime import datetime, timedelta

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services.greenhouse_pilot_ingestion import (
    GreenhousePilotIngestionError,
    ingest_confirmed_supervised_application,
)


def test_greenhouse_core_rejects_lever_before_record_build_or_file_write(
    db_session,
    tmp_path,
):
    user = User(
        email="lever-blocked-from-greenhouse-core@example.test",
        hashed_password="not-used",
        full_name="Ledger Boundary Reviewer",
        profile_data={},
    )
    job = Job(
        external_id="lever-core-boundary",
        title="Boundary Analyst",
        company="Boundary Employer",
        url="https://jobs.lever.co/boundary/12345678-1234-1234-1234-123456789abc/apply",
        raw_data={"application_method": "external_url"},
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applied,
        automation_state=ApplicationAutomationState.confirmed.value,
        submission_idempotency_key="application:lever:greenhouse-core-boundary",
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
        approval_metadata={},
    )
    db_session.add(approval)
    db_session.commit()

    ledger = tmp_path / "greenhouse-pilot-ledger.jsonl"
    with pytest.raises(GreenhousePilotIngestionError, match="Greenhouse approvals only"):
        ingest_confirmed_supervised_application(
            db_session,
            application,
            user,
            job,
            baseline_path=tmp_path / "missing-baseline.csv",
            ledger_path=ledger,
            summary_json_path=tmp_path / "readiness.json",
            summary_markdown_path=tmp_path / "readiness.md",
        )

    assert not ledger.exists()
