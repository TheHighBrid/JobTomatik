import json
from pathlib import Path

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    SubmissionEvidence,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt
from app.services import lever_phase_b_launch as launch_service


EVIDENCE_ROOT = Path(__file__).resolve().parents[1] / "evidence"
CANONICAL_LAUNCH = EVIDENCE_ROOT / "lever-phase-b-launch.json"


@pytest.fixture(autouse=True)
def use_canonical_launch(monkeypatch):
    monkeypatch.setattr(
        launch_service.settings,
        "lever_phase_b_launch_path",
        str(CANONICAL_LAUNCH),
    )


def test_lever_launch_status_exposes_exact_retained_candidates(auth_client):
    response = auth_client.get("/api/supervised-pilot/lever-launch")

    assert response.status_code == 200
    payload = response.json()
    assert payload["preparation_only"] is True
    assert payload["candidate_count"] == 2
    assert payload["materialized_count"] == 0
    assert [item["review_id"] for item in payload["candidates"]] == [
        "D8-026",
        "D8-028",
    ]
    assert {
        item["employer"] for item in payload["candidates"]
    } == {"Cin7", "PocketHealth"}
    for candidate in payload["candidates"]:
        assert candidate["synthetic_preview"] is True
        assert candidate["read_only"] is True
        assert candidate["one_time_approval_required"] is True
        assert candidate["materialized"] is False
        assert candidate["submission_queued"] is False
        assert candidate["approval_issued"] is False
        assert candidate["runtime_flags_changed"] is False
        assert len(candidate["dossier_artifact_sha256"]) == 64
        assert len(candidate["dossier_sha256"]) == 64
        assert len(candidate["source_report_sha256"]) == 64


def test_materialization_creates_preparation_only_records(
    auth_client,
    db_session,
):
    response = auth_client.post(
        "/api/supervised-pilot/lever-launch/D8-026/materialize"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_id"] == "D8-026"
    assert payload["created_job"] is True
    assert payload["created_application"] is True
    assert payload["automation_state"] == ApplicationAutomationState.preparing.value
    assert payload["synthetic_preview"] is True
    assert payload["requires_fresh_runtime_preflight"] is True
    assert payload["submission_queued"] is False
    assert payload["approval_issued"] is False
    assert payload["runtime_flags_changed"] is False

    job = db_session.query(Job).filter(Job.id == payload["job_id"]).one()
    application = (
        db_session.query(Application)
        .filter(Application.id == payload["application_id"])
        .one()
    )
    event = (
        db_session.query(ApplicationEvent)
        .filter(
            ApplicationEvent.application_id == application.id,
            ApplicationEvent.event_type
            == "lever_phase_b_launch_candidate_materialized",
        )
        .one()
    )

    assert job.external_id == payload["launch_application_id"]
    assert job.source == JobSource.lever
    assert job.status == JobStatus.queued
    assert job.raw_data["selection_source"] == "retained_lever_phase_b_launch"
    assert job.raw_data["review_id"] == "D8-026"
    assert job.raw_data["synthetic_preview"] is True
    assert job.raw_data["read_only_launch_evidence"] is True
    assert len(job.raw_data["dossier_artifact_sha256"]) == 64
    assert len(job.raw_data["dossier_sha256"]) == 64

    assert application.status == ApplicationStatus.pending
    assert application.automation_state == ApplicationAutomationState.preparing.value
    assert application.source_listing_url == payload["application_url"]
    assert application.application_target_url == payload["application_url"]
    assert application.application_target_status == "resolved"
    assert application.application_target_metadata[
        "requires_fresh_runtime_preflight"
    ] is True
    assert application.cover_letter is None
    assert application.submission_attempt_count == 0
    assert application.applied_at is None

    assert event.payload["review_id"] == "D8-026"
    assert event.payload["synthetic_preview"] is True
    assert event.payload["requires_fresh_runtime_preflight"] is True
    assert event.payload["submission_queued"] is False
    assert event.payload["approval_issued"] is False
    assert event.payload["runtime_flags_changed"] is False

    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0
    assert db_session.query(SubmissionEvidence).count() == 0


def test_materialization_is_idempotent_for_same_user(auth_client, db_session):
    first = auth_client.post(
        "/api/supervised-pilot/lever-launch/D8-028/materialize"
    )
    second = auth_client.post(
        "/api/supervised-pilot/lever-launch/D8-028/materialize"
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["application_id"] == first.json()["application_id"]
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["created_job"] is False
    assert second.json()["created_application"] is False
    assert db_session.query(Job).count() == 1
    assert db_session.query(Application).count() == 1
    assert (
        db_session.query(ApplicationEvent)
        .filter(
            ApplicationEvent.event_type
            == "lever_phase_b_launch_candidate_materialized"
        )
        .count()
        == 1
    )


def test_tampered_dossier_blocks_before_materialization(
    auth_client,
    db_session,
    monkeypatch,
    tmp_path,
):
    launch = json.loads(CANONICAL_LAUNCH.read_text(encoding="utf-8"))
    selection_path = EVIDENCE_ROOT / launch["selection_receipt"]["path"]
    (tmp_path / selection_path.name).write_bytes(selection_path.read_bytes())

    dossier_root = tmp_path / "lever-phase-b-dossiers"
    dossier_root.mkdir()
    for item in launch["applications"]:
        source = EVIDENCE_ROOT / item["dossier"]["artifact_path"]
        destination = tmp_path / item["dossier"]["artifact_path"]
        if item["selection_reference"].endswith("#D8-026"):
            dossier = json.loads(source.read_text(encoding="utf-8"))
            dossier["read_only"] = False
            destination.write_text(
                json.dumps(dossier, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            destination.write_bytes(source.read_bytes())

    launch_path = tmp_path / "lever-phase-b-launch.json"
    launch_path.write_text(
        json.dumps(launch, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        launch_service.settings,
        "lever_phase_b_launch_path",
        str(launch_path),
    )

    status = auth_client.get("/api/supervised-pilot/lever-launch")
    materialize = auth_client.post(
        "/api/supervised-pilot/lever-launch/D8-026/materialize"
    )

    assert status.status_code == 409
    assert materialize.status_code == 409
    assert "hash mismatch" in status.json()["detail"]
    assert db_session.query(Job).count() == 0
    assert db_session.query(Application).count() == 0


@pytest.mark.parametrize(
    "path",
    [
        "/api/supervised-pilot/lever-launch",
        "/api/supervised-pilot/lever-launch/D8-026/materialize",
    ],
)
def test_lever_launch_endpoints_require_authentication(client, path):
    method = client.get if path.endswith("lever-launch") else client.post
    response = method(path)

    assert response.status_code == 401
