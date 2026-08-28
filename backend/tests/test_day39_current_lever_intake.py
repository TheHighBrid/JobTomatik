from __future__ import annotations

from app.models.application import Application, ApplicationEvent
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionIdentityAlias
from app.services import lever_phase_b_current_intake as intake_service


POSTING_ID = "0d95c00e-3019-4390-8a57-c05d9bf58a10"
HOSTED_URL = f"https://jobs.lever.co/eqbank/{POSTING_ID}"
APPLY_URL = f"{HOSTED_URL}/apply"


def _verified_target():
    return {
        "platform": "lever",
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "verified": True,
        "blockers": [],
        "target_url": APPLY_URL,
        "canonical_application_url": APPLY_URL,
        "site": "eqbank",
        "posting_id": POSTING_ID,
        "region": "global",
        "official_title": "Bilingual Customer Care Representative (ENG & FR)",
        "title_matches_local_job": True,
        "posting_metadata_hash": "a" * 64,
        "identity_hash": "b" * 64,
        "verification_error": None,
        "verified_at": "2026-08-28T15:00:00",
    }


def _payload():
    return {
        "employer": "EQ Bank / Equitable Bank",
        "role": "Bilingual Customer Care Representative (ENG & FR)",
        "application_url": HOSTED_URL,
        "location": "Remote, Canada",
        "notes": "Preparation only",
        "source_reference": "lever-phase-b-candidate-review-2026-08-28#rank-1",
    }


def test_current_lever_intake_requires_verified_live_identity(
    auth_client,
    db_session,
    monkeypatch,
):
    async def blocked(_job):
        return {
            **_verified_target(),
            "verified": False,
            "blockers": ["lever_official_metadata_unavailable"],
            "identity_hash": None,
        }

    monkeypatch.setattr(
        intake_service,
        "resolve_supervised_target_metadata",
        blocked,
    )

    response = auth_client.post("/api/supervised-pilot/lever-candidates", json=_payload())
    assert response.status_code == 422
    assert "lever_official_metadata_unavailable" in response.json()["detail"]
    assert db_session.query(Job).count() == 0
    assert db_session.query(Application).count() == 0
    assert db_session.query(SubmissionApproval).count() == 0


def test_current_lever_intake_is_idempotent_preparation_only(
    auth_client,
    db_session,
    monkeypatch,
):
    async def verified(_job):
        return _verified_target()

    monkeypatch.setattr(
        intake_service,
        "resolve_supervised_target_metadata",
        verified,
    )

    first = auth_client.post("/api/supervised-pilot/lever-candidates", json=_payload())
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["created_job"] is True
    assert body["created_application"] is True
    assert body["application_url"] == APPLY_URL
    assert body["target_identity_verified"] is True
    assert body["adapter_version"] == "1.1.0"
    assert body["submission_queued"] is False
    assert body["approval_issued"] is False
    assert body["runtime_flags_changed"] is False

    job = db_session.query(Job).filter(Job.id == body["job_id"]).one()
    application = (
        db_session.query(Application)
        .filter(Application.id == body["application_id"])
        .one()
    )
    target = dict((job.raw_data or {}).get("supervised_target_metadata") or {})
    assert target["verified"] is True
    assert target["identity_hash"] == "b" * 64
    assert application.submission_idempotency_key.startswith("submission-identity:")
    assert (
        db_session.query(SubmissionIdentityAlias)
        .filter(SubmissionIdentityAlias.application_id == application.id)
        .count()
        >= 2
    )
    event = (
        db_session.query(ApplicationEvent)
        .filter(
            ApplicationEvent.application_id == application.id,
            ApplicationEvent.event_type == "lever_phase_b_current_candidate_imported",
        )
        .one()
    )
    assert event.payload["submission_queued"] is False
    assert event.payload["approval_issued"] is False
    assert event.payload["runtime_flags_changed"] is False
    assert db_session.query(SubmissionApproval).count() == 0

    second = auth_client.post("/api/supervised-pilot/lever-candidates", json=_payload())
    assert second.status_code == 201, second.text
    repeated = second.json()
    assert repeated["application_id"] == body["application_id"]
    assert repeated["job_id"] == body["job_id"]
    assert repeated["created_job"] is False
    assert repeated["created_application"] is False
    assert db_session.query(Job).count() == 1
    assert db_session.query(Application).count() == 1
    assert db_session.query(SubmissionApproval).count() == 0


def test_current_lever_intake_rejects_forged_authority_fields(auth_client):
    payload = {
        **_payload(),
        "approval_reference": "fake",
        "authorize_final_submit": True,
        "promotion_authorized": True,
    }
    response = auth_client.post("/api/supervised-pilot/lever-candidates", json=payload)
    assert response.status_code == 422
