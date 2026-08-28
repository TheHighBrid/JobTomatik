from __future__ import annotations

import httpx
import pytest

from app.models.application import Application, ApplicationEvent
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionIdentityAlias
from app.services import ats_lever
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


@pytest.mark.asyncio
async def test_hosted_metadata_fallback_is_strictly_404_scoped(monkeypatch):
    posting_id = "a52e4915-8239-4581-8828-84661f070424"
    hosted_url = f"https://jobs.lever.co/fullscript/{posting_id}"
    apply_path = f"/fullscript/{posting_id}/apply"
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "api.lever.co":
            return httpx.Response(
                404,
                request=request,
                json={"ok": False, "error": "Document not found"},
            )
        assert request.url.host == "jobs.lever.co"
        html = (
            '<!doctype html><html><head><title>Fullscript - Technical Support Specialist</title></head>'
            '<body><div class="posting-headline"><h2>Technical Support Specialist</h2></div>'
            f'<a href="{apply_path}">Apply for this job</a></body></html>'
        )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html; charset=utf-8"},
            text=html,
        )

    transport = httpx.MockTransport(handler)
    real_client = ats_lever.httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(ats_lever.httpx, "AsyncClient", client_factory)
    payload = await ats_lever.fetch_lever_posting("fullscript", posting_id)

    assert payload["id"] == posting_id
    assert payload["text"] == "Technical Support Specialist"
    assert payload["hostedUrl"] == hosted_url
    assert payload["applyUrl"] == f"{hosted_url}/apply"
    assert payload["_metadata_source"] == "hosted_page_404_fallback"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_hosted_metadata_fallback_does_not_mask_non_404_api_failures(monkeypatch):
    posting_id = "a52e4915-8239-4581-8828-84661f070424"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.lever.co"
        return httpx.Response(403, request=request, text="forbidden")

    transport = httpx.MockTransport(handler)
    real_client = ats_lever.httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(ats_lever.httpx, "AsyncClient", client_factory)
    with pytest.raises(httpx.HTTPStatusError):
        await ats_lever.fetch_lever_posting("fullscript", posting_id)


@pytest.mark.asyncio
async def test_hosted_metadata_fallback_requires_exact_apply_route(monkeypatch):
    posting_id = "a52e4915-8239-4581-8828-84661f070424"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.lever.co":
            return httpx.Response(404, request=request, json={"ok": False})
        html = (
            '<!doctype html><html><body>'
            '<div class="posting-headline"><h2>Technical Support Specialist</h2></div>'
            '</body></html>'
        )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            text=html,
        )

    transport = httpx.MockTransport(handler)
    real_client = ats_lever.httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(ats_lever.httpx, "AsyncClient", client_factory)
    with pytest.raises(ValueError, match="exact apply route"):
        await ats_lever.fetch_lever_posting("fullscript", posting_id)
