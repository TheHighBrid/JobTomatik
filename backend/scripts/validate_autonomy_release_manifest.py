#!/usr/bin/env python3
"""Validate a candidate JobTomatik certified-autonomous release manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.services.autonomy_release_contract import (
    autonomy_release_contract_requirements,
    compute_autonomy_manifest_digest,
    compute_autonomy_manifest_signature,
    validate_autonomy_release_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", help="Path to candidate autonomous release JSON")
    parser.add_argument("--adapter-name", default="")
    parser.add_argument("--adapter-version", default="")
    parser.add_argument(
        "--print-requirements",
        action="store_true",
        help="Print the machine-readable contract without validating a candidate",
    )
    parser.add_argument(
        "--print-digest",
        action="store_true",
        help="Print the canonical manifest digest for a candidate JSON",
    )
    parser.add_argument(
        "--print-signature",
        action="store_true",
        help=(
            "Print the HMAC-SHA256 attestation using "
            "AUTONOMY_CERTIFICATION_SIGNING_KEY"
        ),
    )
    args = parser.parse_args()

    if args.print_requirements:
        print(json.dumps(autonomy_release_contract_requirements(), indent=2, sort_keys=True))
        return 0

    if not args.manifest:
        parser.error("--manifest is required unless --print-requirements is used")

    path = Path(args.manifest)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SystemExit("Autonomy release manifest must contain a JSON object.")

    if args.print_digest:
        print(compute_autonomy_manifest_digest(manifest))
        return 0

    signing_key = os.getenv("AUTONOMY_CERTIFICATION_SIGNING_KEY", "")
    if args.print_signature:
        if not signing_key:
            raise SystemExit("AUTONOMY_CERTIFICATION_SIGNING_KEY is required to sign.")
        print(compute_autonomy_manifest_signature(manifest, signing_key))
        return 0

    adapter = manifest.get("adapter") if isinstance(manifest.get("adapter"), dict) else {}
    adapter_name = args.adapter_name or str(adapter.get("name") or "")
    adapter_version = args.adapter_version or str(adapter.get("version") or "")
    result = validate_autonomy_release_manifest(
        manifest,
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        trusted_signing_key=signing_key or None,
        trusted_release_commit=os.getenv("AUTONOMY_RELEASE_COMMIT") or None,
        trusted_source_artifacts={
            "fixture_digest": os.getenv("AUTONOMY_FIXTURE_ARTIFACT", ""),
            "evidence_digest": os.getenv("AUTONOMY_EVIDENCE_ARTIFACT", ""),
            "policy_digest": os.getenv("AUTONOMY_POLICY_ARTIFACT", ""),
        },
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
