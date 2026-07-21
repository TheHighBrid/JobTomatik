from unittest.mock import MagicMock

import pytest

from app.models.application import Application
from app.models.job import Job, JobSource, JobStatus
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services import supervised_submission as approval_service
from app.services import supervised_target_identity as identity_service
from app.services.supervised_target_identity import resolve_supervised_target_metadata
from tests.conftest import TestingSessionLocal


POSTING_ID = "12345678-1234-1234-1234-123456789abc"
LEVER_URL = f"https://jobs.lever.co/safeco/{POSTING_ID}/apply"
LEVER_EU_URL = f"https://jobs.eu.lever.co/safeco/{POSTING_ID}/apply"


def _official_payload(*, apply_url=LEVER_URL, title="Payments Risk Analyst"):
    hosted_url = apply_url.removesuffix("/apply")
    return {
        "id": POSTING_ID,
        "text": title,
        "categories": {
            "team": "Risk",
            "location": "Remote",
            "commitment": "Full-time",
        },
        "description": "<p>Payments risk role.</p>",
        "descriptionPlain": "Payments risk role.",
        "hostedUrl": hosted_url,
        "applyUrl": apply_url,
    }


def _valid_metadata(*, identity_hash="b" * 64, region="global", url=LEVER_URL):
    return {
        "platform": "lever",
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "verified": True,
        "blockers": [],
        "target_url": url,
        "canonical_application_url": url,
        "site": "safeco",
        "posting_id": POSTING_ID,
        "region": region,
        "official_title": "Payments Risk Analyst",
        "title_matches_local_job": True,
        "posting_metadata_hash": "a" * 64,
        "identity_hash": identity_hash,
        "verification_error": None,
        "verified_at": "2026-07-21T21:00:00",
    }


