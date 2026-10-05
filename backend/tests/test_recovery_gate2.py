"""Synthetic negative controls. No public employer network requests."""
import json
import os
import sqlite3
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

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
        "browser": {"owner": "playwright", "type": "chromium", "args": list(gate.BROWSER_ARGS)},
        "worker_witness": {"installed": True, "completed": True, "errors": [],
                           "targets": [{"type": "page", "url": URL}],
                           "final_targets": [{"type": "page", "url": URL}]},
        "dom": {"guard_installed": True, "observations": [],
                "snapshot": {"submits": 0, "programmatic": 0, "clicks": [], "shared_workers": 0}},
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
    "trace", "boundary", "verified_fields", "field_readbacks", "flow_invocation", "worker_witness",
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
        try:
            await original(context, url, record)
        finally:
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


PASSIVE_WIDGETS = '''<div class="grecaptcha-badge" data-security-widget="badge"></div>
<iframe title="reCAPTCHA" data-security-widget="passive"
src="https://www.google.com/recaptcha/api2/anchor?size=invisible"></iframe>'''
WIDGET_AUDIT = '''<script>
window.__widgetAudit={calls:{execute:0,reset:0,render:0},clicks:0,mutations:0};
window.grecaptcha=Object.fromEntries(['execute','reset','render'].map(name=>
  [name,()=>{window.__widgetAudit.calls[name]++}]));
const widgets=[...document.querySelectorAll('[data-security-widget]')];
addEventListener('click',event=>{
  if(widgets.some(widget=>widget.contains(event.target)))window.__widgetAudit.clicks++;
},true);
new MutationObserver(events=>{for(const event of events){
  if(widgets.some(widget=>widget.contains(event.target) ||
    [...event.removedNodes].some(node=>node===widget || node.contains?.(widget))))
    window.__widgetAudit.mutations++;
}}).observe(document.body,{attributes:true,childList:true,subtree:true});
</script>'''
MIXED_BOUNDARIES = [
    pytest.param('<iframe data-security-widget="challenge" title="Cloudflare" '
                 'src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/turnstile" '
                 'width="300" height="150"></iframe>', id="cloudflare"),
    pytest.param('<iframe data-security-widget="challenge" '
                 'src="https://www.google.com/recaptcha/api2/bframe"></iframe>', id="recaptcha"),
    pytest.param('<iframe data-security-widget="challenge" '
                 'src="https://hcaptcha.com/captcha"></iframe>', id="hcaptcha"),
    pytest.param('<div data-security-widget="challenge" data-sitekey="synthetic" '
                 'style="width:200px;height:100px">Choose an image</div>', id="sitekey"),
    pytest.param('<input data-security-widget="challenge" type="password">', id="login"),
    pytest.param('<div data-security-widget="challenge">Enter your verification code</div>', id="otp"),
    pytest.param('<div data-security-widget="challenge">Identity verification required</div>', id="identity"),
    pytest.param('<div data-security-widget="challenge">Checking your browser. '
                 'Security verification required</div>', id="anti-bot"),
]


CLOUDFLARE_CHALLENGE_HOST = "challenges.cloudflare.com"


def _is_cloudflare_challenge_iframe(fragment: str) -> bool:
    """Identify the Cloudflare case by parsed iframe URL host, never substring membership."""
    from bs4 import BeautifulSoup

    iframe = BeautifulSoup(fragment, "html.parser").find("iframe")
    if iframe is None:
        return False
    parsed = urlsplit(str(iframe.get("src") or ""))
    return parsed.scheme == "https" and parsed.hostname == CLOUDFLARE_CHALLENGE_HOST


@pytest.mark.parametrize(("fragment", "expected"), [
    ('<iframe src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/turnstile"></iframe>', True),
    ('<iframe src="HTTPS://Challenges.Cloudflare.com/turnstile"></iframe>', True),
    ('<iframe src="http://challenges.cloudflare.com/turnstile"></iframe>', False),
    ('<iframe src="https://challenges.cloudflare.com.attacker.test/turnstile"></iframe>', False),
    ('<iframe src="https://attacker.test/?next=https://challenges.cloudflare.com/"></iframe>', False),
    ('<iframe src="https://attacker.test/challenges.cloudflare.com"></iframe>', False),
    ('<iframe src="https://challenges.cloudflare.com@attacker.test/"></iframe>', False),
    ('<iframe src="https://notchallenges.cloudflare.com/"></iframe>', False),
    ('<div data-src="https://challenges.cloudflare.com/turnstile"></div>', False),
    ('<iframe title="challenges.cloudflare.com"></iframe>', False),
])
def test_cloudflare_case_is_identified_by_exact_parsed_host(fragment, expected):
    assert _is_cloudflare_challenge_iframe(fragment) is expected


