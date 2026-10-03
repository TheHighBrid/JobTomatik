"""Actual browser proof and negative controls for the fixture-only boundary."""

import asyncio
import json
import threading
import zipfile
from pathlib import Path

import pytest
from scripts.run_onehost_fixture_gate import (
    _child_processes,
    request_allowed,
    run_gate,
    run_once,
)


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
@pytest.mark.parametrize("exception_type", [RuntimeError, AttributeError, TypeError])
async def test_fill_failure_retains_trace_and_shuts_down(monkeypatch, tmp_path, exception_type):
    from app.services import form_filler_v3

    async def fail_fill(*_args, **_kwargs):
        raise exception_type("Injected fixture fill failure")

    monkeypatch.setattr(form_filler_v3, "_fill_step_fields", fail_fill)
    record = await run_once(tmp_path, 1)
    assert record["status"] == "failed"
    assert "Injected fixture fill failure" in record["errors"][0]
    assert record["checks"]["browser_shutdown"]
    assert record["checks"]["server_shutdown"]
    assert record["checks"]["trace_retained"]
    assert json.loads((tmp_path / "run-001/evidence.json").read_text()) == record


@pytest.mark.asyncio
@pytest.mark.parametrize("exception_type", [asyncio.CancelledError, KeyboardInterrupt, SystemExit])
async def test_process_control_exception_propagates_after_cleanup(monkeypatch, tmp_path, exception_type):
    from app.services import form_filler_v3

    async def interrupt_fill(*_args, **_kwargs):
        raise exception_type("Injected process-control interruption")

    monkeypatch.setattr(form_filler_v3, "_fill_step_fields", interrupt_fill)
    baseline = _child_processes()
    with pytest.raises(exception_type):
        await run_once(tmp_path, 1)
    assert not set(_child_processes().items()) - set(baseline.items())
    assert not any(thread.name == "onehost-fixture-server" for thread in threading.enumerate())
    with zipfile.ZipFile(tmp_path / "run-001/trace.zip") as archive:
        assert archive.testzip() is None


@pytest.mark.asyncio
async def test_final_submit_sensor_detects_a_click_even_without_a_post(monkeypatch, tmp_path):
    from app.services import form_filler_v3

    fill = form_filler_v3._fill_step_fields

    async def fill_then_click_fixture_submit(surface, **kwargs):
        outcome = await fill(
            surface, profile=kwargs["profile"], cover_letter=kwargs["cover_letter"],
            resume_path=kwargs["resume_path"], log=kwargs["log"], step_number=kwargs["step_number"],
        )
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
        outcome = await fill(
            surface, profile=kwargs["profile"], cover_letter=kwargs["cover_letter"],
            resume_path=kwargs["resume_path"], log=kwargs["log"], step_number=kwargs["step_number"],
        )
        await surface.evaluate("fetch('http://employer.invalid/fixture').catch(() => null)")
        return outcome

    monkeypatch.setattr(form_filler_v3, "_fill_step_fields", fill_then_attempt_nonfixture_request)
    record = await run_once(tmp_path, 1)
    assert record["status"] == "failed"
    assert record["blocked_requests"] == [{"url": "http://employer.invalid/fixture", "method": "GET"}]
    assert not record["checks"]["no_nonfixture_requests"]
    assert record["checks"]["trace_retained"]
    assert record["checks"]["browser_shutdown"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["ws", "wss"])
async def test_websocket_attempt_is_closed_before_upstream_and_fails_proof(monkeypatch, tmp_path, scheme):
    from app.services import form_filler_v3

    fill = form_filler_v3._fill_step_fields
    url = f"{scheme}://employer.invalid/fixture"
    close_codes = []

    async def fill_then_attempt_websocket(surface, **kwargs):
        outcome = await fill(
            surface, profile=kwargs["profile"], cover_letter=kwargs["cover_letter"],
            resume_path=kwargs["resume_path"], log=kwargs["log"], step_number=kwargs["step_number"],
        )
        close_codes.append(await surface.evaluate("""url => new Promise(resolve => {
            const socket = new WebSocket(url);
            socket.onclose = event => resolve(event.code);
            socket.onerror = () => resolve('network_error');
            setTimeout(() => resolve('timeout'), 1500);
        })""", url))
        return outcome

    monkeypatch.setattr(form_filler_v3, "_fill_step_fields", fill_then_attempt_websocket)
    record = await run_once(tmp_path, 1)
    assert close_codes == [1008]
    assert record["status"] == "failed" and record["errors"] == []
    assert record["blocked_requests"] == [{"url": url, "method": "WEBSOCKET"}]
    assert not record["checks"]["no_nonfixture_requests"]
    assert record["checks"]["current_flow_ready"]
    assert record["http_requests"] == [{"method": "GET", "path": "/fixture"}]
    assert all(record["checks"][key] for key in ["trace_retained", "browser_shutdown", "server_shutdown"])
