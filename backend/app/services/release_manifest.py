"""Build and validate the fail-closed OneHost release manifest."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, Mapping


_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReleaseManifestError(ValueError):
    """Raised when exact release identity cannot be proven."""

    def __init__(self, code: str, message: str):
        """Initialize the error with a stable machine-readable code."""
        super().__init__(message)
        self.code = code


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ReleaseManifestError(f"{key}_missing", f"{key} is required")
    return value


def _sha40(payload: Mapping[str, Any], key: str) -> str:
    value = _required_text(payload, key).lower()
    if _SHA40_RE.fullmatch(value) is None:
        raise ReleaseManifestError(
            f"{key}_invalid",
            f"{key} must be a 40-character hexadecimal SHA",
        )
    return value


def _sha256(payload: Mapping[str, Any], key: str) -> str:
    value = _required_text(payload, key).lower()
    if _SHA256_RE.fullmatch(value) is None:
        raise ReleaseManifestError(
            f"{key}_invalid",
            f"{key} must be a 64-character hexadecimal SHA-256",
        )
    return value


def _android_version_code(payload: Mapping[str, Any]) -> int:
    raw_value = payload.get("android_version_code")
    if isinstance(raw_value, bool):
        raise ReleaseManifestError(
            "android_version_code_invalid",
            "Android versionCode must be a positive integer",
        )
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ReleaseManifestError(
            "android_version_code_invalid",
            "Android versionCode must be a positive integer",
        ) from exc
    if value <= 0:
        raise ReleaseManifestError(
            "android_version_code_invalid",
            "Android versionCode must be a positive integer",
        )
    return value


def _verification_runs(payload: Mapping[str, Any]) -> list[str]:
    raw_runs = payload.get("verification_runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ReleaseManifestError(
            "verification_runs_missing",
            "At least one verification run is required",
        )
    runs = [str(item).strip() for item in raw_runs]
    if any(not item for item in runs):
        raise ReleaseManifestError(
            "verification_runs_invalid",
            "Verification run identifiers must be non-empty",
        )
    return runs


def _build_timestamp(payload: Mapping[str, Any]) -> str:
    value = _required_text(payload, "build_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseManifestError(
            "build_timestamp_invalid",
            "Build timestamp must be ISO-8601",
        ) from exc
    if parsed.tzinfo is None:
        raise ReleaseManifestError(
            "build_timestamp_invalid",
            "Build timestamp must include a timezone",
        )
    return value


def build_release_manifest(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a manifest only when every required release identity is explicit."""
    source_sha = _sha40(payload, "source_sha")
    backend_revision = _sha40(payload, "backend_revision")
    manifest = {
        "source_sha": source_sha,
        "version": _required_text(payload, "version"),
        "android_version_code": _android_version_code(payload),
        "apk_sha256": _sha256(payload, "apk_sha256"),
        "signing_cert_sha256": _sha256(payload, "signing_cert_sha256"),
        "backend_revision": backend_revision,
        "frontend_revision": _sha40(payload, "frontend_revision"),
        "database_schema_revision": _required_text(
            payload,
            "database_schema_revision",
        ),
        "verification_runs": _verification_runs(payload),
        "build_timestamp": _build_timestamp(payload),
        "rollback_tested": payload.get("rollback_tested") is True,
        "upgrade_tested": payload.get("upgrade_tested") is True,
        "grants_submit": False,
    }
    if backend_revision != source_sha:
        raise ReleaseManifestError(
            "backend_revision_mismatch",
            "Backend revision must match source SHA",
        )
    return manifest


def render_release_manifest(manifest: Mapping[str, Any]) -> str:
    """Render a deterministic JSON release-manifest artifact."""
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def rollback_is_safe(
    *,
    from_schema: str,
    to_schema: str,
    destructive: bool,
) -> Dict[str, Any]:
    """Return the fail-closed rollback decision for the schema transition."""
    if not from_schema or not to_schema:
        return {"safe": False, "reason": "schema_revision_missing"}
    if from_schema == to_schema:
        return {"safe": True, "reason": "same_schema"}
    if destructive:
        return {
            "safe": False,
            "reason": "destructive_migration_blocks_rollback",
        }
    return {"safe": True, "reason": "reversible_migration"}
