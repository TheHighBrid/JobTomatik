from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.models.application import Application
from app.models.job import Job, JobSource, JobStatus
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services import supervised_submission as approval_service
from tests.conftest import TestingSessionLocal


GREENHOUSE_URL = "https://job-boards.greenhouse.io/safeco/jobs/123456"


def _prepare_application(auth_client, tmp_path, *, suffix: str) -> int:
    resume = tmp_path / f"schema-binding-{suffix}.pdf"
    resume.write_bytes(b"%PDF-1.4\nGreenhouse schema binding fixture\n")

    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").one()
    user.resume_path = str(resume)
    user.phone = "+1 613 555 0101"
    job = Job(
        external_id=f"greenhouse-schema-{suffix}",
        title="Fraud Operations Analyst",
        company="SafeCo",
        url=GREENHOUSE_URL,
        source=JobSource.manual,
        status=JobStatus.approved,
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": GREENHOUSE_URL,
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id
    db.close()

    response = auth_client.post(
        "/api/applications",
        json={
            "job_id": job_id,
            "cover_letter": "Schema-bound supervised pilot cover letter.",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _enable_pilot(monkeypatch) -> None:
    monkeypatch.setattr(
        approval_service.settings,
        "allow_real_application_submit",
        True,
    )
    monkeypatch.setattr(
        approval_service.settings,
        "greenhouse_supervised_pilot_enabled",
        True,
    )


def _approval_payload() -> dict:
    return {
        "confirm_employer": "SafeCo",
        "confirm_role": "Fraud Operations Analyst",
        "confirm_application_url": GREENHOUSE_URL,
        "confirm_final_submit": True,
        "expires_in_minutes": 20,
    }


def _schema_status(schema_hash: str) -> dict:
    return {
        "checked": True,
        "verified": True,
        "status_code": 200,
        "board_token": "safeco",
        "job_id": "123456",
        "schema_hash": schema_hash,
        "fingerprint_version": approval_service.FORM_SCHEMA_FINGERPRINT_VERSION,
        "question_count": 4,
        "required_question_count": 4,
        "required_uploads": ["Resume"],
        "unsupported_fields": [],
        "blocker": None,
    }


def test_greenhouse_schema_fingerprint_is_order_insensitive_but_detects_option_drift():
    schema = {
        "id": 123456,
        "questions": [
            {
                "label": "Are you authorized to work in Canada?",
                "required": True,
                "fields": [
                    {
                        "name": "question_1",
                        "type": "multi_value_single_select",
                        "values": [
                            {"value": 1, "label": "Yes"},
                            {"value": 2, "label": "No"},
                        ],
                    }
                ],
            },
            {
                "label": "Resume",
                "required": True,
                "fields": [{"name": "resume", "type": "input_file"}],
            },
        ],
        "location_questions": [],
        "demographic_questions": [],
        "data_compliance": [{"type": "gdpr", "requires_consent": False}],
    }
    reordered = deepcopy(schema)
    reordered["questions"].reverse()
    reordered["questions"][1]["fields"][0]["values"].reverse()

    base_hash = approval_service._greenhouse_schema_fingerprint(schema, "123456")
    reordered_hash = approval_service._greenhouse_schema_fingerprint(
        reordered,
        "123456",
    )
    assert base_hash == reordered_hash

    changed = deepcopy(schema)
    changed["questions"][0]["fields"][0]["values"][0]["label"] = "Authorized"
    assert approval_service._greenhouse_schema_fingerprint(
        changed,
        "123456",
    ) != base_hash


@pytest.mark.parametrize(
    "schema",
    [
        {},
        {"questions": []},
        {"questions": [{"label": "Name"}]},
        {
            "questions": [
                {"label": "Name", "fields": [{"name": "first_name"}]}
            ]
        },
    ],
)
def test_greenhouse_schema_probe_rejects_missing_or_malformed_questions(
    monkeypatch,
    schema,
):
    monkeypatch.setattr(
        approval_service,
        "_get_greenhouse_schema_response",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            json=lambda: schema,
        ),
    )

    result = approval_service._greenhouse_form_schema_status(GREENHOUSE_URL)

    assert result["verified"] is False
    assert result["schema_hash"] is None
    assert result["blocker"] == "application_form_schema_unverified"


def test_embedded_greenhouse_schema_probe_uses_for_board_token(monkeypatch):
    requested = {}
    monkeypatch.setattr(
        approval_service,
        "_get_greenhouse_schema_response",
        lambda url, **kwargs: (
            requested.update(url=url)
            or SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "questions": [
                        {
                            "label": "Name",
                            "required": True,
                            "fields": [{"name": "first_name", "type": "input_text"}],
                        }
                    ]
                },
            )
        ),
    )

    result = approval_service._greenhouse_form_schema_status(
        "https://boards.greenhouse.io/embed/job_app?token=123&for=acme"
    )

    assert requested["url"].endswith("/boards/acme/jobs/123")
    assert result["board_token"] == "acme"
    assert result["job_id"] == "123"
    assert result["verified"] is True


def test_unverified_live_greenhouse_schema_blocks_supervised_approval(
    auth_client,
    tmp_path,
    monkeypatch,
):
    _enable_pilot(monkeypatch)
    app_id = _prepare_application(auth_client, tmp_path, suffix="unverified")
    monkeypatch.setattr(
        approval_service,
        "_should_probe_form_schema",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        approval_service,
        "_greenhouse_form_schema_status",
        lambda _url: {
            **_schema_status("a" * 64),
            "verified": False,
            "schema_hash": None,
            "blocker": "application_form_schema_unverified",
        },
    )

    preflight = auth_client.get(
        f"/api/supervised-submissions/applications/{app_id}/preflight"
    )
    assert preflight.status_code == 200
    assert preflight.json()["ready"] is False
    assert "application_form_schema_unverified" in preflight.json()["blockers"]

    approval = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json=_approval_payload(),
    )
    assert approval.status_code == 409


def test_greenhouse_schema_drift_revokes_approval_before_queueing(
    auth_client,
    tmp_path,
    monkeypatch,
):
    _enable_pilot(monkeypatch)
    app_id = _prepare_application(auth_client, tmp_path, suffix="drift")
    monkeypatch.setattr(
        approval_service,
        "_should_probe_form_schema",
        lambda *_args, **_kwargs: True,
    )
    current_hash = {"value": "a" * 64}
    monkeypatch.setattr(
        approval_service,
        "_greenhouse_form_schema_status",
        lambda _url: _schema_status(current_hash["value"]),
    )

    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json=_approval_payload(),
    )
    assert created.status_code == 201
    data = created.json()
    reference = data["reference"]
    assert data["approval_metadata"]["form_schema_hash"] == "a" * 64

    current_hash["value"] = "b" * 64
    queued = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals/{reference}/submit"
    )
    assert queued.status_code == 409
    assert "payload changed" in queued.json()["detail"].lower()

    db = TestingSessionLocal()
    approval = db.query(SubmissionApproval).filter(
        SubmissionApproval.reference == reference
    ).one()
    assert approval.status == SubmissionApprovalStatus.revoked.value
    mismatches = approval.approval_metadata["mismatched_fields"]
    assert "form_schema_hash" in mismatches
    assert "combined_payload_hash" in mismatches
    application = db.query(Application).filter(Application.id == app_id).one()
    assert application.submission_attempt_count == 0
    db.close()
