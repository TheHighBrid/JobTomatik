"""Synthetic negative controls. No public employer network requests."""
import json
import os
import sqlite3
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services import recovery_gate2 as gate

URL = "https://job-boards.greenhouse.io/gate2fixture/jobs/1234567"
TELEMETRY = "https://c.spl.greenhouse.io/com.snowplowanalytics.snowplow/tp2"
HTML = """<!doctype html><html><body><form id="application_form">
<label for="first">First Name</label><input id="first" name="first_name">
<label for="last">Last Name</label><input id="last" name="last_name">
<label for="email">Email</label><input id="email" name="email" type="email">
<button id="submit_app" type="submit">Submit Application</button>
</form></body></html>"""


def source():
    inputs = {"backend/app/services/recovery_gate2.py": "0" * 64,
              "backend/app/services/ats_greenhouse.py": "1" * 64,
              "backend/app/services/form_filler_v3.py": "2" * 64}
    return {"git_sha": "a" * 40, "inputs": inputs,
            "source_sha256": gate.digest(json.dumps(inputs, sort_keys=True).encode())}


@pytest.fixture
def evidence(tmp_path):
    reservation = gate.claim_attempt(tmp_path / "ledger.sqlite", gate.identity(URL))
    with zipfile.ZipFile(tmp_path / "trace.zip", "w") as archive:
        archive.writestr("0.trace", '{"type":"context-options","browserName":"chromium"}\n')
    record = {
        "source": source(), "target_url": URL, "detected_identity": gate.identity(URL),
        "dry_run": True, "synthetic_profile": dict(gate.PROFILE),
        "adapter": {"callable": gate.ADAPTER, "name": "greenhouse", "source_sha256": "1" * 64},
        "filler": {"callable": gate.FILLER, "calls": 1, "source_sha256": "2" * 64},
        "flow_invocation": {"dry_run": True},
        "browser": {"owner": "playwright", "type": "chromium"},
        "dom": {"guard_installed": True, "observations": [],
                "snapshot": {"submits": 0, "programmatic": 0, "clicks": []}},
        "network": {"guard_installed": True, "requests": [], "sent": [], "blocked": [],
                    "failed": [], "finished": [], "websockets": []},
        "duplicate": reservation,
        "teardown": {"browser_closed": True, "driver_stopped": True, "tracked_count": 2, "remaining": []},
        "trace": gate.trace_evidence(tmp_path / "trace.zip"),
        "boundary": {"checks": 3, "bypassed": False, "detected": None},
        "verified_fields": 1, "field_readbacks": [{"matched": True, "expected_sha256": "x", "observed_sha256": "x"}],
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



def add_aborted_telemetry(record):
    event = {"request_id": "request-1", "method": "POST", "url": TELEMETRY,
             "body_sha256": gate.digest(b"synthetic")}
    for stage in ("requests", "sent"):
        record["network"][stage].append(dict(event))
    record["network"]["blocked"].append({**event, "abort_succeeded": True})
    record["network"]["failed"].append({**event, "failure": "net::ERR_BLOCKED_BY_CLIENT"})
    return event


def add_trace_mutation(record, directory, event, *, aborted=True, status=-1,
                       failure="net::ERR_BLOCKED_BY_CLIENT.Inspector", body=b"synthetic", copies=1):
    with zipfile.ZipFile(directory / "trace.zip", "a") as archive:
        archive.writestr("0.network", "\n".join(json.dumps({"snapshot": {
            "request": {"method": event["method"], "url": event["url"],
                        "postData": {"text": body.decode()}},
            "_wasAborted": aborted, "response": {"status": status, "_failureText": failure},
        }}) for _ in range(copies)))
    record["trace"] = gate.trace_evidence(directory / "trace.zip")


def test_aborted_snowplow_telemetry_is_not_an_application_mutation(evidence):
    record, directory = evidence
    event = add_aborted_telemetry(record)
    add_trace_mutation(record, directory, event)
    assert gate.evaluate(record, directory) == []


def test_application_post_still_fails_when_telemetry_is_also_blocked(evidence):
    record, directory = evidence
    add_aborted_telemetry(record)
    record["network"]["sent"].append({"method": "POST", "url": URL})
    assert "application POST or other mutation sent" in gate.evaluate(record, directory)


@pytest.mark.parametrize("case", [
    "finished", "finished_other_id", "no_blocked", "no_failed", "abort_failed",
    "failed_connection", "different_id", "different_url", "different_body",
    "duplicate_id", "extra_sent", "trace_only", "trace_completed", "trace_response",
    "trace_not_blocked", "trace_other_body", "trace_duplicate", "missing_hash",
])
def test_telemetry_requires_independent_abort_lifecycle(evidence, case):
    record, directory = evidence
    event = add_aborted_telemetry(record)
    network = record["network"]

    def clear_lifecycle():
        for stage in ("requests", "sent", "blocked", "failed"):
            network[stage].clear()

    mutations = {
        "finished": lambda: network["finished"].append(dict(event)),
        "finished_other_id": lambda: network["finished"].append({**event, "request_id": "other"}),
        "no_blocked": network["blocked"].clear,
        "no_failed": network["failed"].clear,
        "abort_failed": lambda: network["blocked"][0].update(abort_succeeded=False),
        "failed_connection": lambda: network["failed"][0].update(failure="net::ERR_CONNECTION_RESET"),
        "different_id": lambda: network["failed"][0].update(request_id="other"),
        "different_url": lambda: network["failed"][0].update(url=URL),
        "different_body": lambda: network["failed"][0].update(body_sha256="b" * 64),
        "duplicate_id": lambda: network["sent"].append(dict(event)),
        "extra_sent": lambda: network["sent"].append({**event, "request_id": "other"}),
        "trace_only": clear_lifecycle,
        "missing_hash": lambda: network["blocked"][0].pop("body_sha256"),
    }
    trace_options = {
        "trace_completed": {"aborted": False, "status": 200, "failure": None},
        "trace_response": {"status": 200},
        "trace_not_blocked": {"failure": "net::ERR_CONNECTION_RESET"},
        "trace_other_body": {"body": b"different"},
        "trace_duplicate": {"copies": 2},
    }
    if case in mutations:
        mutations[case]()
    add_trace_mutation(record, directory, event, **trace_options.get(case, {}))
    assert gate.evaluate(record, directory), case
    if case.startswith("finished"):
        assert "completed application mutation" in gate.evaluate(record, directory)


@pytest.mark.parametrize("url", [
    "https://c.spl.greenhouse.io.attacker.test/com.snowplowanalytics.snowplow/tp2",
    "https://fake-snowplow-example.test/tp2", "https://snowplow.example.invalid/tp2",
    "https://evil-google-analytics.com/tp2", "https://collector.snowplow.io/tp2",
    "https://sub.c.spl.greenhouse.io/com.snowplowanalytics.snowplow/tp2",
    "https://c.spl.greenhouse.io/applications", TELEMETRY + "?application=1",
    TELEMETRY + "#fragment", TELEMETRY.replace("https:", "http:"),
    TELEMETRY.replace(".io/", ".io:444/"), TELEMETRY.replace("https://", "https://user@"),
])
def test_telemetry_lookalikes_and_unapproved_endpoints_fail(evidence, url):
    record, directory = evidence
    event = add_aborted_telemetry(record)
    for stage in ("requests", "sent", "blocked", "failed"):
        record["network"][stage][0]["url"] = url
    add_trace_mutation(record, directory, {**event, "url": url})
    assert "unsafe network attempt" in gate.evaluate(record, directory)


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "UNKNOWN", None])
def test_other_methods_unsafe_even_at_telemetry_endpoint(evidence, method):
    record, directory = evidence
    add_aborted_telemetry(record)
    for stage in ("requests", "sent", "blocked", "failed"):
        record["network"][stage][0]["method"] = method
    assert gate.evaluate(record, directory)