def test_exactly_one_mixed_boundary_is_the_cloudflare_iframe():
    matches = [param.id for param in MIXED_BOUNDARIES if _is_cloudflare_challenge_iframe(param.values[0])]
    assert matches == ["cloudflare"]


@pytest.mark.asyncio
@pytest.mark.parametrize("challenge_html", MIXED_BOUNDARIES)
async def test_passive_widget_never_erases_independent_boundary(monkeypatch, tmp_path, challenge_html):
    from bs4 import BeautifulSoup

    html = HTML.replace('<body>', '<body>' + PASSIVE_WIDGETS + challenge_html + WIDGET_AUDIT)
    detector = gate.detect_blocking_challenge
    observed = []

    async def capture_detection(page):
        challenge = await detector(page)
        observed.append(challenge)
        return challenge

    monkeypatch.setattr(gate, "detect_blocking_challenge", capture_detection)
    result = await synthetic_run(monkeypatch, tmp_path, html)
    assert result["verdict"] == "NOT_PROVEN", result
    assert result["boundary"]["stopped"]
    assert result.get("filler", {}).get("calls", 0) == 0
    assert result["dom"]["snapshot"] == {"clicks": [], "submits": 0, "programmatic": 0, "shared_workers": 0}
    assert result["widget_audit"] == {
        "calls": {"execute": 0, "reset": 0, "render": 0}, "clicks": 0, "mutations": 0}
    assert result["trace"]["valid"]
    assert result["teardown"]["browser_closed"] and result["teardown"]["driver_stopped"]
    assert result["teardown"]["remaining"] == [] and result["cleanup_errors"] == []
    retained = BeautifulSoup((tmp_path / "run/failure-or-final.html").read_text(), "html.parser")
    original = BeautifulSoup(html, "html.parser")
    assert [str(node) for node in retained.select('[data-security-widget]')] == [
        str(node) for node in original.select('[data-security-widget]')]
    assert all(not retained.select_one('#' + key).get('value') for key in ('first', 'last', 'email'))
    if _is_cloudflare_challenge_iframe(challenge_html):
        assert observed[0]["reason_code"] == "captcha_detected"
        assert observed[0]["details"]["selector"] == 'iframe[src*="challenges.cloudflare.com" i]'
        assert observed[0]["details"]["visible"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("details", [
    {},
    {"selector": ".grecaptcha-badge"},
    {"selector": "iframe[src*=recaptcha]", "source": "https://www.google.com/recaptcha/api2/anchor?size=invisible"},
])
async def test_passive_widget_cannot_clear_positive_detector_evidence(monkeypatch, tmp_path, details):
    challenge = {"reason_code": "captcha_detected", "summary": "Independent detector stop", "details": details}

    async def detected(_page):
        return challenge

    monkeypatch.setattr(gate, "detect_blocking_challenge", detected)
    html = HTML.replace('<body>', '<body>' + PASSIVE_WIDGETS + WIDGET_AUDIT)
    result = await synthetic_run(monkeypatch, tmp_path, html)
    assert result["verdict"] == "NOT_PROVEN", result
    assert result["boundary"]["stopped"] and result["boundary"]["detected"] == challenge
    assert result.get("filler", {}).get("calls", 0) == 0
    assert result["dom"]["snapshot"] == {"clicks": [], "submits": 0, "programmatic": 0, "shared_workers": 0}
    assert result["widget_audit"] == {
        "calls": {"execute": 0, "reset": 0, "render": 0}, "clicks": 0, "mutations": 0}
    assert result["trace"]["valid"] and result["teardown"]["remaining"] == []


@pytest.mark.asyncio
async def test_passive_only_production_detection_is_observation_only(monkeypatch, tmp_path):
    detector = gate.detect_blocking_challenge
    observed = []

    async def capture_detection(page):
        challenge = await detector(page)
        observed.append(challenge)
        return challenge

    monkeypatch.setattr(gate, "detect_blocking_challenge", capture_detection)
    html = HTML.replace('<body>', '<body>' + PASSIVE_WIDGETS + WIDGET_AUDIT)
    result = await synthetic_run(monkeypatch, tmp_path, html)
    assert result["verdict"] == "PASS", result
    assert observed and all(challenge is None for challenge in observed)
    assert result["boundary"].get("passive_widgets")
    assert result["filler"]["calls"] > 0 and result["verified_fields"] >= 3
    assert result["dom"]["snapshot"] == {"clicks": [], "submits": 0, "programmatic": 0, "shared_workers": 0}
    assert result["widget_audit"] == {
        "calls": {"execute": 0, "reset": 0, "render": 0}, "clicks": 0, "mutations": 0}
    assert result["trace"]["valid"]
    assert result["teardown"]["browser_closed"] and result["teardown"]["driver_stopped"]
    assert result["teardown"]["remaining"] == [] and result["cleanup_errors"] == []


# ---------------------------------------------------------------------------
# H1: SharedWorker traffic bypasses context routes and request events.
# Real Chromium, loopback HTTP or in-memory routes only. Hosts other than the
# loopback fixture are unresolvable, so nothing can reach an external network.
# ---------------------------------------------------------------------------
NO_EXTERNAL_DNS = "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"
WORKER_POST = ("fetch(%s,{method:'POST',body:'synthetic-shared-worker-application'})"
               ".then(r=>self.r='status '+r.status).catch(e=>self.r=String(e));"
               "onconnect=e=>{const p=e.ports[0];setTimeout(()=>p.postMessage(self.r||'pending'),800)};")


@pytest.mark.parametrize("case", [
    "witness_missing", "witness_not_installed", "witness_incomplete", "witness_errors",
    "targets_missing", "final_missing", "no_page_target", "malformed_target",
    "shared_worker_target", "service_worker_target", "unknown_target", "final_shared_worker",
    "dom_shared_worker", "snapshot_shared_worker", "snapshot_count_missing", "engine_block_missing",
])
def test_shared_worker_and_witness_evidence_fail_closed(evidence, case):
    record, directory = evidence
    witness = record["worker_witness"]
    shared = {"type": "shared_worker", "url": "blob:https://job-boards.greenhouse.io/x"}
    {
        "witness_missing": lambda: record.pop("worker_witness"),
        "witness_not_installed": lambda: witness.update(installed=False),
        "witness_incomplete": lambda: witness.update(completed=False),
        "witness_errors": lambda: witness.update(errors=["Target.getTargets failed"]),
        "targets_missing": lambda: witness.pop("targets"),
        "final_missing": lambda: witness.update(final_targets=None),
        "no_page_target": lambda: witness.update(targets=[{"type": "iframe", "url": URL}]),
        "malformed_target": lambda: witness["targets"].append("shared_worker"),
        "shared_worker_target": lambda: witness["targets"].append(shared),
        "service_worker_target": lambda: witness["targets"].append({**shared, "type": "service_worker"}),
        "unknown_target": lambda: witness["targets"].append({**shared, "type": "auction_worklet"}),
        "final_shared_worker": lambda: witness["final_targets"].append(shared),
        "dom_shared_worker": lambda: record["dom"]["observations"].append(
            {"kind": "shared_worker", "url": "blob:x"}),
        "snapshot_shared_worker": lambda: record["dom"]["snapshot"].update(shared_workers=1),
        "snapshot_count_missing": lambda: record["dom"]["snapshot"].pop("shared_workers"),
        "engine_block_missing": lambda: record["browser"].update(args=["--no-sandbox"]),
    }[case]()
    assert gate.evaluate(record, directory), case


class _LoopbackSink:
    """Loopback-only fixture server that records every request it receives."""

    def __init__(self, pages):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        hits = self.hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?")[0]
                body, kind = pages.get(path, (None, None))
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("content-type", kind)
                self.end_headers()
                self.wfile.write(body.encode())

            def do_POST(self):
                length = int(self.headers.get("content-length") or 0)
                hits.append((self.command, self.path, self.rfile.read(length)))
                self.send_response(200)
                self.end_headers()

            def do_PUT(self):
                self.do_POST()

            def do_PATCH(self):
                self.do_POST()

            def do_DELETE(self):
                self.do_POST()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


SHARED_WORKER_PAGE = """<!doctype html><html><head><script>
window.__attempts = {};
const attempt = (name, factory) => {
  try { factory(); window.__attempts[name] = 'created'; }
  catch (error) { window.__attempts[name] = String(error.name || error); }
};
// Before DOMContentLoaded, from a same-origin script URL.
attempt('early', () => new SharedWorker('/worker.js?early'));
// blob: worker.
attempt('blob', () => new SharedWorker(URL.createObjectURL(
  new Blob([WORKER_SOURCE], {type: 'text/javascript'}))));
// Synchronously created about:blank iframe, before any navigation.
const blank = document.createElement('iframe');
document.documentElement.appendChild(blank);
attempt('about_blank', () => new blank.contentWindow.SharedWorker('/worker.js?blank'));
</script></head><body>
<iframe id="srcdoc" srcdoc="<script>
try{new SharedWorker('/worker.js?srcdoc');parent.__attempts.srcdoc='created'}
catch(e){parent.__attempts.srcdoc=String(e.name||e)}
</script>"></iframe>
<iframe id="child" src="/frame"></iframe>
</body></html>"""
SHARED_WORKER_FRAME = ("<script>try{new SharedWorker('/worker.js?iframe');parent.__attempts.iframe='created'}"
                       "catch(e){parent.__attempts.iframe=String(e.name||e)}</script>")
SHARED_WORKER_ATTEMPTS = {"early", "blob", "about_blank", "srcdoc", "iframe"}


async def _shared_worker_loopback_run(configuration):
    """Run the shared-worker page under one layer configuration of the gate."""
    from playwright.async_api import async_playwright

    worker = WORKER_POST % "'/shared-post'"
    page_html = SHARED_WORKER_PAGE.replace("WORKER_SOURCE", json.dumps(
        WORKER_POST % "location.origin.replace('blob:','')+'/shared-post'"))
    sink = _LoopbackSink({"/": (page_html, "text/html"), "/frame": (SHARED_WORKER_FRAME, "text/html"),
                          "/worker.js": (worker, "application/javascript")})
    engine = configuration in {"gate", "engine_only"}
    guard = configuration in {"gate", "guard_only"}
    args = [NO_EXTERNAL_DNS] + (list(gate.BROWSER_ARGS) if engine else ["--no-sandbox"])
    record = {"dom": {"observations": []}, "routed": []}
    manager = await async_playwright().start()
    try:
        try:
            browser = await manager.chromium.launch(headless=True, args=args)
        except Exception as exc:
            if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
                pytest.fail(str(exc))
            pytest.skip("Chromium not available locally; browser controls are mandatory in CI")
        session = await gate._install_worker_witness(browser, record)
        context = await browser.new_context(service_workers="block")
        await context.expose_binding("gate2Observe", lambda _source, event:
                                     record["dom"]["observations"].append(event))
        if guard:
            await context.add_init_script(gate.DOM_GUARD)

        async def route_guard(route):
            # Same policy shape as the gate: only read-only methods may continue.
            record["routed"].append((route.request.method, route.request.url))
            if route.request.method in {"GET", "HEAD"}:
                await route.fallback()
            else:
                await route.abort("blockedbyclient")
        await context.route("**/*", route_guard)
        page = await context.new_page()
        await page.goto(sink.origin + "/", wait_until="load")
        await page.wait_for_timeout(1500)
        record["attempts"] = await page.evaluate("window.__attempts")
        record["typeof"] = await page.evaluate("typeof SharedWorker")
        await gate._complete_worker_witness(session, record)
        await browser.close()
    finally:
        await manager.stop()
        sink.close()
    record["hits"] = list(sink.hits)
    return record


@pytest.mark.asyncio
async def test_unhardened_shared_worker_post_escapes_route_but_witness_sees_it():
    """Control: proves the fixture is sensitive. Context routes never see the POST."""
    record = await _shared_worker_loopback_run("control")
    assert record["attempts"] == {name: "created" for name in SHARED_WORKER_ATTEMPTS}
    assert any(path == "/shared-post" for _method, path, _body in record["hits"])
    assert not any(method == "POST" for method, _url in record["routed"])
    witness_errors = gate._worker_witness_errors(record["worker_witness"])
    assert any("shared_worker" in error for error in witness_errors), witness_errors


@pytest.mark.asyncio
@pytest.mark.parametrize("configuration", ["gate", "engine_only", "guard_only"])
async def test_shared_worker_cannot_mutate_in_any_frame(configuration):
    record = await _shared_worker_loopback_run(configuration)
    assert record["hits"] == []
    assert not any("created" == value for value in record["attempts"].values()), record["attempts"]
    assert set(record["attempts"]) == SHARED_WORKER_ATTEMPTS
    assert gate._worker_witness_errors(record["worker_witness"]) == []
    observed = [e for e in record["dom"]["observations"] if e.get("kind") == "shared_worker"]
    if configuration == "engine_only":
        assert record["typeof"] == "undefined" and observed == []
    else:
        # Main frame (early, blob), about:blank, srcdoc and a child document all report.
        assert len(observed) == len(SHARED_WORKER_ATTEMPTS)
        assert set(record["attempts"].values()) == {"SecurityError"}


def _shared_worker_html(where):
    worker = json.dumps(WORKER_POST % "'https://sink.invalid/application'")
    create = ("try{const w=new SharedWorker(URL.createObjectURL(new Blob([" + worker +
              "],{type:'text/javascript'})));w.port.onmessage=m=>{window.__widgetAudit={worker:m.data}};"
              "w.port.start()}catch(e){window.__widgetAudit={error:String(e.name||e)}}")
    if where == "main_frame":
        return HTML.replace("<body>", "<body><script>" + create + "</script>")
    if where == "iframe":
        return HTML.replace("</form>", '</form><iframe srcdoc="<script>' +
                            create.replace("window.__widgetAudit", "parent.__widgetAudit")
                            .replace('"', "&quot;") + '</script>"></iframe>')
    if where == "about_blank":
        return HTML.replace("<body>", "<body><script>const f=document.createElement('iframe');"
                            "document.body.appendChild(f);" +
                            create.replace("new SharedWorker", "new f.contentWindow.SharedWorker") +
                            "</script>")
    raise AssertionError(where)


def _no_external_dns(monkeypatch, args=None):
    monkeypatch.setattr(gate, "BROWSER_ARGS", tuple(args if args is not None else gate.BROWSER_ARGS)
                        + (NO_EXTERNAL_DNS,))


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["main_frame", "iframe", "about_blank"])
async def test_gate_shared_worker_attempt_is_blocked_and_not_proven(monkeypatch, tmp_path, where):
    _no_external_dns(monkeypatch)
    result = await synthetic_run(monkeypatch, tmp_path, _shared_worker_html(where))
    assert result["verdict"] == "NOT_PROVEN", result
    assert "SharedWorker attempted outside recorded network evidence" in result["violations"]
    assert result["widget_audit"] == {"error": "SecurityError"}
    assert any(e.get("kind") == "shared_worker" for e in result["dom"]["observations"])
    assert gate._worker_witness_errors(result["worker_witness"]) == []
    assert not any(t["type"] == "shared_worker" for t in result["worker_witness"]["targets"])
    assert result["trace"]["valid"] and result["teardown"]["remaining"] == []


