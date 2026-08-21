#!/usr/bin/env python3
from __future__ import annotations

"""Physical Android acceptance with real Playwright-over-CDP proof.

The stable Runtime V2 acceptance implementation remains in
``android_runtime_acceptance_base``. This public entrypoint adds the browser
proof that was previously missing: a raw ``/json/version`` response is not
accepted as evidence that the application worker can attach Playwright.

The base acceptance intentionally remains a no-submit shadow contract. This
entrypoint may project one explicitly enabled supervised ATS pilot through that
structural proof while preserving the real runtime safety state in the receipt.
"""

import asyncio
from copy import copy
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
SHADOW_ACCEPTANCE_PROFILE = "shadow_no_submit"
SUPERVISED_PROFILE_PREFIX = "supervised_"
SUPPORTED_SUPERVISED_PLATFORMS = ("greenhouse", "lever")
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


def _enabled_supervised_platforms(settings: Settings) -> list[str]:
    return [
        platform
        for platform in SUPPORTED_SUPERVISED_PLATFORMS
        if bool(getattr(settings, f"{platform}_supervised_pilot_enabled", False))
    ]


def _configured_acceptance_profile(settings: Settings) -> str:
    """Choose the runtime acceptance profile from authoritative managed settings."""

    if settings.allow_real_followup_send:
        raise RuntimeError(
            "Android runtime acceptance requires recruiter/follow-up sending to remain disabled"
        )
    if not settings.allow_real_application_submit:
        return SHADOW_ACCEPTANCE_PROFILE

    enabled_platforms = _enabled_supervised_platforms(settings)
    if len(enabled_platforms) != 1:
        raise RuntimeError(
            "Supervised Android runtime requires exactly one ATS pilot switch when real submission is enabled"
        )
    return f"{SUPERVISED_PROFILE_PREFIX}{enabled_platforms[0]}"


def _base_settings_for_profile(
    settings: Settings,
    profile: str,
) -> tuple[Settings, dict[str, Any] | None]:
    """Return base-proof settings plus any truthful safety receipt override.

    The stable base implementation is deliberately a no-submit shadow proof. For
    an explicitly scoped supervised pilot we project only the global submit flag
    to false while the base proves runtime identity, artifact identity, worker
    ownership, Redis DB1 routing, Beat identity, and process identity. The public
    receipt is then restored to the real settings and remains non-authorizing:
    a one-time exact-payload approval is still required before any final click.
    """

    if profile == SHADOW_ACCEPTANCE_PROFILE:
        return settings, None

    if not profile.startswith(SUPERVISED_PROFILE_PREFIX):
        raise RuntimeError(f"Unsupported Android runtime acceptance profile: {profile}")

    platform = profile.removeprefix(SUPERVISED_PROFILE_PREFIX)
    if platform not in SUPPORTED_SUPERVISED_PLATFORMS:
        raise RuntimeError(f"Unsupported supervised Android ATS profile: {platform}")
    if settings.allow_real_application_submit is not True:
        raise RuntimeError("Supervised Android runtime requires real application submission enabled")
    if settings.allow_real_followup_send is not False:
        raise RuntimeError(
            "Supervised Android runtime requires recruiter/follow-up sending disabled"
        )

    enabled_platforms = _enabled_supervised_platforms(settings)
    if enabled_platforms != [platform]:
        raise RuntimeError(
            "Supervised Android runtime profile must match the only enabled ATS pilot switch"
        )

    projected = copy(settings)
    projected.allow_real_application_submit = False
    return projected, {
        "real_submission_disabled": False,
        "supervised_submission_window": True,
        "supervised_platform": platform,
        "one_time_approval_required": True,
        "final_submit_allowed": False,
        "outreach_authorized": False,
    }


def run_acceptance(profile: str = SHADOW_ACCEPTANCE_PROFILE) -> dict[str, Any]:
    """Run Runtime V2 acceptance against one authoritative backend config."""

    authoritative_settings = _backend_settings()
    base_settings, safety_override = _base_settings_for_profile(
        authoritative_settings,
        profile,
    )

    def configured_base_settings() -> Settings:
        return base_settings

    # The base implementation owns frontend/API/worker/Beat/process and shadow
    # safety attestation. Bind its settings lookup to the managed backend file, or
    # the tightly scoped projection above, so inherited settings cannot mask the
    # running runtime.
    with _BASE_SETTINGS_LOCK:
        original_worker = _base._worker_acceptance
        original_settings = _base.get_settings
        _base._worker_acceptance = _worker_acceptance
        _base.get_settings = configured_base_settings
        try:
            payload = _base.run_acceptance()
        finally:
            _base._worker_acceptance = original_worker
            _base.get_settings = original_settings

    if safety_override is not None:
        payload["safety"] = safety_override
    payload["acceptance_profile"] = profile

    browser = dict(payload.get("browser") or {})
    browser.update(_playwright_browser_acceptance())
    browser["cdp_ready"] = True
    payload["browser"] = browser
    return payload


def main() -> int:
    configured_profile = (
        os.environ.get("JOBTOMATIK_ANDROID_ACCEPTANCE_PROFILE") or ""
    ).strip()
    try:
        settings = _backend_settings()
        if not configured_profile:
            configured_profile = _configured_acceptance_profile(settings)
        payload = run_acceptance(configured_profile)
        receipt = write_receipt(runtime_acceptance_path(), payload)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        print(
            "ANDROID_RUNTIME_ACCEPTANCE=PASS "
            f"profile={configured_profile} revision={receipt['revision']} "
            f"fingerprint={receipt['runtime_fingerprint_sha256']}"
        )
        return 0
    except Exception as exc:
        settings = _backend_settings()
        enabled_platforms = _enabled_supervised_platforms(settings)
        failure = {
            "version": 1,
            "status": "fail",
            "revision": current_revision(),
            "acceptance_profile": configured_profile or "auto",
            "error": str(exc)[:1800],
            "safety": {
                "real_submission_disabled": settings.allow_real_application_submit is False,
                "supervised_submission_window": bool(
                    settings.allow_real_application_submit and len(enabled_platforms) == 1
                ),
                "supervised_platform": enabled_platforms[0] if len(enabled_platforms) == 1 else None,
                "one_time_approval_required": True,
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