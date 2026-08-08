"""Exact runtime revision identity used by certification and deployment surfaces.

The runtime identity is deliberately non-consequential: it proves *what code is
running* but never enables submission, outreach, adapter promotion, or release
authorization.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from typing import Any


REVISION_RE = re.compile(r"^[0-9a-f]{7,64}$", re.IGNORECASE)
RUNTIME_IDENTITY_VERSION = "phase12-runtime-identity-v1"
KNOWN_RUNTIME_ROLES = {"api", "worker", "beat", "cli", "ci", "unknown"}


def _normalize_revision(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if REVISION_RE.fullmatch(normalized) else None


def _git_revision() -> str | None:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
    except Exception:
        return None
    return _normalize_revision(value)


def resolve_runtime_revision() -> tuple[str, str]:
    """Resolve the running commit without inventing an identity.

    Explicit deployment identity wins. GitHub Actions identity is next. A local git
    checkout is accepted only as a development/CLI fallback. Unknown remains unknown.
    """

    explicit = _normalize_revision(os.getenv("JOBTOMATIK_RUNTIME_REVISION"))
    if explicit:
        return explicit, "JOBTOMATIK_RUNTIME_REVISION"

    github_sha = _normalize_revision(os.getenv("GITHUB_SHA"))
    if github_sha:
        return github_sha, "GITHUB_SHA"

    git_sha = _git_revision()
    if git_sha:
        return git_sha, "git"

    return "unknown", "unknown"


def current_revision() -> str:
    return resolve_runtime_revision()[0]


def runtime_role() -> str:
    role = str(os.getenv("JOBTOMATIK_RUNTIME_ROLE") or "unknown").strip().lower()
    return role if role in KNOWN_RUNTIME_ROLES else "unknown"


def _identity_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def runtime_identity_manifest() -> dict[str, Any]:
    revision, source = resolve_runtime_revision()
    expected_raw = str(os.getenv("JOBTOMATIK_EXPECTED_REVISION") or "").strip()
    expected = _normalize_revision(expected_raw)
    expected_configured = bool(expected_raw)
    expected_valid = not expected_configured or expected is not None
    matches_expected = bool(expected and revision != "unknown" and revision == expected)
    known = revision != "unknown"

    # Explicit expected identity is the strongest production attestation. Local/CI
    # callers without an expected value remain observable but are not "deployment_attested".
    deployment_attested = bool(
        known and expected_configured and expected_valid and matches_expected
    )

    payload = {
        "version": RUNTIME_IDENTITY_VERSION,
        "revision": revision,
        "source": source,
        "role": runtime_role(),
        "known": known,
        "expected_revision": expected,
        "expected_configured": expected_configured,
        "expected_valid": expected_valid,
        "matches_expected": matches_expected,
        "deployment_attested": deployment_attested,
    }
    payload["identity_sha256"] = _identity_hash(payload)
    payload["submission_authorized"] = False
    payload["outreach_authorized"] = False
    return payload