@pytest.mark.asyncio
async def test_unrecorded_shared_worker_mutation_cannot_pass_on_witness_alone(monkeypatch, tmp_path):
    # Defeat both in-page and engine layers. The worker runs and attempts a POST
    # (unresolvable host) that no Playwright stream records; the witness must fail it.
    _no_external_dns(monkeypatch, args=("--no-sandbox", "--disable-dev-shm-usage"))
    monkeypatch.setattr(gate, "DOM_GUARD", gate.DOM_GUARD.replace(gate.SHARED_WORKER_GUARD, ""))
    result = await synthetic_run(monkeypatch, tmp_path, _shared_worker_html("main_frame"))
    assert result["verdict"] == "NOT_PROVEN", result
    assert "independent browser target witness missing or observed unrouted worker" in result["violations"]
    assert any(t["type"] == "shared_worker" for t in result["worker_witness"]["targets"])
    assert "worker" in (result["widget_audit"] or {}), result["widget_audit"]
    assert not any(e.get("kind") == "shared_worker" for e in result["dom"]["observations"])
    flat = [e.get("url", "") for stage in ("requests", "sent", "blocked", "failed", "finished")
            for e in result["network"][stage]]
    assert not any("sink.invalid" in url for url in flat)  # invisible to every recorded stream
    # Even with the engine-flag evidence restored, the witness alone keeps it NOT_PROVEN.
    record = json.loads(json.dumps(result))
    record["browser"]["args"] = list(record["browser"]["args"]) + [gate.SHARED_WORKER_DISABLED_ARG]
    assert gate.evaluate(record, tmp_path / "run") == [
        "independent browser target witness missing or observed unrouted worker"]


