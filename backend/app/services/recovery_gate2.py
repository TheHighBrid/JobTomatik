"""Auditable, synthetic-only Greenhouse recovery proof. No application writes.

This proves the production adapter, v3 field filler and ATS flow, not API/Celery
dispatch, submission readiness, retained handoffs or adapter promotion.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import importlib.metadata
import json
import os
import re
import sqlite3
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from app.services.ats_flow import run_ats_application_flow
from app.services.ats_greenhouse import GreenhouseAdapter, parse_greenhouse_job_url
from app.services.ats_registry import detect_ats_adapter
from app.services.browser_navigation import detect_blocking_challenge
from app.services import form_filler as _production_compat  # Install production control compatibility.
from app.services.form_filler_v3 import _fill_step_fields
from app.services.operational_safety import require_browser_entry_allowed
from app.config import get_settings

_production_compat.install_text_control_evidence()

ROOT = Path(__file__).resolve().parents[3]
PROFILE = {
    "full_name": "Avery Certification", "first_name": "Avery",
    "last_name": "Certification", "email": "avery.certification@example.test",
    "synthetic_certification_only": True, "answer_policies": [],
}
FILLER = "app.services.form_filler_v3._fill_step_fields"
ADAPTER = "app.services.ats_greenhouse.GreenhouseAdapter"

# Installed in every document before site scripts. Report attempts independently
# of the filler log and stop native/JavaScript form submissions before dispatch.
DOM_GUARD = r"""(() => {
  const state = {clicks: [], submits: 0, programmatic: 0};
  Object.defineProperty(window, '__gate2', {value: state});
  const report = event => { window.gate2Observe(event); };
  const final = el => el && (
    el.matches('input[type=submit],button[type=submit],#submit_app,[data-gate2-final]') ||
    (el.tagName === 'BUTTON' && el.form && !el.hasAttribute('type')) ||
    /submit|send application|finish application|complete application/i.test(
      [el.textContent, el.value, el.id, el.getAttribute('aria-label'),
       el.getAttribute('data-testid'), el.getAttribute('data-qa')].join(' ')));
  addEventListener('click', event => {
    const el = event.target.closest('button,input,a,[role=button]');
    if (!el) return;
    const item = {kind:'click', final:!!final(el), tag:el.tagName,
      id:el.id, text:(el.textContent || el.value || '').slice(0,120)};
    state.clicks.push(item); report(item);
    if (item.final) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);
  addEventListener('submit', event => {
    state.submits++; report({kind:'submit'});
    event.preventDefault(); event.stopImmediatePropagation();
  }, true);
  for (const method of ['submit', 'requestSubmit']) {
    Object.defineProperty(HTMLFormElement.prototype, method, {value:function() {
      state.programmatic++; report({kind:'programmatic_submit', method});
    }});
  }
})()"""


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def identity(url: str) -> dict:
    parsed = urlsplit(url)
    board, job = parse_greenhouse_job_url(url)
    if (parsed.scheme != "https" or parsed.hostname not in {
        "boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io",
    } or parsed.username or parsed.password or parsed.port not in {None, 443}
        or not board or not job or not re.fullmatch(r"[a-zA-Z0-9_-]+", board)
        or not re.fullmatch(r"\d+", job)):
        raise ValueError("An exact public HTTPS Greenhouse board/job URL is required")
    return {"board_token": board, "job_id": job}


def provenance() -> dict:
    """Bind executed inputs to the clean HEAD, not an environment SHA assertion."""
    git_executable = shutil.which("git")
    if not git_executable:
        raise RuntimeError("Git executable is required for source attestation")

    def git(*args):
        return subprocess.check_output([git_executable, "-C", str(ROOT), *args])
    if git("status", "--porcelain", "--untracked-files=all").strip():
        raise RuntimeError("Gate 2 requires a clean committed checkout")
    sha = git("rev-parse", "HEAD").decode().strip()
    manifest = {}
    tracked = {raw.decode() for raw in git("ls-files", "-z").split(b"\0") if raw}
    for directory in (ROOT / "backend/app", ROOT / "backend/scripts"):
        if any(str(path.relative_to(ROOT)) not in tracked for path in directory.rglob("*.py")):
            raise RuntimeError("Uncommitted Python input, including ignored inputs, is present")
    for raw in git("ls-files", "-z").split(b"\0"):
        if not raw:
            continue
        path = raw.decode()
        if path.startswith("backend/app/") or path.startswith("backend/scripts/") or path in {
            "backend/requirements.txt", "backend/requirements.android-server.txt",
        }:
            payload = (ROOT / path).read_bytes()
            if payload != git("show", f"HEAD:{path}"):
                raise RuntimeError(f"Executed input differs from HEAD: {path}")
            manifest[path] = digest(payload)
    return {"git_sha": sha, "inputs": manifest, "python": sys.version,
            "playwright": importlib.metadata.version("playwright"),
            "source_sha256": digest(json.dumps(manifest, sort_keys=True).encode())}


def claim_attempt(path: Path, target: dict) -> dict:
    """Durable unique target/identity reservation. Never touches application DB."""
    path.parent.mkdir(parents=True, exist_ok=True)
    key = digest(json.dumps({"target": target, "profile": PROFILE}, sort_keys=True).encode())
    with sqlite3.connect(path, timeout=5) as db:
        db.execute("CREATE TABLE IF NOT EXISTS attempts (key TEXT PRIMARY KEY, created REAL NOT NULL)")
        db.execute("INSERT INTO attempts VALUES (?, ?)", (key, time.time()))
    duplicate_rejected = False
    try:
        with sqlite3.connect(path, timeout=5) as db:
            db.execute("INSERT INTO attempts VALUES (?, ?)", (key, time.time()))
    except sqlite3.IntegrityError:
        duplicate_rejected = True
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT COUNT(*) FROM attempts WHERE key = ?", (key,)).fetchone()[0]
    return {"key": key, "reserved": True, "duplicate_rejected": duplicate_rejected,
            "ledger": str(path), "rows": rows}


def trace_evidence(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as archive:
            records = [json.loads(line) for name in archive.namelist() if name.endswith(".trace")
                       for line in archive.read(name).decode().splitlines() if line]
            network = [json.loads(line) for name in archive.namelist() if name.endswith(".network")
                       for line in archive.read(name).decode().splitlines() if line]
            valid = archive.testzip() is None and any(
                item.get("type") == "context-options" and item.get("browserName") == "chromium"
                for item in records)
            mutations = []
            for item in network:
                snapshot = item.get("snapshot", {})
                request = snapshot.get("request", {})
                if request and _mutating(request):
                    post = request.get("postData") or {}
                    body = (archive.read("resources/" + post["_sha1"])
                            if post.get("_sha1") else post.get("text", "").encode())
                    response = snapshot.get("response") or {}
                    mutations.append({**request, "body_sha256": digest(body),
                        "aborted": snapshot.get("_wasAborted") is True,
                        "response_status": response.get("status"),
                        "failure": response.get("_failureText")})
        return {"path": path.name, "sha256": digest(path.read_bytes()), "valid": valid,
                "mutating_requests": mutations}
    except (OSError, zipfile.BadZipFile, UnicodeError, ValueError, KeyError):
        return {"path": path.name, "valid": False}


def evaluate(record: dict, directory: Path) -> list[str]:
    """Fail closed on missing, conflicting or independently unverifiable evidence."""
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)
    source = record.get("source") or {}
    require(bool(re.fullmatch(r"[0-9a-f]{40}", source.get("git_sha", ""))), "exact SHA missing")
    inputs = source.get("inputs") or {}
    require(bool(inputs) and source.get("source_sha256") == digest(
        json.dumps(inputs, sort_keys=True).encode()), "source digest missing or inconsistent")
    require({"backend/app/services/ats_greenhouse.py", "backend/app/services/form_filler_v3.py",
             "backend/app/services/recovery_gate2.py"}.issubset(inputs)
            and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                    for value in inputs.values()), "required executed input hashes missing")
    require(record.get("dry_run") is True, "dry_run must be true")
    require(record.get("flow_invocation", {}).get("dry_run") is True,
            "production flow dry_run evidence missing")
    require(record.get("synthetic_profile") == PROFILE, "synthetic input identity changed")
    try:
        expected = identity(record.get("target_url", ""))
    except ValueError:
        expected = None
    require(expected is not None and record.get("detected_identity") == expected,
            "target identity missing or changed")
    require(record.get("adapter", {}).get("callable") == ADAPTER
            and record.get("adapter", {}).get("name") == "greenhouse", "production Greenhouse adapter missing")
    require(record.get("filler", {}).get("callable") == FILLER
            and record.get("filler", {}).get("calls", 0) > 0, "production filler missing")
    require(record.get("adapter", {}).get("source_sha256") == inputs.get("backend/app/services/ats_greenhouse.py")
            and record.get("filler", {}).get("source_sha256") == inputs.get("backend/app/services/form_filler_v3.py"),
            "executed adapter/filler source digest mismatch")
    require(record.get("browser", {}).get("owner") == "playwright"
            and record.get("browser", {}).get("type") == "chromium", "owned Chromium missing")
    dom = record.get("dom") or {}
    require(dom.get("guard_installed") is True and dom.get("observations") is not None
            and dom.get("snapshot") is not None, "DOM evidence missing")
    require(not any(e.get("final") or e.get("kind") in {"submit", "programmatic_submit"}
                    for e in dom.get("observations", [])), "final submit attempted")
    snapshot = dom.get("snapshot") or {}
    require(snapshot.get("submits") == 0
            and snapshot.get("programmatic") == 0
            and not any(e.get("final") for e in snapshot.get("clicks", [])),
            "DOM submit observation failed")
    network = record.get("network") or {}
    require(network.get("guard_installed") is True
            and all(isinstance(network.get(stage), list) for stage in
                    ("requests", "sent", "blocked", "failed", "finished", "websockets")),
            "network evidence missing")
    aborted = _proven_aborted_telemetry(network)
    require(not _unreconciled_mutations(network.get("blocked"), aborted)
            and not any(not _is_telemetry(e) for e in network.get("blocked") or [])
            and not network.get("websockets"), "unsafe network attempt")
    require(not _unreconciled_mutations(network.get("sent"), aborted),
            "application POST or other mutation sent")
    require(not _unreconciled_mutations(network.get("requests"), aborted)
            and not _unreconciled_mutations(network.get("failed"), aborted),
            "unreconciled mutation lifecycle")
    # Completion is always unsafe, regardless of domain or other aborted requests.
    require(not any(_mutating(e) for e in network.get("finished") or []),
            "completed application mutation")
    duplicate = record.get("duplicate") or {}
    require(duplicate.get("reserved") is True and duplicate.get("duplicate_rejected") is True
            and duplicate.get("rows") == 1 and bool(duplicate.get("key")), "duplicate protection failed")
    expected_key = digest(json.dumps({"target": expected, "profile": PROFILE}, sort_keys=True).encode())
    try:
        with sqlite3.connect(f"file:{directory / 'ledger.sqlite'}?mode=ro", uri=True) as ledger:
            count = ledger.execute("SELECT COUNT(*) FROM attempts WHERE key = ?", (expected_key,)).fetchone()[0]
        require(duplicate.get("key") == expected_key and count == 1, "retained duplicate ledger mismatch")
    except sqlite3.Error:
        errors.append("retained duplicate ledger missing or invalid")
    teardown = record.get("teardown") or {}
    require(teardown.get("browser_closed") is True and teardown.get("driver_stopped") is True
            and teardown.get("tracked_count", 0) > 0
            and teardown.get("remaining") == [], "browser/process teardown failed")
    trace = record.get("trace") or {}
    actual_trace = trace_evidence(directory / "trace.zip")
    require(trace.get("valid") is True and actual_trace.get("valid") is True
            and trace.get("sha256") == actual_trace.get("sha256"), "trace missing or invalid")
    require(not _unreconciled_mutations(actual_trace.get("mutating_requests"), aborted, trace=True),
            "trace contains application POST or other mutation")
    boundary = record.get("boundary") or {}
    require(boundary.get("checks", 0) >= 2 and boundary.get("bypassed") is False,
            "human/security boundary evidence missing or mishandled")
    require(not boundary.get("detected"), "human/security boundary reached")
    readbacks = record.get("field_readbacks") or []
    require(bool(readbacks) and all(item.get("matched") is True
            and item.get("expected_sha256") == item.get("observed_sha256") for item in readbacks)
            and record.get("verified_fields", 0) == len(readbacks), "field readback evidence missing")
    require(not record.get("error") and not record.get("cleanup_errors"), "execution failed")
    return errors



def _mutating(event: dict) -> bool:
    # Missing/unknown methods cannot establish a read-only request.
    return event.get("method") not in {"GET", "HEAD"}


def _is_telemetry(event: dict) -> bool:
    """Classification only, not an exemption. Exact endpoint from failed run 37173569727."""
    try:
        parsed = urlsplit(event.get("url", ""))
        return (event.get("method") == "POST" and parsed.scheme == "https"
                and parsed.hostname == "c.spl.greenhouse.io"
                and parsed.port in {None, 443} and not parsed.username and not parsed.password
                and parsed.path == "/com.snowplowanalytics.snowplow/tp2"
                and not parsed.query and not parsed.fragment)
    except (TypeError, ValueError):
        return False


def _request_key(event: dict) -> tuple | None:
    """Trace has no public request ID. Keep URL exact and bind method plus body hash."""
    body = event.get("body_sha256")
    if not isinstance(body, str) or not re.fullmatch(r"[0-9a-f]{64}", body):
        return None
    return event.get("method"), event.get("url"), body


def _blocked_failure(event: dict) -> bool:
    return event.get("failure") in {
        "net::ERR_BLOCKED_BY_CLIENT", "net::ERR_BLOCKED_BY_CLIENT.Inspector",
    }


def _unique_requests(events) -> dict:
    """Index only unambiguous object-bound request IDs."""
    counts = Counter(e.get("request_id") for e in events)
    return {e["request_id"]: e for e in events
            if isinstance(e.get("request_id"), str) and counts[e["request_id"]] == 1}


def _abort_matches(event, stages, completed_ids) -> bool:
    """Require every lifecycle witness, including an independent blocked failure."""
    request_id, key = event["request_id"], _request_key(event)
    return all((
        key is not None, _is_telemetry(event), event.get("abort_succeeded") is True,
        request_id not in completed_ids,
        all(_request_key(stages[stage].get(request_id, {})) == key
            for stage in ("requests", "sent", "failed")),
        _blocked_failure(stages["failed"].get(request_id, {})),
    ))


def _proven_aborted_telemetry(network: dict) -> list:
    """Require independent requestfailed evidence for each successful route abort."""
    # Object-bound IDs reconcile callbacks, never URL membership alone.
    # Ambiguous/duplicate IDs and incomplete older evidence fail closed.
    stages = {stage: _unique_requests(network.get(stage) or [])
              for stage in ("requests", "sent", "blocked", "failed")}
    completed_ids = {e.get("request_id") for e in network.get("finished") or []}
    return [event for event in stages["blocked"].values()
            if _abort_matches(event, stages, completed_ids)]


def _mutation_identity(event, trace):
    """Use object IDs for callbacks and an exact payload tuple for trace snapshots."""
    key = _request_key(event)
    return key if trace else (event.get("request_id"), key)


def _trace_aborted(event) -> bool:
    """Require the trace's own terminal abort with no response."""
    return all((event.get("aborted") is True, event.get("response_status") == -1,
                _blocked_failure(event)))


def _unreconciled_mutations(events, aborted, *, trace=False) -> list:
    """Reconcile each aborted request to at most one mutation per stream."""
    # Trace also requires its own abort/failure/no-response evidence.
    # Same-URL completions or extra attempts cannot borrow an exemption.
    available = Counter(_mutation_identity(e, trace) for e in aborted)
    unsafe = []
    for event in events or []:
        if not _mutating(event):
            continue
        key = _request_key(event)
        identity = _mutation_identity(event, trace)
        if (key is None or not _is_telemetry(event) or available[identity] <= 0
                or (trace and not _trace_aborted(event))):
            unsafe.append(event)
        else:
            available[identity] -= 1
    return unsafe


_INTERACTIVE_CAPTCHA = (
    'iframe[src*="recaptcha/"][src*="/bframe"], iframe[src*="hcaptcha.com"], '
    'iframe[src*="challenges.cloudflare.com" i], '
    'iframe[src*="recaptcha/"][src*="/anchor"]:not([src*="size=invisible"]), '
    '.h-captcha, div.g-recaptcha:not(.grecaptcha-badge), '
    ':is([class*="captcha" i],[id*="captcha" i],[data-sitekey])'
    ':not(.grecaptcha-badge):not(.grecaptcha-badge *)'
    ':not([name="g-recaptcha-response"]):not([name="h-captcha-response"])'
)
_PASSIVE_CAPTCHA = '.grecaptcha-badge, iframe[title="reCAPTCHA"][src*="size=invisible"]'


async def _passive_invisible_captcha(page) -> bool:
    """True only for a usable form plus a passive badge, with no interactive challenge."""
    controls = page.locator("form input:not([type='hidden']):not([type='submit'])"
                            ":not([type='button']):not([type='password']), form textarea, form select")
    usable = False
    for index in range(await controls.count()):
        control = controls.nth(index)
        if await control.is_visible() and await control.is_enabled():
            usable = True
            break
    if not usable:
        return False
    interactive = await page.locator(_INTERACTIVE_CAPTCHA).count()
    if interactive:
        return False
    badge = await page.locator(_PASSIVE_CAPTCHA).count()
    return badge > 0


async def _boundary(page, record):
    boundary = record["boundary"]
    boundary["checks"] += 1
    challenge = await detect_blocking_challenge(page)
    if await page.locator(_INTERACTIVE_CAPTCHA).count():
        challenge = {"reason_code": "captcha_detected", "summary": "Interactive CAPTCHA present"}
    # Production already filters invisible reCAPTCHA sources and badge elements.
    # Observing a passive widget never overrides a positive detector result:
    # its evidence may describe an independent challenge or be incomplete.
    if await _passive_invisible_captcha(page):
        boundary.setdefault("passive_widgets", []).append({
            "reason_code": "passive_invisible_recaptcha",
            "summary": "passive invisible widget observed; no interaction",
        })
    elif not challenge and await page.locator(_PASSIVE_CAPTCHA).count():
        challenge = {"reason_code": "captcha_detected", "summary": "Widget without usable application form"}
    # Production heuristics intentionally ignore some challenge phrases when a
    # form is also present. Certification takes the stricter boundary here.
    if not challenge:
        text = await page.locator("body").inner_text()
        match = re.search(
            r"verify you are human|confirm you are human|prove you are human|"
            r"checking your browser|unusual traffic|security verification|"
            r"identity verification|verify (?:your|the) identity|"
            r"(?:complete|solve)\s+(?:the\s+)?(?:captcha|recaptcha|hcaptcha)|"
            r"(?:captcha|recaptcha|hcaptcha)\s+(?:is\s+)?(?:required|failed|expired|invalid)|"
            r"enter (?:the|your|a) verification code|two.factor authentication|"
            r"multi.factor authentication|one.time (?:passcode|code)", text, re.I)
        if match:
            challenge = {"reason_code": "security_boundary", "summary": match.group(0)}
    # Login must also be detected when a site's text does not match a phrase.
    if not challenge and await page.locator('input[type="password"]').count():
        challenge = {"reason_code": "login_required", "summary": "Login required"}
    if challenge:
        boundary["detected"] = challenge
        boundary["stopped"] = True
        raise RuntimeError("Human/security boundary reached; no interaction permitted")


async def _exercise(context, url, record):
    await context.expose_binding("gate2Observe", lambda _source, event:
                                 record["dom"]["observations"].append(event))
    await context.add_init_script(DOM_GUARD)
    record["dom"]["guard_installed"] = True

    request_ids = {}

    def request_event(request):
        # Retain Request objects so callback IDs cannot be reused during this run.
        if request not in request_ids:
            request_ids[request] = f"request-{len(request_ids) + 1}"
        return {"request_id": request_ids[request], "url": request.url,
                "method": request.method, "body_sha256": digest(request.post_data_buffer or b"")}

    async def guard(route):
        request = route.request
        event = {**request_event(request),
                 "resource_type": request.resource_type}
        record["network"]["requests"].append(event)
        allowed = request.method in {"GET", "HEAD"} and urlsplit(request.url).scheme == "https"
        if request.is_navigation_request() and request.frame == request.frame.page.main_frame:
            try:
                allowed = allowed and identity(request.url) == identity(url)
            except ValueError:
                allowed = False
        if allowed:
            await route.fallback()
        else:
            await route.abort("blockedbyclient")
            record["network"]["blocked"].append({**event, "abort_succeeded": True})

    async def websocket(route):
        record["network"]["websockets"].append(route.url)
        await route.close(code=1008, reason="Recovery proof disallows WebSockets")

    # 'sent' is the historical label for request initiation, including routed
    # attempts. It is not proof bytes reached a server. Keep terminal signals separate.
    context.on("request", lambda request: record["network"]["sent"].append(request_event(request)))
    context.on("requestfailed", lambda request: record["network"]["failed"].append({
        **request_event(request), "failure": request.failure}))
    context.on("requestfinished", lambda request:
               record["network"]["finished"].append(request_event(request)))
    await context.route("**/*", guard)
    await context.route_web_socket("**/*", websocket)
    record["network"]["guard_installed"] = True
    page = await context.new_page()
    record["page"] = page
    response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    if not response or response.status != 200:
        raise RuntimeError(f"Public form navigation failed: {response.status if response else None}")
    await _boundary(page, record)
    record["detected_identity"] = identity(page.url)
    if record["detected_identity"] != identity(url):
        raise RuntimeError("Greenhouse target changed")
    adapter = await detect_ats_adapter(page, page.url)
    if type(adapter) is not GreenhouseAdapter:
        raise RuntimeError("Production Greenhouse adapter was not detected")
    record["adapter"] = {"name": adapter.name, "version": adapter.version,
                         "callable": f"{type(adapter).__module__}.{type(adapter).__name__}",
                         "source_sha256": digest(Path(inspect.getfile(type(adapter))).read_bytes())}
    record["filler"] = {"callable": FILLER, "calls": 0,
                        "source_sha256": digest(Path(inspect.getfile(inspect.unwrap(_fill_step_fields))).read_bytes())}
    log = []
    record["log"] = log

    async def fill(surface, step):
        await _boundary(page, record)
        if identity(page.url) != identity(url):
            raise RuntimeError("Greenhouse identity changed before fill")
        record["filler"]["calls"] += 1
        submit = await adapter.find_submit_button(surface)
        if submit:
            await submit.evaluate("el => el.setAttribute('data-gate2-final', 'true')")
        # No fabricated answer policies, demographic/legal/consent values or upload
        # writes. Unknown required fields return production review items untouched.
        return await _fill_step_fields(surface, profile=dict(PROFILE), cover_letter="",
                                       resume_path="", log=log, step_number=step)

    record["flow_invocation"] = {"callable": "app.services.ats_flow.run_ats_application_flow", "dry_run": True}
    flow = await run_ats_application_flow(page, adapter, fill_step=fill, dry_run=True, log=log)
    record["flow"] = flow.as_dict()
    await _boundary(page, record)
    record["detected_identity"] = identity(page.url)
    surface = await adapter.resolve_surface(page)
    record["field_readbacks"] = []
    for event in flow.control_evidence:
        key = str(event.get("canonical_key", "")).removeprefix("profile.")
        if event.get("source") != "profile" or key not in PROFILE or key == "answer_policies":
            continue
        control_id = event.get("control_id", "")
        if not re.fullmatch(r"jt-text-\d+", control_id):
            continue
        observed = await surface.locator(f'[data-jt-text-control-id="{control_id}"]').input_value()
        expected = str(PROFILE[key])
        record["field_readbacks"].append({"control_id": control_id, "canonical_key": event["canonical_key"],
            "expected_sha256": digest(expected.encode()), "observed_sha256": digest(observed.encode()),
            "matched": observed == expected})
    record["verified_fields"] = len(record["field_readbacks"])
    record["dom"]["snapshot"] = await page.evaluate("window.__gate2")
    await page.screenshot(path=str(Path(record["directory"]) / "form.png"), full_page=True)
    (Path(record["directory"]) / "form.html").write_text(await page.content())


async def run_gate(url: str, directory: Path, ledger: Path) -> dict:
    """One browser launch with unconditional trace, failure and shutdown retention."""
    from playwright.async_api import async_playwright
    from scripts.run_onehost_fixture_gate import _child_processes, _still_running

    directory.mkdir(parents=True, exist_ok=False)
    record = {"schema": "jobtomatik.recovery.gate2.v1", "target_url": url,
              "evidence_kind": "public_greenhouse",
              "directory": str(directory), "dry_run": True, "synthetic_profile": dict(PROFILE),
              "dom": {"observations": []},
              "network": {"requests": [], "sent": [], "finished": [], "failed": [],
                          "blocked": [], "websockets": []},
              "boundary": {"checks": 0, "detected": None, "bypassed": False},
              "cleanup_errors": [], "browser_started": False}
    manager = browser = context = None
    tracing = False
    baseline = _child_processes()
    tracked = {}
    try:
        target = identity(url)
        require_browser_entry_allowed(url)
        record["source"] = provenance()
        for flag in ("ALLOW_REAL_APPLICATION_SUBMIT", "AUTOPILOT_ENABLED",
                     "GREENHOUSE_SUPERVISED_PILOT_ENABLED", "LEVER_SUPERVISED_PILOT_ENABLED"):
            if os.getenv(flag, "false").lower() not in {"false", "0", ""}:
                raise RuntimeError(f"Unsafe runtime flag: {flag}")
        for flag in ("allow_real_application_submit", "greenhouse_supervised_pilot_enabled",
                     "lever_supervised_pilot_enabled"):
            if getattr(get_settings(), flag):
                raise RuntimeError(f"Unsafe resolved configuration: {flag}")
        record["duplicate"] = claim_attempt(ledger, target)
        if not record["duplicate"]["duplicate_rejected"]:
            raise RuntimeError("Duplicate reservation self-check failed")
        with sqlite3.connect(ledger) as database, sqlite3.connect(directory / "ledger.sqlite") as backup:
            database.backup(backup)
        manager = await async_playwright().start()
        browser = await manager.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        record["browser_started"] = True
        record["browser"] = {"owner": "playwright", "type": browser.browser_type.name, "version": browser.version}
        context = await browser.new_context(service_workers="block")
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        tracing = True
        await _exercise(context, url, record)
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        tracked.update({pid: started for pid, started in _child_processes().items() if pid not in baseline})
        page = record.pop("page", None)
        if page is not None and not page.is_closed():
            try:
                record["dom"]["snapshot"] = await page.evaluate("window.__gate2")
                (directory / "failure-or-final.html").write_text(await page.content())
            except Exception as exc:
                record["cleanup_errors"].append(f"DOM retention: {exc}")
        if tracing:
            try:
                await context.tracing.stop(path=str(directory / "trace.zip"))
            except Exception as exc:
                record["cleanup_errors"].append(f"Trace retention: {exc}")
        teardown = record["teardown"] = {}
        if browser is not None:
            try:
                await browser.close()
                teardown["browser_closed"] = not browser.is_connected()
            except Exception as exc:
                record["cleanup_errors"].append(f"Browser shutdown: {exc}")
        if manager is not None:
            try:
                await manager.stop()
                teardown["driver_stopped"] = True
            except Exception as exc:
                record["cleanup_errors"].append(f"Driver shutdown: {exc}")
        deadline = time.monotonic() + 3
        while _still_running(tracked) and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        teardown.update({"tracked_count": len(tracked), "remaining": _still_running(tracked),
                         "tracked": {str(pid): start for pid, start in tracked.items()}})
        record["trace"] = trace_evidence(directory / "trace.zip")
        record["violations"] = evaluate(record, directory)
        record["verdict"] = "PASS" if not record["violations"] else "NOT_PROVEN"
        (directory / "summary.json").write_text(json.dumps(record, indent=2))
    return record
