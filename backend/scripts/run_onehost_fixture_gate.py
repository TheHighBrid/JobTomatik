"""Repeat the owned-browser proof on an HTTP fixture, retaining synthetic evidence.

This exercises the current v3 filler and ATS flow, not API/Celery dispatch or
retained handoffs. It cannot certify an employer application or adapter maturity.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = BACKEND_ROOT / "tests/fixtures/onehost_http_form.html"
PROFILE = {"full_name": "Fixture Candidate", "email": "fixture@example.test"}
EXPECTED_VALUES = {"first": "Fixture", "last": "Candidate", "email": PROFILE["email"]}
LAUNCH_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]


class FixtureServer:
    """Serve only the fixture on loopback; observe and reject other HTTP requests."""

    def __init__(self, html: bytes):
        self.requests: list[dict] = []
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append({"method": "GET", "path": self.path})
                if self.path != "/fixture":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)

            def do_POST(self):
                requests.append({"method": "POST", "path": self.path})
                self.send_error(405)

            def log_message(self, *_args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/fixture"
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="onehost-fixture-server",
            daemon=True,
        )

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def request_allowed(url: str, method: str, fixture_url: str) -> bool:
    """Allow exactly the fixture GET, including its scheme, host, port and path."""
    target, fixture = urlsplit(url), urlsplit(fixture_url)
    return (
        method == "GET"
        and target == fixture
        and target.scheme == "http"
        and target.hostname == "127.0.0.1"
        and target.username is None
        and target.password is None
    )


def _process_identity(pid: int):
    try:
        fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[1]), fields[19], fields[0]
    except (OSError, IndexError, ValueError):
        return None


def _child_processes() -> dict[int, str]:
    identities = {
        int(path.name): identity
        for path in Path("/proc").iterdir()
        if path.name.isdigit() and (identity := _process_identity(int(path.name)))
    }
    descendants = {os.getpid()}
    while True:
        children = {pid for pid, identity in identities.items() if identity[0] in descendants}
        if children.issubset(descendants):
            break
        descendants.update(children)
    return {pid: identities[pid][1] for pid in descendants if pid != os.getpid()}


def _still_running(tracked: dict[int, str]) -> list[int]:
    return [
        pid for pid, started in tracked.items()
        if (identity := _process_identity(pid))
        and identity[1] == started and identity[2] != "Z"
    ]


def _source_digest() -> str:
    digest = hashlib.sha256()
    paths = sorted((BACKEND_ROOT / "app").rglob("*.py")) + [Path(__file__), FIXTURE_PATH]
    for path in paths:
        digest.update(str(path.relative_to(BACKEND_ROOT)).encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


async def run_once(output_dir: Path, index: int) -> dict:
    # Import the production functions, without monkeypatching URL, policy or
    # browser-provider guards to pretend this is an employer application.
    sys.path.insert(0, str(BACKEND_ROOT))
    from playwright.async_api import async_playwright
    from app.services.ats_base import ATSAdapter
    from app.services.ats_flow import run_ats_application_flow
    from app.services.form_filler_v3 import _fill_step_fields

    run_dir = output_dir / f"run-{index:03d}"
    run_dir.mkdir(parents=True, exist_ok=False)
    trace = run_dir / "trace.zip"
    record = {
        "run": index,
        "synthetic": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
        "errors": [],
        "blocked_requests": [],
    }
    browser = context = None
    tracing = False
    tracked = {}
    baseline = _child_processes()
    fixture = FixtureServer(FIXTURE_PATH.read_bytes())
    try:
        with fixture:
            record["fixture_url"] = fixture.url
            async with async_playwright() as playwright:
                try:
                    browser = await playwright.chromium.launch(headless=True, args=LAUNCH_ARGS)
                    record["browser"] = {"type": browser.browser_type.name, "version": browser.version}
                    context = await browser.new_context(service_workers="block")
                    await context.tracing.start(screenshots=True, snapshots=True, sources=True)
                    tracing = True

                    async def guard(route):
                        request = route.request
                        if request_allowed(request.url, request.method, fixture.url):
                            await route.continue_()
                        else:
                            record["blocked_requests"].append({"url": request.url, "method": request.method})
                            await route.abort("blockedbyclient")

                    await context.route("**/*", guard)
                    page = await context.new_page()
                    response = await page.goto(fixture.url, wait_until="domcontentloaded", timeout=15000)
                    record["navigation_status"] = response.status if response else None
                    log = []

                    async def fill_step(surface, step_number):
                        return await _fill_step_fields(
                            surface, profile=dict(PROFILE), cover_letter="", resume_path="",
                            log=log, step_number=step_number,
                        )

                    flow = await run_ats_application_flow(
                        page, ATSAdapter(), fill_step=fill_step, dry_run=True, log=log,
                    )
                    record["flow"] = flow.as_dict()
                    record["log"] = log
                    record["values"] = {
                        field: await page.locator(f"#{field}").input_value()
                        for field in EXPECTED_VALUES
                    }
                    record["submit_observations"] = await page.evaluate("window.fixtureObservations")
                finally:
                    tracked = {pid: started for pid, started in _child_processes().items() if pid not in baseline}
                    try:
                        if tracing:
                            await context.tracing.stop(path=str(trace))
                    finally:
                        if browser is not None:
                            await browser.close()
                            record["browser_closed"] = not browser.is_connected()
    except Exception as exc:
        record["errors"].append(f"{type(exc).__name__}: {str(exc)[:500]}")

    # The Playwright driver has also exited by this point. Check tracked Linux
    # child identities rather than treating a disconnected client as shutdown.
    deadline = time.monotonic() + 3
    while _still_running(tracked) and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    record["tracked_child_process_count"] = len(tracked)
    record["remaining_child_processes"] = _still_running(tracked)
    record["fixture_server_stopped"] = not fixture.thread.is_alive()
    record["http_requests"] = list(fixture.requests)
    try:
        with zipfile.ZipFile(trace) as archive:
            if archive.testzip() is not None or not any(name.endswith(".trace") for name in archive.namelist()):
                raise ValueError("Trace archive is incomplete")
        record["trace_sha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
        record["trace_bytes"] = trace.stat().st_size
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        record["errors"].append(f"Trace verification failed: {exc}")

    checks = {
        "local_http_navigation": record.get("navigation_status") == 200
        and {"method": "GET", "path": "/fixture"} in fixture.requests,
        "values_verified": record.get("values") == EXPECTED_VALUES,
        "current_flow_ready": record.get("flow", {}).get("success") is True
        and record.get("flow", {}).get("ready_to_submit") is True,
        "submit_not_clicked": record.get("submit_observations") == {"submitClicks": 0, "submitEvents": 0}
        and not any("submit_clicked" in str(item.get("action")) for item in record.get("log", [])),
        "no_nonfixture_requests": not record["blocked_requests"]
        and all(item == {"method": "GET", "path": "/fixture"} for item in fixture.requests),
        "browser_shutdown": record.get("browser_closed") is True
        and len(tracked) > 0 and not record["remaining_child_processes"],
        "server_shutdown": record["fixture_server_stopped"],
        "trace_retained": bool(record.get("trace_sha256")),
    }
    record["checks"] = checks
    record["status"] = "passed" if all(checks.values()) and not record["errors"] else "failed"
    (run_dir / "evidence.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


async def run_gate(output_dir: Path, repeats: int = 3, revision: str = "unattested-local") -> dict:
    if repeats < 3:
        raise ValueError("The recovery proof requires at least three independent launches")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "gate": "onehost-fixture",
        "synthetic": True,
        "scope": "owned_browser_v3_fill_and_ats_flow",
        "api_celery_dispatch_proven": False,
        "employer_certification": False,
        "repository_revision": revision,
        "source_sha256": _source_digest(),
        "requested_runs": repeats,
        "runs": [],
        "status": "failed",
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for index in range(1, repeats + 1):
        record = await run_once(output_dir, index)
        summary["runs"].append({"run": index, "status": record["status"], "evidence": f"run-{index:03d}/evidence.json"})
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if record["status"] != "passed":
            break
    if len(summary["runs"]) == repeats and all(run["status"] == "passed" for run in summary["runs"]):
        summary["status"] = "passed"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--revision", default=os.getenv("JOBTOMATIK_RUNTIME_REVISION", "unattested-local"))
    args = parser.parse_args()
    summary = asyncio.run(run_gate(args.output_dir, args.repeats, args.revision))
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