@pytest.mark.asyncio
async def test_dedicated_worker_like_recaptcha_enterprise_stays_routed_and_allowed(monkeypatch, tmp_path):
    # Run 37173569727 shows reCAPTCHA Enterprise loading webworker.js as a dedicated
    # Worker inside its anchor frame. Dedicated workers are context-routed, so the
    # witness must accept them (liveness) while their requests stay in the streams.
    _no_external_dns(monkeypatch)
    worker = json.dumps("fetch('https://www.recaptcha.net/recaptcha/enterprise/webworker.js')"
                        ".then(()=>postMessage('ok')).catch(e=>postMessage(String(e)))")
    script = ("<script>const w=new Worker(URL.createObjectURL(new Blob([" + worker +
              "],{type:'text/javascript'})));w.onmessage=m=>{window.__widgetAudit={worker:m.data}}</script>")
    result = await synthetic_run(monkeypatch, tmp_path, HTML.replace("</form>", "</form>" + script))
    assert result["verdict"] == "PASS", result
    assert any(t["type"] == "worker" for t in result["worker_witness"]["targets"])
    assert any("webworker.js" in e["url"] for e in result["network"]["requests"])
    assert result["widget_audit"] and "worker" in result["widget_audit"]


@pytest.mark.asyncio
async def test_dedicated_worker_post_remains_blocked_and_not_proven(monkeypatch, tmp_path):
    _no_external_dns(monkeypatch)
    worker = json.dumps("fetch('https://job-boards.greenhouse.io/applications',{method:'POST',body:'x'})"
                        ".then(()=>postMessage('sent')).catch(e=>postMessage(String(e)))")
    script = ("<script>const w=new Worker(URL.createObjectURL(new Blob([" + worker +
              "],{type:'text/javascript'})));w.onmessage=m=>{window.__widgetAudit={worker:m.data}}</script>")
    result = await synthetic_run(monkeypatch, tmp_path, HTML.replace("</form>", "</form>" + script))
    assert result["verdict"] == "NOT_PROVEN", result
    assert "unsafe network attempt" in result["violations"]
    assert any(e["method"] == "POST" for e in result["network"]["blocked"])
    assert not any(e["method"] == "POST" for e in result["network"]["finished"])