@pytest.mark.parametrize("stage", ["requests", "sent", "blocked", "failed", "finished"])
def test_missing_lifecycle_stream_fails_closed(evidence, stage):
    record, directory = evidence
    record["network"].pop(stage)
    assert "network evidence missing" in gate.evaluate(record, directory)


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_read_only_methods_remain_non_mutating(evidence, method):
    record, directory = evidence
    record["network"]["sent"].append({"method": method, "url": URL})
    record["network"]["finished"].append({"method": method, "url": URL})
    assert gate.evaluate(record, directory) == []


@pytest.mark.asyncio
async def test_passive_invisible_badge_does_not_stop_or_get_clicked(monkeypatch, tmp_path):
    html = HTML.replace(
        "<body>",
        '<body><div class="grecaptcha-badge"></div>'
        '<iframe title="reCAPTCHA" src="https://www.google.com/recaptcha/api2/anchor?size=invisible"></iframe>'
        '<script>window.__widgetAudit={calls:0,mutations:0};'
        'window.grecaptcha={execute:()=>{window.__widgetAudit.calls++},'
        'reset:()=>{window.__widgetAudit.calls++},render:()=>{window.__widgetAudit.calls++}};'
        'new MutationObserver(events=>{for(const event of events){'
        'if(event.target.matches?.(".grecaptcha-badge,iframe[title=reCAPTCHA]"))'
        'window.__widgetAudit.mutations++}}).observe(document.body,{attributes:true,subtree:true});</script>',
    )
    result = await synthetic_run(monkeypatch, tmp_path, html)
    assert result["verdict"] == "PASS", result
    assert result["boundary"].get("stopped") is not True
    assert result["filler"]["calls"] > 0
    assert result["boundary"].get("passive_widgets")
    assert result["dom"]["snapshot"]["clicks"] == []
    assert result["widget_audit"] == {"calls": 0, "mutations": 0}
    from bs4 import BeautifulSoup
    retained = BeautifulSoup((tmp_path / "run/form.html").read_text(), "html.parser")
    assert retained.select_one(".grecaptcha-badge").attrs == {"class": ["grecaptcha-badge"]}
    assert retained.select_one('iframe[title="reCAPTCHA"]').attrs == {
        "title": "reCAPTCHA", "src": "https://www.google.com/recaptcha/api2/anchor?size=invisible"}


