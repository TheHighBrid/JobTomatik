"""Load retained adapter autonomy-release records without granting authority itself."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


DEFAULT_LEVER_AUTONOMY_RELEASE_PATH = "evidence/lever-autonomy-release.json"


def load_lever_autonomy_release(
    path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return one retained Lever autonomy release or ``None`` on any unsafe shape.

    Cryptographic validity is intentionally not decided here. The canonical maturity
    model validates the embedded manifest under the separately configured trusted
    signing key. This loader only prevents malformed or unrelated files from entering
    the adapter manifest at all.
    """

    candidate = Path(
        path
        or os.getenv("LEVER_AUTONOMY_RELEASE_PATH")
        or DEFAULT_LEVER_AUTONOMY_RELEASE_PATH
    )
    if not candidate.is_file():
        return None
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, Mapping):
        return None

    # The generator output is a wrapper report. Only its explicitly generated release
    # section may enter the runtime manifest, and only when the wrapper says generation
    # actually succeeded. A blocker report therefore remains inert even if copied to
    # the configured path by mistake.
    if value.get("promotion_record_generated") is not True:
        return None
    if str(value.get("adapter") or "").strip().lower() != "lever":
        return None
    if str(value.get("adapter_version") or "").strip() != "1.1.0":
        return None
    release = value.get("autonomy_release")
    if not isinstance(release, Mapping):
        return None
    return dict(release)


__all__ = [
    "DEFAULT_LEVER_AUTONOMY_RELEASE_PATH",
    "load_lever_autonomy_release",
]