@pytest.mark.asyncio
async def test_missing_witness_completion_is_not_proven(monkeypatch, tmp_path):
    async def lost(session, record):
        return None
    monkeypatch.setattr(gate, "_complete_worker_witness", lost)
    result = await synthetic_run(monkeypatch, tmp_path)
    assert result["verdict"] == "NOT_PROVEN"
    assert result["violations"] == [
        "independent browser target witness missing or observed unrouted worker"]


@pytest.mark.asyncio
async def test_clean_run_witness_observes_only_routed_targets(monkeypatch, tmp_path):
    result = await synthetic_run(monkeypatch, tmp_path)
    assert result["verdict"] == "PASS", result
    witness = result["worker_witness"]
    assert witness["installed"] and witness["completed"] and witness["errors"] == []
    assert any(t["type"] == "page" for t in witness["targets"])
    assert gate.SHARED_WORKER_DISABLED_ARG in result["browser"]["args"]
    assert result["dom"]["snapshot"]["shared_workers"] == 0


# ---------------------------------------------------------------------------
# H2: retained real Greenhouse passive invisible-reCAPTCHA badge.
# Verbatim subtree from Gate 2 v1 artifact 11292382142 (run 37173569727,
# gate2-public-evidence/failure-or-final.html, artifact zip sha256
# f7bb6f02f589f39642b45e10261c13b01d036d79b9db1913d6f2ec0d2bb89695).
# Its visible nested .grecaptcha-logo (256x64) stopped v1 before the filler.
# ---------------------------------------------------------------------------
REAL_GREENHOUSE_BADGE = (
    '<div><div class="grecaptcha-badge" data-style="bottomright" style="width: 256px; height: 60px; '
    'display: block; transition: right 0.3s; position: fixed; bottom: 14px; right: -186px; '
    'box-shadow: gray 0px 0px 5px; border-radius: 2px; overflow: hidden;"><div class="grecaptcha-logo">'
    '<iframe title="reCAPTCHA" width="256" height="60" role="presentation" name="a-y1t4dpfhi03p" '
    'frameborder="0" scrolling="no" sandbox="allow-forms allow-popups allow-same-origin allow-scripts '
    'allow-top-navigation allow-modals allow-popups-to-escape-sandbox allow-storage-access-by-user-activation" '
    'src="https://www.recaptcha.net/recaptcha/enterprise/anchor?ar=1&amp;k=6LfmcbcpAAAAAChNTbhUShzUOAMj_wY9LQIvLFX0'
    '&amp;co=aHR0cHM6Ly9qb2ItYm9hcmRzLmdyZWVuaG91c2UuaW86NDQz&amp;hl=en&amp;v=guXhH0v-XMxlzmbTwqkaT4i5'
    '&amp;size=invisible&amp;anchor-ms=20000&amp;execute-ms=30000&amp;cb=lysr8v1r1gww"></iframe></div>'
    '<div class="grecaptcha-error"></div><textarea id="g-recaptcha-response-100000" '
    'name="g-recaptcha-response" class="g-recaptcha-response" style="width: 250px; height: 40px; '
    'border: 1px solid rgb(193, 193, 193); margin: 10px 25px; padding: 0px; resize: none; display: none;">'
    '</textarea></div><iframe style="display: none;"></iframe></div>'
)
REAL_ANCHOR = 'src="https://www.recaptcha.net/recaptcha/enterprise/anchor?ar=1&amp;'
VISIBLE_CHECKBOX_ANCHOR = ('<iframe title="reCAPTCHA" width="304" height="78" '
                           'src="https://www.google.com/recaptcha/api2/anchor?ar=1&amp;k=x&amp;size=normal"></iframe>')