@pytest.mark.asyncio
async def test_real_browser_aborted_snowplow_lifecycle(monkeypatch, tmp_path):
    script = f"fetch('{TELEMETRY}', {{method:'POST',body:'synthetic'}}).catch(()=>{{}})"
    html = HTML.replace('<input id="first" name="first_name">',
        '<input id="first" name="first_name" onchange="' + script.replace('"', '&quot;') + '">')
    result = await synthetic_run(monkeypatch, tmp_path, html)
    assert result["verdict"] == "PASS", result
    network = result["network"]
    aborted = gate._proven_aborted_telemetry(network)
    assert len(aborted) == 1
    request_id = aborted[0]["request_id"]
    assert all(any(e["request_id"] == request_id for e in network[stage])
               for stage in ("requests", "sent", "failed"))
    assert not any(e["method"] == "POST" for e in network["finished"])
    assert len(result["trace"]["mutating_requests"]) == 1
    assert result["trace"]["mutating_requests"][0]["aborted"] is True
    assert result["teardown"]["remaining"] == []


@pytest.mark.asyncio
async def test_real_browser_completed_telemetry_fails_despite_route_abort_claim(monkeypatch, tmp_path):
    # Synthetic corrupted guard, fulfilled entirely in memory. Independent terminal
    # and trace signals must defeat the claimed route abort without any upstream POST.
    from playwright.async_api import Route
    original = Route.abort

    async def incorrect_abort(route, *args, **kwargs):
        if route.request.url == TELEMETRY:
            await route.fulfill(status=200, body="synthetic", headers={"Access-Control-Allow-Origin": "*"})
        else:
            await original(route, *args, **kwargs)

    monkeypatch.setattr(Route, "abort", incorrect_abort)
    script = f"fetch('{TELEMETRY}', {{method:'POST',body:'synthetic'}}).catch(()=>{{}})"
    html = HTML.replace('<input id="first" name="first_name">',
        '<input id="first" name="first_name" onchange="' + script.replace('"', '&quot;') + '">')
    result = await synthetic_run(monkeypatch, tmp_path, html)
    assert result["verdict"] == "NOT_PROVEN", result
    assert "completed application mutation" in result["violations"]
    assert "trace contains application POST or other mutation" in result["violations"]
    assert any(e["method"] == "POST" for e in result["network"]["finished"])
    assert result["trace"]["valid"] and result["teardown"]["remaining"] == []


def test_retained_duplicate_database_is_required(evidence):
    record, directory = evidence
    (directory / "ledger.sqlite").unlink()
    assert "retained duplicate ledger missing or invalid" in gate.evaluate(record, directory)


def test_trace_network_overrides_false_clean_json(evidence):
    record, directory = evidence
    with zipfile.ZipFile(directory / "trace.zip", "a") as archive:
        archive.writestr("0.network", json.dumps({"snapshot": {"request": {"method": "POST", "url": URL}}}))
    record["trace"] = gate.trace_evidence(directory / "trace.zip")
    assert "trace contains application POST or other mutation" in gate.evaluate(record, directory)