def _prepare_application(auth_client, tmp_path, *, suffix="base", url=LEVER_URL):
    resume = tmp_path / f"lever-{suffix}.pdf"
    resume.write_bytes(b"%PDF-1.4\nSynthetic Lever supervised resume\n")

    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").one()
    user.resume_path = str(resume)
    user.phone = "+1 613 555 0101"
    job = Job(
        external_id=f"lever-supervised-{suffix}",
        title="Payments Risk Analyst",
        company="SafeCo",
        url=url,
        source=JobSource.manual,
        status=JobStatus.approved,
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": url,
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
            "cover_letter": "Exact Lever supervised pilot cover letter.",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _enable_lever_pilot(monkeypatch):
    monkeypatch.setattr(
        approval_service.settings,
        "allow_real_application_submit",
        True,
    )
    monkeypatch.setattr(
        approval_service.settings,
        "lever_supervised_pilot_enabled",
        True,
    )


def _mock_metadata(monkeypatch, metadata):
    async def resolved(_job):
        return dict(metadata)

    monkeypatch.setattr(
        "app.api.supervised_submissions.resolve_supervised_target_metadata",
        resolved,
    )


def _approval_payload(url=LEVER_URL):
    return {
        "confirm_employer": "SafeCo",
        "confirm_role": "Payments Risk Analyst",
        "confirm_application_url": url,
        "confirm_final_submit": True,
        "expires_in_minutes": 20,
        "notes": "Explicit Lever target approval.",
    }


@pytest.mark.asyncio
async def test_resolver_binds_global_and_eu_lever_identity(monkeypatch):
    async def fetch_global(site, posting_id, *, region="global", timeout=15.0):
        assert site == "safeco"
        assert posting_id == POSTING_ID
        url = LEVER_EU_URL if region == "eu" else LEVER_URL
        return _official_payload(apply_url=url)

    monkeypatch.setattr(identity_service, "fetch_lever_posting", fetch_global)

    global_job = Job(title="Payments Risk Analyst", company="SafeCo", url=LEVER_URL)
    global_job.raw_data = {"selected_apply_url": LEVER_URL}
    global_identity = await resolve_supervised_target_metadata(global_job)
    assert global_identity["verified"] is True
    assert global_identity["site"] == "safeco"
    assert global_identity["posting_id"] == POSTING_ID
    assert global_identity["region"] == "global"
    assert global_identity["canonical_application_url"] == LEVER_URL
    assert global_identity["adapter_version"] == "1.1.0"
    assert len(global_identity["posting_metadata_hash"]) == 64
    assert len(global_identity["identity_hash"]) == 64

    eu_job = Job(title="Payments Risk Analyst", company="SafeCo", url=LEVER_EU_URL)
    eu_job.raw_data = {"selected_apply_url": LEVER_EU_URL}
    eu_identity = await resolve_supervised_target_metadata(eu_job)
    assert eu_identity["verified"] is True
    assert eu_identity["region"] == "eu"
    assert eu_identity["canonical_application_url"] == LEVER_EU_URL
    assert eu_identity["identity_hash"] != global_identity["identity_hash"]


@pytest.mark.asyncio
async def test_resolver_fails_closed_on_role_or_metadata_mismatch(monkeypatch):
    async def fetch_wrong_title(*args, **kwargs):
        return _official_payload(title="Unrelated Engineering Role")

    monkeypatch.setattr(identity_service, "fetch_lever_posting", fetch_wrong_title)
    job = Job(title="Payments Risk Analyst", company="SafeCo", url=LEVER_URL)
    job.raw_data = {"selected_apply_url": LEVER_URL}

    identity = await resolve_supervised_target_metadata(job)

    assert identity["verified"] is False
    assert "lever_role_metadata_mismatch" in identity["blockers"]
    assert identity["identity_hash"]


def test_lever_preflight_is_exact_but_disabled_by_default(
    auth_client,
    tmp_path,
    monkeypatch,
):
    app_id = _prepare_application(auth_client, tmp_path, suffix="disabled")
    _mock_metadata(monkeypatch, _valid_metadata())

    response = auth_client.get(
        f"/api/supervised-submissions/applications/{app_id}/preflight"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is False
    assert data["platform"] == "lever"
    assert data["platform_display_name"] == "Lever"
    assert data["adapter_version"] == "1.1.0"
    assert "global_live_submit_disabled" in data["blockers"]
    assert "lever_supervised_pilot_disabled" in data["blockers"]
    assert data["target_identity_verified"] is True
    assert data["target_identity"]["site"] == "safeco"
    assert data["target_identity"]["posting_id"] == POSTING_ID
    assert data["target_identity_hash"] == "b" * 64


def test_lever_approval_uses_exact_target_hash_and_platform_reference(
    auth_client,
    tmp_path,
    monkeypatch,
):
    _enable_lever_pilot(monkeypatch)
    app_id = _prepare_application(auth_client, tmp_path, suffix="approval")
    _mock_metadata(monkeypatch, _valid_metadata())

    preflight = auth_client.get(
        f"/api/supervised-submissions/applications/{app_id}/preflight"
    )
    assert preflight.status_code == 200
    assert preflight.json()["ready"] is True

    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json=_approval_payload(),
    )

    assert created.status_code == 201
    data = created.json()
    assert data["reference"].startswith("lvsup-")
    assert data["platform"] == "lever"
    assert data["application_url"] == LEVER_URL
    assert data["approval_metadata"]["adapter_version"] == "1.1.0"
    assert data["approval_metadata"]["target_identity_hash"] == "b" * 64
    assert data["approval_metadata"]["target_identity"]["region"] == "global"
    assert len(data["combined_payload_hash"]) == 64


def test_lever_target_identity_drift_revokes_before_queueing(
    auth_client,
    tmp_path,
    monkeypatch,
):
    _enable_lever_pilot(monkeypatch)
    app_id = _prepare_application(auth_client, tmp_path, suffix="drift")
    _mock_metadata(monkeypatch, _valid_metadata(identity_hash="b" * 64))

    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json=_approval_payload(),
    )
    assert created.status_code == 201
    reference = created.json()["reference"]

    changed = _valid_metadata(identity_hash="c" * 64)
    changed["posting_metadata_hash"] = "d" * 64
    _mock_metadata(monkeypatch, changed)

    fake_task = MagicMock()
    monkeypatch.setattr(
        "app.api.supervised_submissions.submit_application_task",
        fake_task,
    )
    queued = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals/{reference}/submit"
    )

    assert queued.status_code == 409
    assert "payload changed" in queued.json()["detail"].lower()
    fake_task.delay.assert_not_called()

    db = TestingSessionLocal()
    approval = db.query(SubmissionApproval).filter(
        SubmissionApproval.reference == reference
    ).one()
    assert approval.status == SubmissionApprovalStatus.revoked.value
    assert "target_identity_hash" in approval.approval_metadata["mismatched_fields"]
    application = db.query(Application).filter(Application.id == app_id).one()
    assert application.submission_attempt_count == 0
    db.close()