def _badge_with(nested):
    """Insert extra markup inside the real badge, next to the genuine logo."""
    return REAL_GREENHOUSE_BADGE.replace('<div class="grecaptcha-error">', nested + '<div class="grecaptcha-error">')


H2_BLOCKING = [
    pytest.param(REAL_GREENHOUSE_BADGE.replace('class="grecaptcha-logo"',
                 'class="grecaptcha-logo" data-sitekey="synthetic"'), id="logo-sitekey"),
    pytest.param(REAL_GREENHOUSE_BADGE.replace('class="grecaptcha-error"',
                 'class="grecaptcha-error" data-sitekey="synthetic"'), id="error-sitekey"),
    pytest.param(REAL_GREENHOUSE_BADGE.replace("size=invisible", "size=normal"), id="badge-anchor-normal"),
    pytest.param(REAL_GREENHOUSE_BADGE.replace("size=invisible", "size=compact"), id="badge-anchor-compact"),
    pytest.param(REAL_GREENHOUSE_BADGE.replace("enterprise/anchor", "enterprise/bframe"), id="badge-bframe"),
    pytest.param(_badge_with('<div class="captcha-challenge" style="width:300px;height:200px">'
                             'Select all images</div>'), id="nested-challenge"),
    pytest.param(_badge_with('<div data-sitekey="synthetic" style="width:300px;height:80px"></div>'),
                 id="nested-sitekey"),
    pytest.param(_badge_with('<iframe width="400" height="580" '
                             'src="https://www.google.com/recaptcha/api2/bframe?hl=en"></iframe>'),
                 id="nested-bframe"),
    pytest.param(_badge_with('<iframe width="303" height="78" '
                             'src="https://newassets.hcaptcha.com/captcha/v1/index.html"></iframe>'),
                 id="nested-hcaptcha"),
    pytest.param(_badge_with('<iframe width="300" height="65" '
                             'src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/turnstile">'
                             '</iframe>'), id="nested-turnstile"),
    pytest.param(REAL_GREENHOUSE_BADGE.replace(' data-style="bottomright"', ''), id="badge-without-style"),
    pytest.param(REAL_GREENHOUSE_BADGE + '<iframe width="400" height="580" '
                 'src="https://www.google.com/recaptcha/api2/bframe?hl=en&amp;k=x"></iframe>', id="api2-bframe"),
    pytest.param(REAL_GREENHOUSE_BADGE + '<iframe width="400" height="580" '
                 'src="https://www.recaptcha.net/recaptcha/enterprise/bframe?hl=en&amp;k=x"></iframe>',
                 id="enterprise-bframe"),
    pytest.param(REAL_GREENHOUSE_BADGE + '<iframe width="400" height="580" '
                 'src="https://www.google.com/recaptcha/api2/bframe?size=invisible"></iframe>',
                 id="bframe-spoofed-invisible"),
    pytest.param(REAL_GREENHOUSE_BADGE + '<div class="g-recaptcha" data-sitekey="x">' + VISIBLE_CHECKBOX_ANCHOR
                 + '</div>', id="g-recaptcha-checkbox"),
    pytest.param(REAL_GREENHOUSE_BADGE + '<span id="recaptcha-anchor" role="checkbox" '
                 'class="recaptcha-checkbox" style="display:inline-block;width:28px;height:28px"></span>',
                 id="recaptcha-anchor"),
    pytest.param(REAL_GREENHOUSE_BADGE + '<div class="h-captcha" data-sitekey="x">'
                 '<iframe width="303" height="78" src="https://newassets.hcaptcha.com/captcha/v1/index.html">'
                 '</iframe></div>', id="hcaptcha"),
    pytest.param(REAL_GREENHOUSE_BADGE + '<div class="cf-turnstile" data-sitekey="x"><iframe width="300" '
                 'height="65" src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/turnstile">'
                 '</iframe></div>', id="turnstile"),
]