@pytest.mark.parametrize("key", [
    "source", "target_url", "detected_identity", "dry_run", "synthetic_profile",
    "adapter", "filler", "browser", "dom", "network", "duplicate", "teardown",
    "trace", "boundary", "verified_fields", "field_readbacks", "flow_invocation",
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
        record["widget_audit"] = await record["page"].evaluate("window.__widgetAudit || null")
    monkeypatch.setattr(gate, "_exercise", fixture)
    def actual_source():
        result = source()
        result["git_sha"] = subprocess.check_output(
            ["git", "-C", str(gate.ROOT), "rev-parse", "HEAD"]).decode().strip()
        for path in result["inputs"]:
            result["inputs"][path] = gate.digest((gate.ROOT / path).read_bytes())
        result["source_sha256"] = gate.digest(json.dumps(result["inputs"], sort_keys=True).encode())
        return result
    monkeypatch.setattr(gate, "provenance", actual_source)
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
    "document.querySelector('form').dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))",
    "fetch(location.href, {method:'POST',body:'synthetic'}).catch(()=>{})",
    "fetch(location.href, {method:'PUT',body:'synthetic'}).catch(()=>{})",
    "fetch(location.href, {method:'PATCH',body:'synthetic'}).catch(()=>{})",
    "fetch(location.href, {method:'DELETE'}).catch(()=>{})",
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
    "Multi-factor authentication", "Identity verification required",
    '<input type="password" aria-label="Password">',
    '<iframe src="https://www.google.com/recaptcha/api2/bframe"></iframe>',
    '<iframe src="https://www.recaptcha.net/recaptcha/enterprise/bframe"></iframe>',
    '<iframe src="https://hcaptcha.com/captcha"></iframe>',
    '<div class="grecaptcha-badge"></div><iframe src="https://www.google.com/recaptcha/api2/bframe"></iframe>',
    '<div class="grecaptcha-badge"></div><iframe src="https://www.google.com/recaptcha/api2/anchor?size=normal"></iframe>',
    '<div class="grecaptcha-badge"></div>Complete the CAPTCHA',
    '<div class="grecaptcha-badge"></div><div class="captcha-challenge">Choose an image</div>',
    '<div class="grecaptcha-badge"></div><iframe src="https://hcaptcha.com/captcha"></iframe>',
    '<div class="grecaptcha-badge"></div>Multi-factor authentication',
    '<div class="grecaptcha-badge"></div><input type="password">',
])
async def test_security_boundary_stops_without_filling(monkeypatch, tmp_path, boundary):
    result = await synthetic_run(monkeypatch, tmp_path, HTML.replace("<body>", "<body>" + boundary))
    assert result["verdict"] == "NOT_PROVEN"
    assert result["boundary"]["stopped"]
    assert result.get("filler", {}).get("calls", 0) == 0
    assert result["trace"]["valid"] and result["teardown"]["remaining"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("form", [
    "", '<form><input type="hidden" name="first_name"><button type="submit">Submit</button></form>',
    '<form><input name="first_name" disabled></form>',
    '<form hidden><input name="first_name"></form>',
])
async def test_passive_badge_without_usable_form_fails(monkeypatch, tmp_path, form):
    html = '<html><body><div class="grecaptcha-badge"></div>' + form + '</body></html>'
    result = await synthetic_run(monkeypatch, tmp_path, html)
    assert result["verdict"] == "NOT_PROVEN"
    assert not result["boundary"].get("passive_widgets")
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


@pytest.mark.asyncio
async def test_browser_shutdown_failure_invalidates_proof(monkeypatch, tmp_path):
    from playwright.async_api import Browser
    original = Browser.close

    async def close_and_fail(browser, *args, **kwargs):
        await original(browser, *args, **kwargs)
        raise RuntimeError("synthetic teardown failure")

    monkeypatch.setattr(Browser, "close", close_and_fail)
    result = await synthetic_run(monkeypatch, tmp_path)
    assert result["verdict"] == "NOT_PROVEN" and result["trace"]["valid"]
    assert any("synthetic teardown failure" in item for item in result["cleanup_errors"])


@pytest.mark.asyncio
async def test_trace_loss_after_startup_invalidates_proof(monkeypatch, tmp_path):
    from pathlib import Path

    async def inject(context):
        tracing_class = type(context.tracing)
        original = tracing_class.stop

        async def stop_and_lose_trace(tracing, *args, **kwargs):
            await original(tracing, *args, **kwargs)
            Path(kwargs["path"]).unlink()

        monkeypatch.setattr(tracing_class, "stop", stop_and_lose_trace)

    result = await synthetic_run(monkeypatch, tmp_path, inject=inject)
    assert result["verdict"] == "NOT_PROVEN" and result["browser_started"]
    assert "trace missing or invalid" in result["violations"]
    assert result["teardown"]["remaining"] == []
