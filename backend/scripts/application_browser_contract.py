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

from app.config import Settings
from app.services.application_browser_contract import (
    application_browser_contract,
    read_native_identity,
)
from app.services.browser_runtime import probe_external_playwright_cdp

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NATIVE_ENDPOINT = "http://127.0.0.1:9223"
LEGACY_MANAGED_NATIVE_ENDPOINT = "http://127.0.0.1:9222"
DEPLOYMENT_MIGRATION_ENV = "JOBTOMATIK_MIGRATE_LEGACY_BROWSER_ENDPOINT"


class ManagedBrowserSettings(Settings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Pydantic requires the full override signature even though this launcher
        # intentionally ignores caller-shell environment settings.
        del settings_cls, env_settings
        return init_settings, dotenv_settings, file_secret_settings


def managed_browser_contract():
    settings = ManagedBrowserSettings(_env_file=BACKEND_ROOT / ".env")
    endpoint = settings.application_browser_cdp_endpoint.strip()
    migrate_legacy = os.environ.get(DEPLOYMENT_MIGRATION_ENV, "0") == "1"
    # Only the launcher may initialize a missing endpoint. During the one bounded
    # deployment restart, the previously managed 9222 default is also migrated to
    # the native-Chrome 9223 transport. Other explicit endpoints remain untouched.
    if not endpoint or (
        migrate_legacy and endpoint == LEGACY_MANAGED_NATIVE_ENDPOINT
    ):
        settings = settings.model_copy(
            update={"application_browser_cdp_endpoint": DEFAULT_NATIVE_ENDPOINT}
        )
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
            print(
                json.dumps(
                    {
                        "provider": contract.provider,
                        "endpoint": contract.endpoint,
                        "android_package": identity["Android-Package"],
                    }
                )
            )
        else:
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
