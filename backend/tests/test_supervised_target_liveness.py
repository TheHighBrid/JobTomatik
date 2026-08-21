from types import SimpleNamespace

import httpx

from app.models.job import Job
from app.services import supervised_submission as approval_service


LIVE_URL = "https://job-boards.greenhouse.io/example/jobs/123456"


def test_greenhouse_target_liveness_accepts_same_exact_job(monkeypatch):
    monkeypatch.setattr(
        approval_service.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            url=LIVE_URL,
        ),
    )

    result = approval_service._greenhouse_target_liveness(LIVE_URL)

    assert result["checked"] is True
    assert result["live"] is True
    assert result["blocker"] is None
    assert result["status_code"] == 200
    assert result["final_url"] == LIVE_URL


def test_greenhouse_target_liveness_blocks_closed_board_redirect(monkeypatch):
    monkeypatch.setattr(
        approval_service.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            url="https://job-boards.greenhouse.io/example?error=true",
        ),
    )

    result = approval_service._greenhouse_target_liveness(LIVE_URL)

    assert result["checked"] is True
    assert result["live"] is False
    assert result["blocker"] == "application_target_closed_or_expired"


def test_greenhouse_target_liveness_fails_closed_when_network_is_unverified(
    monkeypatch,
):
    def fail_request(*args, **kwargs):
        request = httpx.Request("GET", LIVE_URL)
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr(approval_service.httpx, "get", fail_request)

    result = approval_service._greenhouse_target_liveness(LIVE_URL)

    assert result["checked"] is True
    assert result["live"] is False
    assert result["blocker"] == "application_target_liveness_unverified"


def test_liveness_probe_is_scoped_to_production_manual_greenhouse_phase_b(
    monkeypatch,
):
    job = Job(
        external_id="phase-b-liveness",
        title="Compliance Analyst",
        company="Example",
        url=LIVE_URL,
        raw_data={
            "selection_source": approval_service.MANUAL_GREENHOUSE_PHASE_B_SOURCE,
        },
    )

    monkeypatch.setattr(approval_service.settings, "app_environment", "production")
    assert approval_service._should_probe_target_liveness(job, "greenhouse") is True

    monkeypatch.setattr(approval_service.settings, "app_environment", "test")
    assert approval_service._should_probe_target_liveness(job, "greenhouse") is False

    monkeypatch.setattr(approval_service.settings, "app_environment", "production")
    assert approval_service._should_probe_target_liveness(job, "lever") is False

    job.raw_data = {"selection_source": "manual"}
    assert approval_service._should_probe_target_liveness(job, "greenhouse") is False
