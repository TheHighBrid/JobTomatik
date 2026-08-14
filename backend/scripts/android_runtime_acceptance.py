#!/usr/bin/env python3
from __future__ import annotations

"""Physical Android acceptance with real Playwright-over-CDP proof.

The stable Runtime V2 acceptance implementation remains in
``android_runtime_acceptance_base``. This public entrypoint adds the browser
proof that was previously missing: a raw ``/json/version`` response is not
accepted as evidence that the application worker can attach Playwright.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.browser_runtime import probe_external_playwright_cdp  # noqa: E402
from scripts import android_runtime_acceptance_base as _base  # noqa: E402

for _name in dir(_base):
    if _name.startswith("__") or _name in globals():
        continue
    globals()[_name] = getattr(_base, _name)

# Keep these contracts explicit in the authoritative source because tests and
# operational review intentionally inspect this file.
REQUIRED_WORKER_QUEUES = "applications,celery,followup,scraping"
validate_worker_canary_receipt = _base.validate_worker_canary_receipt
_BASE_WORKER_ACCEPTANCE = _base._worker_acceptance


def _worker_identity_tokens(revision: str) -> tuple[str, ...]:
    return (
        "celery",
        "app.celery_app",
        "worker",
        f"jobtomatik-android-{revision[:12]}@",
        "-Q",
        REQUIRED_WORKER_QUEUES,
    )


def _worker_acceptance(
    revision: str,
    worker_pid: int,
    *,
    directory: Path | None = None,
) -> dict[str, Any]:
    """Delegate to the certified startup-receipt proof without new queue work."""

    # Preserve the existing monkeypatch/test seam while retaining the original
    # deterministic implementation.
    _base.validate_worker_canary_receipt = validate_worker_canary_receipt
    return _BASE_WORKER_ACCEPTANCE(
        revision,
        worker_pid,
        directory=directory,
    )


def _playwright_browser_acceptance() -> dict[str, Any]:
    settings = get_settings()
    endpoint = (settings.application_browser_cdp_endpoint or "").strip()
    if not endpoint:
        raise RuntimeError("Android application browser CDP endpoint is not configured")
    proof = asyncio.run(probe_external_playwright_cdp(endpoint))
    if proof.get("playwright_attach_ready") is not True:
        raise RuntimeError("Android/native Chromium did not pass Playwright CDP attachment")
    if proof.get("browser_owned_by_jobtomatik") is not False:
        raise RuntimeError("Android/native Chromium ownership contract changed unexpectedly")
    return proof


def run_acceptance() -> dict[str, Any]:
    """Run Runtime V2 acceptance and require the actual worker browser path."""

    # The base implementation still owns frontend/API/worker/Beat/process and
    # no-submit attestation. Its worker helper is patched only to preserve this
    # module's deterministic test seam.
    original_worker = _base._worker_acceptance
    _base._worker_acceptance = _worker_acceptance
    try:
        payload = _base.run_acceptance()
    finally:
        _base._worker_acceptance = original_worker

    browser = dict(payload.get("browser") or {})
    browser.update(_playwright_browser_acceptance())
    browser["cdp_ready"] = True
    payload["browser"] = browser
    return payload


def main() -> int:
    try:
        payload = run_acceptance()
        receipt = write_receipt(runtime_acceptance_path(), payload)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        print(
            "ANDROID_RUNTIME_ACCEPTANCE=PASS "
            f"revision={receipt['revision']} fingerprint={receipt['runtime_fingerprint_sha256']}"
        )
        return 0
    except Exception as exc:
        failure = {
            "version": 1,
            "status": "fail",
            "revision": current_revision(),
            "error": str(exc)[:1800],
            "safety": {
                "real_submission_disabled": get_settings().allow_real_application_submit is False,
                "final_submit_allowed": False,
                "outreach_authorized": False,
            },
        }
        write_receipt(runtime_acceptance_path(), failure)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        print(f"ANDROID_RUNTIME_ACCEPTANCE=FAIL reason={failure['error']}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
