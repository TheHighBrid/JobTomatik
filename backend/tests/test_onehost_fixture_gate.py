"""Actual browser proof and negative controls for the fixture-only boundary."""

import json
from pathlib import Path

import pytest

from scripts.run_onehost_fixture_gate import request_allowed, run_gate, run_once


@pytest.mark.parametrize("url,method", [
    ("https://127.0.0.1:1234/fixture", "GET"),
    ("http://localhost:1234/fixture", "GET"),
    ("http://127.0.0.1:1235/fixture", "GET"),
    ("http://127.0.0.1:1234/submit", "GET"),
    ("http://127.0.0.1:1234/fixture", "POST"),
    ("http://employer.invalid/fixture", "GET"),
    ("http://127.0.0.1:1234/fixture?redirect=employer.invalid", "GET"),
])
def test_fixture_boundary_rejects_other_targets_and_submission(url, method):
    assert not request_allowed(url, method, "http://127.0.0.1:1234/fixture")


@pytest.mark.asyncio
async def test_three_fresh_launches_navigate_fill_retain_traces_and_stop(tmp_path):
    summary = await run_gate(tmp_path)
    assert summary["status"] == "passed", (tmp_path / "run-001/evidence.json").read_text()
    assert len(summary["runs"]) == 3
    assert summary["synthetic"] is True
    assert summary["api_celery_dispatch_proven"] is False
    assert summary["employer_certification"] is False
    for run in summary["runs"]:
        record = json.loads((tmp_path / run["evidence"]).read_text())
        assert all(record["checks"].values())
        assert record["remaining_child_processes"] == []
        assert (tmp_path / Path(run["evidence"]).parent / "trace.zip").is_file()


@pytest.mark.asyncio
async def test_fill_failure_retains_trace_and_shuts_down(monkeypatch, tmp_path):
    from app.services import form_filler_v3

    async def fail_fill(*_args, **_kwargs):
        raise RuntimeError("Injected fixture fill failure")

    monkeypatch.setattr(form_filler_v3, "_fill_step_fields", fail_fill)
    record = await run_once(tmp_path, 1)
    assert record["status"] == "failed"
    assert "Injected fixture fill failure" in record["errors"][0]
    assert record["checks"]["browser_shutdown"]
    assert record["checks"]["server_shutdown"]
    assert record["checks"]["trace_retained"]


@pytest.mark.asyncio
async def test_final_submit_sensor_detects_a_click_even_without_a_post(monkeypatch, tmp_path):
    from app.services import form_filler_v3

    fill = form_filler_v3._fill_step_fields

    async def fill_then_click_fixture_submit(surface, **kwargs):
        outcome = await fill(surface, **kwargs)
        await surface.locator("#submit_app").click()
        return outcome

    monkeypatch.setattr(form_filler_v3, "_fill_step_fields", fill_then_click_fixture_submit)
    record = await run_once(tmp_path, 1)
    assert record["status"] == "failed"
    assert record["submit_observations"] == {"submitClicks": 1, "submitEvents": 1}
    assert not record["checks"]["submit_not_clicked"]
    assert record["checks"]["trace_retained"]
    assert record["checks"]["browser_shutdown"]


@pytest.mark.asyncio
async def test_unexpected_network_request_is_blocked_and_fails_proof(monkeypatch, tmp_path):
    from app.services import form_filler_v3

    fill = form_filler_v3._fill_step_fields

    async def fill_then_attempt_nonfixture_request(surface, **kwargs):
        outcome = await fill(surface, **kwargs)
        await surface.evaluate("fetch('http://employer.invalid/fixture').catch(() => null)")
        return outcome

    monkeypatch.setattr(form_filler_v3, "_fill_step_fields", fill_then_attempt_nonfixture_request)
    record = await run_once(tmp_path, 1)
    assert record["status"] == "failed"
    assert record["blocked_requests"] == [{"url": "http://employer.invalid/fixture", "method": "GET"}]
    assert not record["checks"]["no_nonfixture_requests"]
    assert record["checks"]["trace_retained"]
    assert record["checks"]["browser_shutdown"]
