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
import subprocess
import sys
import time
import zipfile
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
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT), *args])
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
            mutations = [item["snapshot"]["request"] for item in network
                         if item.get("snapshot", {}).get("request", {}).get("method") not in {None, "GET", "HEAD"}]
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
            and isinstance(network.get("requests"), list)
            and isinstance(network.get("sent"), list), "network evidence missing")
    require(not network.get("blocked") and not network.get("websockets"), "unsafe network attempt")
    require(all(e.get("method") in {"GET", "HEAD"} for e in network.get("sent", [])),
            "application POST or other mutation sent")
    duplicate = record.get("duplicate") or {}
    require(duplicate.get("reserved") is True and duplicate.get("duplicate_rejected") is True
            and duplicate.get("rows") == 1 and bool(duplicate.get("key")), "duplicate protection failed")
    teardown = record.get("teardown") or {}
    require(teardown.get("browser_closed") is True and teardown.get("driver_stopped") is True
            and teardown.get("tracked_count", 0) > 0
            and teardown.get("remaining") == [], "browser/process teardown failed")
    trace = record.get("trace") or {}
    actual_trace = trace_evidence(directory / "trace.zip")
    require(trace.get("valid") is True and actual_trace.get("valid") is True
            and trace.get("sha256") == actual_trace.get("sha256"), "trace missing or invalid")
    require(not actual_trace.get("mutating_requests"), "trace contains application POST or other mutation")
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


async def _boundary(page, record):
    boundary = record["boundary"]
    boundary["checks"] += 1
    challenge = await detect_blocking_challenge(page)
    # Production heuristics intentionally ignore some challenge phrases when a
    # form is also present. Certification takes the stricter boundary here.
    if not challenge:
        text = await page.locator("body").inner_text()
        match = re.search(
            r"verify you are human|confirm you are human|prove you are human|"
            r"checking your browser|unusual traffic|security verification|"
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

    async def guard(route):
        request = route.request
        event = {"url": request.url, "method": request.method,
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
            record["network"]["blocked"].append(event)
            await route.abort("blockedbyclient")

    async def websocket(route):
        record["network"]["websockets"].append(route.url)
        await route.close(code=1008, reason="Recovery proof disallows WebSockets")

    context.on("request", lambda request: record["network"]["sent"].append({
        "url": request.url, "method": request.method}))
    # 'request' includes blocked attempts. A requestfinished event is separate
    # evidence of completion; all mutation attempts invalidate the proof either way.
    context.on("requestfinished", lambda request: record["network"]["finished"].append({
        "url": request.url, "method": request.method}))
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
              "network": {"requests": [], "sent": [], "finished": [], "blocked": [], "websockets": []},
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
