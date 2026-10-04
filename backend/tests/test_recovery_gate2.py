"""Synthetic negative controls. No public employer network requests."""
import copy
import json
import os
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services import recovery_gate2 as gate

URL = "https://job-boards.greenhouse.io/gate2fixture/jobs/1234567"
HTML = """<!doctype html><html><body><form id="application_form">
<label for="first">First Name</label><input id="first" name="first_name">
<label for="last">Last Name</label><input id="last" name="last_name">
<label for="email">Email</label><input id="email" name="email" type="email">
<button id="submit_app" type="submit">Submit Application</button>
</form></body></html>"""


def source():
    inputs = {"backend/app/services/recovery_gate2.py": "0" * 64}
    return {"git_sha": "a" * 40, "inputs": inputs,
            "source_sha256": gate.digest(json.dumps(inputs, sort_keys=True).encode())}


@pytest.fixture
def evidence(tmp_path):
    with zipfile.ZipFile(tmp_path / "trace.zip", "w") as archive:
        archive.writestr("0.trace", '{"type":"context-options"}\n')
    record = {
        "source": source(), "target_url": URL, "detected_identity": gate.identity(URL),
        "dry_run": True, "synthetic_profile": dict(gate.PROFILE),
        "adapter": {"callable": gate.ADAPTER, "name": "greenhouse"},
        "filler": {"callable": gate.FILLER, "calls": 1},
        "browser": {"owner": "playwright", "type": "chromium"},
        "dom": {"guard_installed": True, "observations": [],
                "snapshot": {"submits": 0, "programmatic": 0, "clicks": []}},
        "network": {"guard_installed": True, "requests": [], "sent": [], "blocked": [], "websockets": []},
        "duplicate": {"reserved": True, "duplicate_rejected": True, "rows": 1, "key": "test"},
        "teardown": {"browser_closed": True, "driver_stopped": True, "tracked_count": 2, "remaining": []},
        "trace": gate.trace_evidence(tmp_path / "trace.zip"),
        "boundary": {"checks": 3, "bypassed": False, "detected": None},
        "verified_fields": 3,
    }
    assert gate.evaluate(record, tmp_path) == []
    return record, tmp_path


@pytest.mark.parametrize("case", [
    "submit_click", "native_submit", "application_post", "identity", "adapter",
    "filler", "dry_run", "trace", "teardown", "duplicate", "boundary", "source", "readback",
])
def test_evaluator_fails_closed(evidence, case):
    record, directory = evidence
    if case == "submit_click":
        record["dom"]["observations"].append({"kind": "click", "final": True})
    elif case == "native_submit":
        record["dom"]["observations"].append({"kind": "programmatic_submit"})
    elif case == "application_post":
        record["network"]["sent"].append({"method": "POST", "url": URL})
    elif case == "identity":
        record["detected_identity"]["job_id"] = "7654321"
    elif case == "adapter":
        record["adapter"]["name"] = "lever"
    elif case == "filler":
        record["filler"]["calls"] = 0
    elif case == "dry_run":
        record["dry_run"] = False
    elif case == "trace":
        (directory / "trace.zip").unlink()
    elif case == "teardown":
        record["teardown"]["remaining"] = [123]
    elif case == "duplicate":
        record["duplicate"]["duplicate_rejected"] = False
    elif case == "boundary":
        record["boundary"]["bypassed"] = True
    elif case == "source":
        record["source"]["inputs"]["new"] = "different"
    elif case == "readback":
        record["verified_fields"] = 0
    assert gate.evaluate(record, directory), case


@pytest.mark.parametrize("key", [
    "source", "target_url", "detected_identity", "dry_run", "synthetic_profile",
    "adapter", "filler", "browser", "dom", "network", "duplicate", "teardown",
    "trace", "boundary", "verified_fields",
])
def test_missing_required_evidence_fails_closed(evidence, key):
    record, directory = evidence
    record.pop(key)
    assert gate.evaluate(record, directory), key


@pytest.mark.parametrize("url", [
    "http://job-boards.greenhouse.io/acme/jobs/123", "https://evil.test/acme/jobs/123",
    "https://job-boards.greenhouse.io@evil.test/acme/jobs/123",
    "https://job-boards.greenhouse.io/acme", "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123",
])
def test_exact_public_identity_required(url):
    with pytest.raises(ValueError):
        gate.identity(url)


