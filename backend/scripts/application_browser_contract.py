#!/usr/bin/env python3
"""Read the managed browser configuration or verify identity without mutations."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings
from app.services.application_browser_contract import (
    application_browser_contract,
    read_native_identity,
)


class ManagedBrowserSettings(Settings):
    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        # Match the env-sanitized API/worker, not unrelated caller shell exports.
        return init_settings, dotenv_settings, file_secret_settings


def managed_browser_contract():
    settings = ManagedBrowserSettings(_env_file=BACKEND_ROOT / ".env")
    # Only the launcher may initialize a missing endpoint. The worker fails closed
    # if its endpoint is missing. Existing explicit endpoints are never migrated.
    if not settings.application_browser_cdp_endpoint.strip():
        settings = settings.model_copy(update={"application_browser_cdp_endpoint": "http://127.0.0.1:9223"})
    os.environ["JOBTOMATIK_RUNTIME_MODE"] = "android_managed"
    return application_browser_contract(settings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("config", "identity", "probe"))
    args = parser.parse_args()
    try:
        contract = managed_browser_contract()
        if args.action == "config":
            # Fixed, validated fields consumed with mapfile; never shell-evaluated.
            print(contract.provider)
            print(contract.endpoint)
            print(urlparse(contract.endpoint).port)
        elif args.action == "identity":
            identity = asyncio.run(read_native_identity(contract.endpoint))
            print(json.dumps({"provider": contract.provider, "endpoint": contract.endpoint, "android_package": identity["Android-Package"]}))
        else:
            from app.services.browser_runtime import probe_external_playwright_cdp

            # Probe uses the worker's settings and rejects a missing persisted
            # endpoint; prepare_stack persists defaults before actual worker start.
            proof = asyncio.run(probe_external_playwright_cdp(contract.endpoint))
            if proof.get("connection_identity_verified") is not True:
                raise RuntimeError("ANDROID_NATIVE_CHROME_CONNECTION_UNVERIFIED")
            print(json.dumps(proof))
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"APPLICATION_BROWSER_CONTRACT_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
