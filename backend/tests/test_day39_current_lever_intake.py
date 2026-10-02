from __future__ import annotations

import httpx
import pytest

from app.models.application import Application, ApplicationEvent
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionIdentityAlias
from app.services import lever_phase_b_current_intake as intake_service
from app.services import supervised_target_identity as target_identity


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


def _http_error(status_code: int, url: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


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
async def test_supervised_hosted_metadata_fallback_is_strictly_404_scoped(monkeypatch):
    posting_id = "a52e4915-8239-4581-8828-84661f070424"
    hosted_url = f"https://jobs.lever.co/fullscript/{posting_id}"
    apply_path = f"/fullscript/{posting_id}/apply"
    api_calls = []
    hosted_calls = []

    async def public_api(site, requested_posting_id, *, region, timeout):
        api_calls.append((site, requested_posting_id, region, timeout))
        raise _http_error(
            404,
            f"https://api.lever.co/v0/postings/{site}/{requested_posting_id}",
        )

    def handler(request: httpx.Request) -> httpx.Response:
        hosted_calls.append(str(request.url))
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
    real_client = target_identity.httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(target_identity, "fetch_lever_posting", public_api)
    monkeypatch.setattr(target_identity.httpx, "AsyncClient", client_factory)
    payload = await target_identity._fetch_supervised_lever_posting(
        "fullscript",
        posting_id,
        region="global",
    )

    assert payload["id"] == posting_id
    assert payload["text"] == "Technical Support Specialist"
    assert payload["hostedUrl"] == hosted_url
    assert payload["applyUrl"] == f"{hosted_url}/apply"
    assert payload["_metadata_source"] == "supervised_hosted_page_404_fallback"
    assert len(api_calls) == 1
    assert hosted_calls == [hosted_url]


@pytest.mark.asyncio
async def test_supervised_hosted_metadata_fallback_does_not_mask_non_404_api_failures(
    monkeypatch,
):
    posting_id = "a52e4915-8239-4581-8828-84661f070424"

    async def public_api(site, requested_posting_id, *, region, timeout):
        raise _http_error(
            403,
            f"https://api.lever.co/v0/postings/{site}/{requested_posting_id}",
        )

    monkeypatch.setattr(target_identity, "fetch_lever_posting", public_api)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await target_identity._fetch_supervised_lever_posting(
            "fullscript",
            posting_id,
            region="global",
        )
    assert exc_info.value.response.status_code == 403


@pytest.mark.asyncio
async def test_supervised_hosted_metadata_fallback_requires_exact_apply_route(monkeypatch):
    posting_id = "a52e4915-8239-4581-8828-84661f070424"

    async def public_api(site, requested_posting_id, *, region, timeout):
        raise _http_error(
            404,
            f"https://api.lever.co/v0/postings/{site}/{requested_posting_id}",
        )

    def handler(request: httpx.Request) -> httpx.Response:
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
    real_client = target_identity.httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(target_identity, "fetch_lever_posting", public_api)
    monkeypatch.setattr(target_identity.httpx, "AsyncClient", client_factory)
    with pytest.raises(ValueError, match="exact apply route"):
        await target_identity._fetch_supervised_lever_posting(
            "fullscript",
            posting_id,
            region="global",
        )


@pytest.mark.asyncio
async def test_supervised_runtime_refresh_uses_same_404_hosted_fallback(monkeypatch):
    posting_id = "a52e4915-8239-4581-8828-84661f070424"
    hosted_url = f"https://jobs.lever.co/fullscript/{posting_id}"
    apply_url = f"{hosted_url}/apply"
    payload = {
        "id": posting_id,
        "text": "Technical Support Specialist",
        "categories": {},
        "description": "",
        "descriptionPlain": "",
        "hostedUrl": hosted_url,
        "applyUrl": apply_url,
    }
    metadata_hash = target_identity._hash_value(
        target_identity._safe_official_payload(payload)
    )
    expected = {
        "platform": "lever",
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "site": "fullscript",
        "posting_id": posting_id,
        "region": "global",
        "canonical_application_url": apply_url,
        "posting_metadata_hash": metadata_hash,
    }

    async def fallback(site, requested_posting_id, *, region, timeout=15.0):
        assert (site, requested_posting_id, region) == (
            "fullscript",
            posting_id,
            "global",
        )
        return payload

    monkeypatch.setattr(target_identity, "_fetch_supervised_lever_posting", fallback)
    result = await target_identity.verify_supervised_browser_target(
        current_url=apply_url,
        adapter_name="lever",
        adapter_version="1.1.0",
        expected_metadata=expected,
        refresh_official_metadata=True,
    )

    assert result["verified"] is True
    assert result["blockers"] == []
    assert result["observed_metadata_hash"] == metadata_hash