def test_duplicate_reservation_is_durable_and_atomic(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    target = gate.identity(URL)
    def claim():
        try:
            return gate.claim_attempt(ledger, target)
        except sqlite3.IntegrityError:
            return None
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: claim(), range(4)))
    winners = [result for result in results if result]
    assert len(winners) == 1 and winners[0]["duplicate_rejected"]
    with sqlite3.connect(ledger) as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        gate.claim_attempt(ledger, target)


async def synthetic_run(monkeypatch, tmp_path, html=HTML, inject=None):
    """Intercept the exact HTTPS target in memory, with no upstream connection."""
    original = gate._exercise
    async def fixture(context, url, record):
        record["evidence_kind"] = "synthetic_fixture"
        async def serve(route):
            if route.request.url == URL and route.request.method == "GET":
                await route.fulfill(status=200, content_type="text/html", body=html)
            else:
                await route.abort("blockedbyclient")
        await context.route("**/*", serve)
        if inject:
            await inject(context)
        await original(context, url, record)
    monkeypatch.setattr(gate, "_exercise", fixture)
    monkeypatch.setattr(gate, "provenance", source)
    result = await gate.run_gate(URL, tmp_path / "run", tmp_path / "ledger.sqlite")
    if not result["browser_started"] and "Executable doesn't exist" in result.get("error", ""):
        if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(result["error"])
        pytest.skip("Chromium not available locally; browser controls are mandatory in CI")
    return result


@pytest.mark.asyncio
async def test_production_adapter_filler_owned_browser_and_independent_review(monkeypatch, tmp_path):
    result = await synthetic_run(monkeypatch, tmp_path)
    assert result["verdict"] == "PASS", result
    assert result["verified_fields"] >= 3
    assert result["dom"]["snapshot"]["clicks"] == []
    assert result["network"]["blocked"] == []
    saved = json.loads((tmp_path / "run/summary.json").read_text())
    assert gate.evaluate(saved, tmp_path / "run") == []
    assert saved["evidence_kind"] == "synthetic_fixture"


@pytest.mark.asyncio
@pytest.mark.parametrize("script", [
    "document.querySelector('#submit_app').click()",
    "document.querySelector('form').submit()",
    "document.querySelector('form').requestSubmit()",
    "fetch(location.href, {method:'POST',body:'synthetic'}).catch(()=>{})",
    "location.href='https://job-boards.greenhouse.io/gate2fixture/jobs/7654321'",
    "new WebSocket('wss://job-boards.greenhouse.io/socket')",
])
async def test_browser_negative_controls(monkeypatch, tmp_path, script):
    html = HTML.replace('<input id="first" name="first_name">',
                        '<input id="first" name="first_name" onchange="' + script.replace('"', '&quot;') + '">')
    result = await synthetic_run(monkeypatch, tmp_path, html)
    assert result["verdict"] == "NOT_PROVEN", result
    assert result["trace"]["valid"]
    assert result["teardown"]["remaining"] == []
    assert not any(e["method"] == "POST" for e in result["network"]["finished"])


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", [
    "Verify you are human", "Enter your verification code", "Checking your browser",
    '<input type="password" aria-label="Password">',
])
async def test_security_boundary_stops_without_filling(monkeypatch, tmp_path, boundary):
    result = await synthetic_run(monkeypatch, tmp_path, HTML.replace("<body>", "<body>" + boundary))
    assert result["verdict"] == "NOT_PROVEN"
    assert result["boundary"]["stopped"]
    assert result.get("filler", {}).get("calls", 0) == 0
    assert result["trace"]["valid"] and result["teardown"]["remaining"] == []


@pytest.mark.asyncio
async def test_failure_after_startup_retains_trace_and_cleanup(monkeypatch, tmp_path):
    async def broken(*args, **kwargs):
        raise RuntimeError("synthetic fill failure")
    monkeypatch.setattr(gate, "_fill_step_fields", broken)
    result = await synthetic_run(monkeypatch, tmp_path)
    assert result["verdict"] == "NOT_PROVEN"
    assert result["trace"]["valid"] and result["teardown"]["remaining"] == []
    assert "synthetic fill failure" in result["error"]
