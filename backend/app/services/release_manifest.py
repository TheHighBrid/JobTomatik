"""Fail-closed OneHost release manifest.

The manifest binds the exact source SHA to the artifacts that would be
released. Missing identity is a blocker, not a blank field that can be
published.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED = (
    "source_sha",
    "version",
    "android_version_code",
    "apk_sha256",
    "signing_cert_sha256",
    "backend_revision",
    "frontend_revision",
    "database_schema_revision",
    "verification_runs",
    "build_timestamp",
)


class ReleaseManifestError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _sha40(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA40.match(text):
        raise ReleaseManifestError(f"{label}_invalid", f"{label} must be a 40-character SHA")
    return text


def _sha256(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256.match(text):
        raise ReleaseManifestError(f"{label}_invalid", f"{label} must be a SHA-256")
    return text


def build_release_manifest(payload: Mapping[str, Any]) -> Dict[str, Any]:
    source_sha = _sha40(payload.get("source_sha"), "source_sha")
    backend = _sha40(payload.get("backend_revision") or source_sha, "backend_revision")
    frontend = _sha40(payload.get("frontend_revision") or source_sha, "frontend_revision")
    version = str(payload.get("version") or "").strip()
    if not version:
        raise ReleaseManifestError("version_missing", "Release version is required")
    try:
        version_code = int(payload.get("android_version_code"))
    except (TypeError, ValueError) as exc:
        raise ReleaseManifestError("android_version_code_invalid", "Android versionCode is required") from exc
    if version_code <= 0:
        raise ReleaseManifestError("android_version_code_invalid", "Android versionCode must be positive")
    schema = str(payload.get("database_schema_revision") or "").strip()
    if not schema:
        raise ReleaseManifestError("database_schema_revision_missing", "Database schema revision is required")
    runs = payload.get("verification_runs")
    if not isinstance(runs, list) or not runs:
        raise ReleaseManifestError("verification_runs_missing", "At least one verification run is required")
    manifest = {
        "source_sha": source_sha,
        "version": version,
        "android_version_code": version_code,
        "apk_sha256": _sha256(payload.get("apk_sha256"), "apk_sha256"),
        "signing_cert_sha256": _sha256(payload.get("signing_cert_sha256"), "signing_cert_sha256"),
        "backend_revision": backend,
        "frontend_revision": frontend,
        "database_schema_revision": schema,
        "verification_runs": list(runs),
        "build_timestamp": str(payload.get("build_timestamp") or datetime.now(timezone.utc).isoformat()),
        "rollback_tested": payload.get("rollback_tested") is True,
        "upgrade_tested": payload.get("upgrade_tested") is True,
        "grants_submit": False,
    }
    missing = [key for key in REQUIRED if manifest.get(key) in (None, "")]
    if missing:
        raise ReleaseManifestError("manifest_incomplete", "Missing " + ", ".join(missing))
    if manifest["backend_revision"] != manifest["source_sha"]:
        raise ReleaseManifestError("backend_revision_mismatch", "Backend revision must match source SHA")
    return manifest


def render_release_manifest(manifest: Mapping[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def rollback_is_safe(*, from_schema: str, to_schema: str, destructive: bool) -> Dict[str, Any]:
    if not from_schema or not to_schema:
        return {"safe": False, "reason": "schema_revision_missing"}
    if from_schema == to_schema:
        return {"safe": True, "reason": "same_schema"}
    if destructive:
        return {"safe": False, "reason": "destructive_migration_blocks_rollback"}
    return {"safe": True, "reason": "reversible_migration"}