async def _production_detection(html, viewport=None):
    """Production detector on a static page. Every subresource is aborted in memory."""
    from playwright.async_api import async_playwright

    manager = await async_playwright().start()
    try:
        try:
            browser = await manager.chromium.launch(headless=True, args=[NO_EXTERNAL_DNS])
        except Exception as exc:
            if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
                pytest.fail(str(exc))
            pytest.skip("Chromium not available locally; browser controls are mandatory in CI")
        context = await browser.new_context(java_script_enabled=False, viewport={"width": 1280, "height": 720})
        await context.route("**/*", lambda route: route.abort("blockedbyclient"))
        page = await context.new_page()
        await page.set_content(html, wait_until="load")
        results = []
        for _ in range(3):  # Detection must be stable after layout.
            results.append(await gate.detect_blocking_challenge(page))  # exact gate binding
            await page.wait_for_timeout(200)
        await browser.close()
        return results
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_real_greenhouse_badge_logo_is_visible_but_production_observation_only():
    results = await _production_detection(HTML.replace("</form>", "</form>" + REAL_GREENHOUSE_BADGE))
    assert results == [None, None, None]


@pytest.mark.asyncio
@pytest.mark.parametrize("challenge_html", H2_BLOCKING)
async def test_production_detector_still_blocks_interactive_captcha_near_real_badge(challenge_html):
    results = await _production_detection(HTML.replace("</form>", "</form>" + challenge_html))
    assert all(result and result["reason_code"] == "captcha_detected" for result in results), results


