"""Synthetic owned-browser runtime used only by the Phase 0 API/Celery proof.

The dedicated proof worker installs this runtime only when
``JOBTOMATIK_ONEHOST_PHASE0_PROOF=1``. Production browser selection is not
changed. The proof reuses the current v3 field filler and ATS flow while
Playwright owns Chromium directly, writes a trace, and verifies process cleanup.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlsplit

from app.services.ats_base import ATSAdapter
from app.services.ats_flow import run_ats_application_flow
from app.services.form_filler_v3 import _fill_step_fields


_LAUNCH_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]


def _enabled() -> bool:
    return str(os.getenv("JOBTOMATIK_ONEHOST_PHASE0_PROOF") or "").strip() == "1"


def _fixture_url() -> str:
    return str(os.getenv("JOBTOMATIK_ONEHOST_FIXTURE_URL") or "").strip()


def _evidence_root() -> Path:
    raw = str(os.getenv("JOBTOMATIK_ONEHOST_PHASE0_EVIDENCE_DIR") or "").strip()
    if not raw:
        raise RuntimeError("JOBTOMATIK_ONEHOST_PHASE0_EVIDENCE_DIR is required")
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_token(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.")
    return cleaned[:96] or "phase0"


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


def _capture_new_children(baseline: dict[int, str], tracked: dict[int, str]) -> None:
    """Track descendants by PID plus start identity before they can be reparented."""

    for pid, started in _child_processes().items():
        if baseline.get(pid) != started:
            tracked[pid] = started


def _still_running(tracked: dict[int, str]) -> list[int]:
    return [
        pid
        for pid, started in tracked.items()
        if (identity := _process_identity(pid))
        and identity[1] == started
        and identity[2] != "Z"
    ]


def _exact_get_allowed(url: str, method: str, expected_url: str) -> bool:
    target = urlsplit(url)
    expected = urlsplit(expected_url)
    return (
        method == "GET"
        and target == expected
        and target.scheme == "http"
        and target.hostname is not None
        and target.username is None
        and target.password is None
    )


def _observe_request(record: dict[str, Any], request) -> None:
    record["observed_requests"].append({"url": request.url, "method": request.method})


def _unexpected_observed_requests(record: dict[str, Any], expected_url: str) -> list[dict[str, Any]]:
    return [
        item
        for item in record.get("observed_requests", [])
        if not _exact_get_allowed(item.get("url", ""), item.get("method", ""), expected_url)
    ]


async def _guard_fixture_route(route, expected_url: str, record: dict[str, Any]) -> None:
    """Permit exactly one 200 GET response from the configured fixture, with no redirects."""

    request = route.request
    request_shape = {"url": request.url, "method": request.method}
    if not _exact_get_allowed(request.url, request.method, expected_url):
        record["blocked_requests"].append({**request_shape, "reason": "outside_fixture_boundary"})
        await route.abort("blockedbyclient")
        return

    try:
        upstream = await route.fetch(max_redirects=0)
    except Exception as exc:
        record["blocked_requests"].append({
            **request_shape,
            "reason": "fixture_fetch_failed",
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        })
        await route.abort("blockedbyclient")
        return

    location = upstream.headers.get("location")
    if 300 <= upstream.status < 400:
        record["blocked_requests"].append({
            **request_shape,
            "reason": "fixture_redirect_refused",
            "status": upstream.status,
            "location": location,
        })
        await route.abort("blockedbyclient")
        return
    if upstream.status != 200:
        record["blocked_requests"].append({
            **request_shape,
            "reason": "fixture_status_refused",
            "status": upstream.status,
        })
        await route.abort("blockedbyclient")
        return

    await route.fulfill(response=upstream)


async def _install_fixture_network_guard(context, expected_url: str, record: dict[str, Any]) -> None:
    """Install independent request observation plus fail-closed HTTP/WebSocket routing."""

    context.on("request", lambda request: _observe_request(record, request))

    async def guard(route):
        await _guard_fixture_route(route, expected_url, record)

    async def block_websocket(route):
        record["blocked_requests"].append({
            "url": route.url,
            "method": "WEBSOCKET",
            "reason": "websocket_refused",
        })
        await route.close(code=1008, reason="Phase 0 permits only the configured fixture")

    await context.route("**/*", guard)
    await context.route_web_socket("**/*", block_websocket)


def _verify_trace(trace_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(trace_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Playwright trace archive failed integrity verification")
        if not any(name.endswith(".trace") for name in archive.namelist()):
            raise RuntimeError("Playwright trace archive does not contain trace data")
    payload = trace_path.read_bytes()
    return {
        "trace_path": str(trace_path),
        "trace_sha256": hashlib.sha256(payload).hexdigest(),
        "trace_bytes": len(payload),
    }


async def _exercise_browser(
    *,
    expected_url: str,
    user_profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    expected_values: dict[str, str],
    trace_path: Path,
    baseline: dict[int, str],
    tracked: dict[int, str],
    record: dict[str, Any],
    result: dict[str, Any],
) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = None
        context = None
        tracing_started = False
        _capture_new_children(baseline, tracked)
        try:
            browser = await playwright.chromium.launch(headless=True, args=_LAUNCH_ARGS)
            _capture_new_children(baseline, tracked)
            record["browser"] = {
                "type": browser.browser_type.name,
                "version": browser.version,
            }
            context = await browser.new_context(service_workers="block")
            _capture_new_children(baseline, tracked)
            await _install_fixture_network_guard(context, expected_url, record)
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)
            tracing_started = True

            page = await context.new_page()
            _capture_new_children(baseline, tracked)
            response = await page.goto(expected_url, wait_until="domcontentloaded", timeout=15000)
            record["navigation_status"] = response.status if response else None
            log: list[dict[str, Any]] = []

            async def fill_step(surface, step_number):
                return await _fill_step_fields(
                    surface,
                    profile=dict(user_profile),
                    cover_letter=cover_letter,
                    resume_path=resume_path,
                    log=log,
                    step_number=step_number,
                )

            flow = await run_ats_application_flow(
                page,
                ATSAdapter(),
                fill_step=fill_step,
                dry_run=True,
                log=log,
            )
            values = {
                field: await page.locator(f"#{field}").input_value()
                for field in expected_values
            }
            submit_observations = await page.evaluate("window.fixtureObservations")
            unexpected_requests = _unexpected_observed_requests(record, expected_url)
            record["unexpected_observed_requests"] = unexpected_requests
            record["values"] = values
            record["submit_observations"] = submit_observations
            record["flow"] = flow.as_dict()
            record["log"] = log

            result.update(flow.as_dict())
            result["ats_adapter"] = flow.adapter_name
            result["ats_adapter_version"] = flow.adapter_version
            result["log"] = log

            record["checks"] = {
                "navigation_ok": record["navigation_status"] == 200,
                "values_verified": values == expected_values,
                "submit_not_clicked": submit_observations
                == {"submitClicks": 0, "submitEvents": 0},
                "no_blocked_requests": not record["blocked_requests"],
                "no_unexpected_observed_requests": not unexpected_requests,
                "flow_ready": bool(flow.success and flow.ready_to_submit),
            }
            if not all(record["checks"].values()):
                result["success"] = False
                result["ready_to_submit"] = False
                result["requires_manual_review"] = True
                result["error"] = "Phase 0 owned-browser fixture checks failed"
        finally:
            _capture_new_children(baseline, tracked)
            if tracing_started and context is not None:
                try:
                    await context.tracing.stop(path=str(trace_path))
                except Exception as exc:
                    record["errors"].append(f"trace stop failed: {str(exc)[:300]}")
            if browser is not None:
                try:
                    await browser.close()
                    record["browser_closed"] = not browser.is_connected()
                except Exception as exc:
                    record["browser_closed"] = False
                    record["errors"].append(f"browser close failed: {str(exc)[:300]}")


async def fill_and_submit_application(
    job_url: str,
    user_profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    dry_run: bool = True,
    **_kwargs,
) -> Dict[str, Any]:
    """Exercise the fixture through the real task and current filler primitives."""

    if not _enabled():
        raise RuntimeError("Phase 0 fixture runtime cannot run outside its proof environment")
    if not dry_run:
        raise RuntimeError("Phase 0 fixture runtime is dry-run only")

    expected_url = _fixture_url()
    if not expected_url or job_url != expected_url:
        raise RuntimeError("Phase 0 fixture runtime refuses any URL except the configured fixture")

    email = str(user_profile.get("email") or "phase0@example.test")
    run_token = _safe_token(email.split("@", 1)[0])
    run_dir = _evidence_root() / run_token
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / "trace.zip"
    evidence_path = run_dir / "browser-evidence.json"

    expected_name = str(user_profile.get("full_name") or "").strip().split()
    expected_values = {
        "first": expected_name[0] if expected_name else "",
        "last": " ".join(expected_name[1:]) if len(expected_name) > 1 else "",
        "email": email,
    }
    record: Dict[str, Any] = {
        "synthetic": True,
        "fixture_url": expected_url,
        "blocked_requests": [],
        "observed_requests": [],
        "expected_values": expected_values,
        "errors": [],
    }
    result: Dict[str, Any] = {
        "success": False,
        "dry_run": True,
        "url": job_url,
        "submitted_at": None,
        "error": None,
        "fields_filled": 0,
        "requires_manual_review": False,
        "review_items": [],
        "confirmation_evidence": [],
        "ready_to_submit": False,
        "ats_adapter": "generic",
        "ats_adapter_version": "1.0.0",
        "log": [],
        "phase0_owned_browser_proof": True,
    }

    baseline = _child_processes()
    tracked: dict[int, str] = {}
    try:
        await _exercise_browser(
            expected_url=expected_url,
            user_profile=user_profile,
            cover_letter=cover_letter,
            resume_path=resume_path,
            expected_values=expected_values,
            trace_path=trace_path,
            baseline=baseline,
            tracked=tracked,
            record=record,
            result=result,
        )
    except Exception as exc:
        record["errors"].append(f"{type(exc).__name__}: {str(exc)[:500]}")
        result["success"] = False
        result["ready_to_submit"] = False
        result["requires_manual_review"] = True
        result["error"] = str(exc)[:500]

    deadline = time.monotonic() + 3
    while _still_running(tracked) and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    record["tracked_child_process_count"] = len(tracked)
    record["remaining_child_processes"] = _still_running(tracked)

    try:
        record.update(_verify_trace(trace_path))
    except Exception as exc:
        record["errors"].append(f"trace verification failed: {str(exc)[:300]}")

    shutdown_ok = (
        record.get("browser_closed") is True
        and record["tracked_child_process_count"] > 0
        and not record["remaining_child_processes"]
    )
    record.setdefault("checks", {})["browser_and_driver_shutdown"] = shutdown_ok
    record.setdefault("checks", {})["trace_retained"] = bool(record.get("trace_sha256"))

    if record["errors"] or not all(record.get("checks", {}).values()):
        result["success"] = False
        result["ready_to_submit"] = False
        result["requires_manual_review"] = True
        result["error"] = result.get("error") or "Phase 0 evidence verification failed"

    evidence_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    result.setdefault("log", []).append({
        "action": "phase0_owned_browser_evidence",
        "evidence_path": str(evidence_path),
        "trace_path": str(trace_path),
        "checks": record.get("checks", {}),
    })
    return result
