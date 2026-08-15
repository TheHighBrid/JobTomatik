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
import os
import sys
from pathlib import Path
from threading import RLock
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pydantic_settings import PydanticBaseSettingsSource  # noqa: E402

from app.config import Settings  # noqa: E402
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
_BASE_SETTINGS_LOCK = RLock()


class _BackendRuntimeSettings(Settings):
    """Settings sourced from the managed backend file, never caller environment."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[Settings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, dotenv_settings, file_secret_settings


def _backend_settings() -> Settings:
    """Load the exact settings file used by the managed Android services."""

    return _BackendRuntimeSettings(_env_file=BACKEND_ROOT / ".env")


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


def _configured_browser_cdp_endpoint() -> str:
    """Resolve the browser endpoint from the managed backend runtime config.

    The physical acceptance command can inherit unrelated shell variables, while
    the managed API and worker use ``backend/.env``. A conflicting inherited
    endpoint is rejected before it can satisfy the browser proof.
    """

    backend_endpoint = (_backend_settings().application_browser_cdp_endpoint or "").strip()
    process_endpoint = (os.environ.get("APPLICATION_BROWSER_CDP_ENDPOINT") or "").strip()
    if backend_endpoint:
        if process_endpoint and process_endpoint != backend_endpoint:
            raise RuntimeError(
                "Android application browser CDP endpoint differs from managed backend runtime config"
            )
        return backend_endpoint

    if os.environ.get("JOBTOMATIK_RUNTIME_MODE") == "android_managed":
        raise RuntimeError(
            "Android managed backend runtime CDP endpoint is not configured"
        )

    # Preserve the established non-managed test/override seam. A process-level
    # endpoint remains usable only when no managed backend endpoint exists.
    fallback_endpoint = (get_settings().application_browser_cdp_endpoint or "").strip()
    if process_endpoint and fallback_endpoint and process_endpoint != fallback_endpoint:
        raise RuntimeError(
            "Android application browser CDP endpoint differs from acceptance settings"
        )
    return fallback_endpoint or process_endpoint


def _playwright_browser_acceptance() -> dict[str, Any]:
    endpoint = _configured_browser_cdp_endpoint()
    if not endpoint:
        raise RuntimeError("Android application browser CDP endpoint is not configured")
    proof = asyncio.run(probe_external_playwright_cdp(endpoint))
    if proof.get("playwright_attach_ready") is not True:
        raise RuntimeError("Android/native Chromium did not pass Playwright CDP attachment")
    if proof.get("browser_owned_by_jobtomatik") is not False:
        raise RuntimeError("Android/native Chromium ownership contract changed unexpectedly")
    return proof


def run_acceptance() -> dict[str, Any]:
    """Run Runtime V2 acceptance against one authoritative backend config."""

    # The base implementation owns frontend/API/worker/Beat/process and safety
    # attestation. Bind its settings lookup to the managed backend file so
    # cwd-relative or inherited settings cannot mask the running runtime.
    with _BASE_SETTINGS_LOCK:
        original_worker = _base._worker_acceptance
        original_settings = _base.get_settings
        _base._worker_acceptance = _worker_acceptance
        _base.get_settings = _backend_settings
        try:
            payload = _base.run_acceptance()
        finally:
            _base._worker_acceptance = original_worker
            _base.get_settings = original_settings

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
        settings = _backend_settings()
        failure = {
            "version": 1,
            "status": "fail",
            "revision": current_revision(),
            "error": str(exc)[:1800],
            "safety": {
                "real_submission_disabled": settings.allow_real_application_submit is False,
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