@pytest.mark.asyncio
async def test_real_greenhouse_passive_badge_reaches_filler_without_interaction(monkeypatch, tmp_path):
    from bs4 import BeautifulSoup

    detector = gate.detect_blocking_challenge
    observed = []

    async def capture_detection(page):
        challenge = await detector(page)
        observed.append(challenge)
        return challenge

    monkeypatch.setattr(gate, "detect_blocking_challenge", capture_detection)
    # Playwright's own screenshot briefly toggles inline caret-color on textareas
    # (form.png retention); that restored toggle is not a widget mutation.
    audit = ("<script>window.__widgetAudit={calls:{execute:0,reset:0,render:0},clicks:0,mutations:0};"
             "window.grecaptcha=Object.fromEntries(['execute','reset','render'].map(name=>"
             "[name,()=>{window.__widgetAudit.calls[name]++}]));"
             "const badge=document.querySelector('.grecaptcha-badge');"
             "const caret=v=>String(v||'').replace(/ ?caret-color: transparent !important;/,'');"
             "addEventListener('click',e=>{if(badge.contains(e.target))window.__widgetAudit.clicks++},true);"
             "new MutationObserver(m=>{for(const r of m){if(r.attributeName==='style'&&"
             "caret(r.oldValue)===caret(r.target.getAttribute('style')))continue;"
             "window.__widgetAudit.mutations++}})"
             ".observe(badge,{attributes:true,attributeOldValue:true,childList:true,subtree:true});</script>")
    html = HTML.replace("</form>", "</form>" + REAL_GREENHOUSE_BADGE + audit)
    result = await synthetic_run(monkeypatch, tmp_path, html)
    assert result["verdict"] == "PASS", result
    assert observed and all(challenge is None for challenge in observed)
    assert result["boundary"]["passive_widgets"] and not result["boundary"].get("stopped")
    assert result["filler"]["calls"] > 0 and result["verified_fields"] >= 3
    assert result["dom"]["snapshot"] == {"clicks": [], "submits": 0, "programmatic": 0, "shared_workers": 0}
    assert result["widget_audit"] == {"calls": {"execute": 0, "reset": 0, "render": 0}, "clicks": 0, "mutations": 0}
    retained = BeautifulSoup((tmp_path / "run/form.html").read_text(), "html.parser")
    original = BeautifulSoup(REAL_GREENHOUSE_BADGE, "html.parser")
    assert str(retained.select_one(".grecaptcha-badge")) == str(original.select_one(".grecaptcha-badge"))


H2_GATE_BLOCKING = [
    *[param for param in H2_BLOCKING if param.id in {
        "badge-anchor-normal", "nested-challenge", "nested-sitekey", "nested-bframe", "logo-sitekey", "error-sitekey",
        "enterprise-bframe", "g-recaptcha-checkbox", "hcaptcha", "turnstile"}],
    pytest.param(REAL_GREENHOUSE_BADGE + '<input type="password" aria-label="Password">', id="login"),
    pytest.param(REAL_GREENHOUSE_BADGE + "<p>Enter your verification code</p>", id="otp"),
    pytest.param(REAL_GREENHOUSE_BADGE + "<p>Multi-factor authentication</p>", id="mfa"),
    pytest.param(REAL_GREENHOUSE_BADGE + "<p>Identity verification required</p>", id="identity"),
    pytest.param(REAL_GREENHOUSE_BADGE + "<p>Checking your browser</p>", id="cloudflare-text"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("challenge_html", H2_GATE_BLOCKING)
async def test_real_badge_never_hides_interactive_boundary_in_gate(monkeypatch, tmp_path, challenge_html):
    result = await synthetic_run(monkeypatch, tmp_path, HTML.replace("</form>", "</form>" + challenge_html))
    assert result["verdict"] == "NOT_PROVEN", result
    assert result["boundary"]["stopped"] and result["boundary"]["detected"]
    assert result.get("filler", {}).get("calls", 0) == 0
    assert result["dom"]["snapshot"]["clicks"] == []
    assert result["trace"]["valid"] and result["teardown"]["remaining"] == []


@pytest.mark.asyncio
async def test_real_badge_cannot_clear_positive_detector_result(monkeypatch, tmp_path):
    challenge = {"reason_code": "captcha_detected", "summary": "Independent detector stop",
                 "details": {"selector": '[class*="captcha" i]', "width": 256, "height": 64}}

    async def detected(_page):
        return challenge

    monkeypatch.setattr(gate, "detect_blocking_challenge", detected)
    result = await synthetic_run(monkeypatch, tmp_path, HTML.replace("</form>", "</form>" + REAL_GREENHOUSE_BADGE))
    assert result["verdict"] == "NOT_PROVEN", result
    assert result["boundary"]["detected"] == challenge
    assert result.get("filler", {}).get("calls", 0) == 0
