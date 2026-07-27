from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import greenhouse_pilot_ledger, pilot_ledger
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User


def _application_with_consumed_approval(db_session, *, platform: str):
    user = User(
        email=f"{platform}-ledger-boundary@example.test",
        hashed_password="not-used",
        full_name=f"{platform.title()} Ledger Boundary",
        profile_data={},
    )
    url = (
        "https://jobs.lever.co/boundary/12345678-1234-1234-1234-123456789abc/apply"
        if platform == "lever"
        else "https://job-boards.greenhouse.io/boundary/jobs/123"
    )
    job = Job(
        external_id=f"{platform}-boundary-job",
        title="Boundary Analyst",
        company="Boundary Employer",
        url=url,
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": url,
        },
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applied,
        automation_state=ApplicationAutomationState.confirmed.value,
        submission_idempotency_key=f"application:{platform}:boundary:1",
        submission_attempt_count=1,
        last_submission_attempt_at=datetime.utcnow(),
    )
    db_session.add(application)
    db_session.flush()
    approval = SubmissionApproval(
        application_id=application.id,
        user_id=user.id,
        platform=platform,
        status=SubmissionApprovalStatus.consumed.value,
        employer=job.company,
        role=job.title,
        application_url=url,
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
    return user, job, application, approval


def test_greenhouse_endpoint_rejects_consumed_lever_approval(db_session):
    _, _, application, _ = _application_with_consumed_approval(
        db_session,
        platform="lever",
    )

    with pytest.raises(HTTPException) as exc_info:
        greenhouse_pilot_ledger._require_greenhouse_approval(
            db_session,
            application.id,
        )

    assert exc_info.value.status_code == 409
    assert "Greenhouse approvals only" in str(exc_info.value.detail)
    assert "lever" in str(exc_info.value.detail)


def test_generic_dispatcher_routes_lever_only_to_lever_ledger(db_session, monkeypatch):
    user, _, application, _ = _application_with_consumed_approval(
        db_session,
        platform="lever",
    )
    calls = []

    def lever_ingest(db, app, current_user, job):
        calls.append(("lever", app.id, current_user.id, job.id))
        return {"added": True, "record": {"platform": "lever"}}

    def greenhouse_ingest(*args, **kwargs):
        raise AssertionError("Lever application reached the Greenhouse ledger")

    monkeypatch.setattr(pilot_ledger, "ingest_confirmed_lever_application", lever_ingest)
    monkeypatch.setattr(
        pilot_ledger,
        "ingest_confirmed_supervised_application",
        greenhouse_ingest,
    )

    result = pilot_ledger.ingest_application_pilot_record(
        application.id,
        current_user=user,
        db=db_session,
    )

    assert result["platform"] == "lever"
    assert result["record"]["platform"] == "lever"
    assert len(calls) == 1
    assert calls[0][0] == "lever"


def test_generic_dispatcher_routes_greenhouse_only_to_greenhouse_ledger(
    db_session,
    monkeypatch,
):
    user, _, application, _ = _application_with_consumed_approval(
        db_session,
        platform="greenhouse",
    )
    calls = []

    def greenhouse_ingest(db, app, current_user, job):
        calls.append(("greenhouse", app.id, current_user.id, job.id))
        return {"added": True, "record": {"adapter": "greenhouse"}}

    def lever_ingest(*args, **kwargs):
        raise AssertionError("Greenhouse application reached the Lever ledger")

    monkeypatch.setattr(
        pilot_ledger,
        "ingest_confirmed_supervised_application",
        greenhouse_ingest,
    )
    monkeypatch.setattr(pilot_ledger, "ingest_confirmed_lever_application", lever_ingest)

    result = pilot_ledger.ingest_application_pilot_record(
        application.id,
        current_user=user,
        db=db_session,
    )

    assert result["platform"] == "greenhouse"
    assert result["record"]["adapter"] == "greenhouse"
    assert len(calls) == 1
    assert calls[0][0] == "greenhouse"


def test_frontend_generic_ingestion_never_defaults_to_greenhouse():
    root = Path(__file__).resolve().parents[2]
    client_source = (root / "frontend/src/api/client.js").read_text(encoding="utf-8")
    panel_source = (
        root / "frontend/src/components/SubmissionEvidenceReviewPanel.jsx"
    ).read_text(encoding="utf-8")

    assert "export const ingestSupervisedPilotRecord" in client_source
    assert "api.post(`/pilot-ledger/applications/${appId}/ingest`)" in client_source
    assert "ingestGreenhouseSupervisedPilotRecord" in client_source
    assert "ingestLeverSupervisedPilotRecord" in client_source
    assert "ingestSupervisedPilotRecord" in panel_source

    generic_block = client_source.split(
        "export const ingestSupervisedPilotRecord",
        1,
    )[1].split("export const ingestGreenhouseSupervisedPilotRecord", 1)[0]
    assert "greenhouse-pilot-ledger" not in generic_block
