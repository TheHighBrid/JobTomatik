"""Privacy-safe evidence for verified text-control fills.

The standards control engine already retains evidence for selects, radio groups,
checkboxes, and comboboxes. Safe profile and approved-policy text fields are filled
by the form runner, so this installer records the same kind of durable verification
without retaining the applicant value itself.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from functools import wraps
from typing import Any, Dict, Mapping

from app.services.control_engine import CONTROL_ENGINE_VERSION


_INSTALLED = False


def _canonical_key(entry: Mapping[str, Any]) -> str:
    explicit = str(entry.get("canonical_key") or "").strip()
    if explicit:
        return explicit
    field = str(entry.get("field") or "").strip()
    return f"profile.{field}" if field else ""


def _text_evidence(
    entry: Mapping[str, Any],
    *,
    step_number: int,
) -> Dict[str, Any] | None:
    if (
        entry.get("action") != "fill"
        or entry.get("verified") is not True
        or str(entry.get("source") or "") not in {"profile", "answer_policy"}
    ):
        return None

    descriptor = str(entry.get("descriptor") or "").strip()
    canonical_key = _canonical_key(entry)
    if not descriptor or not canonical_key:
        return None

    source = str(entry.get("source") or "")
    identity = json.dumps(
        {
            "canonical_key": canonical_key,
            "control_type": "text",
            "descriptor": descriptor,
            "source": source,
            "step": step_number,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    fingerprint = hashlib.sha256(identity).hexdigest()
    return {
        "action": "control_verified",
        "control_engine_version": CONTROL_ENGINE_VERSION,
        "control_id": f"text-{fingerprint[:16]}",
        "control_type": "text",
        "descriptor": descriptor,
        "canonical_key": canonical_key,
        "policy_id": None,
        "selected": [],
        "options_fingerprint": fingerprint[:16],
        "verification": "passed",
        "pass": step_number,
        "source": source,
        "value_redacted": True,
    }


def _append_unique(target: list[Dict[str, Any]], item: Dict[str, Any]) -> None:
    signature = (
        item.get("control_id"),
        item.get("canonical_key"),
        item.get("source"),
    )
    if any(
        signature
        == (
            existing.get("control_id"),
            existing.get("canonical_key"),
            existing.get("source"),
        )
        for existing in target
    ):
        return
    target.append(item)


def _sync_loaded_handoff(step_filler) -> None:
    handoff = sys.modules.get("app.services.form_filler_handoff")
    if handoff is not None:
        handoff._fill_step_fields = step_filler


def install_text_control_evidence() -> None:
    """Install an idempotent wrapper around the canonical ATS step filler."""

    global _INSTALLED
    from app.services import form_filler_v3

    if _INSTALLED:
        _sync_loaded_handoff(form_filler_v3._fill_step_fields)
        return

    original = form_filler_v3._fill_step_fields
    signature = inspect.signature(original)

    @wraps(original)
    async def wrapped(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        log = bound.arguments.get("log")
        start = len(log) if isinstance(log, list) else 0
        outcome = await original(*args, **kwargs)
        if not isinstance(log, list):
            return outcome

        try:
            step_number = int(bound.arguments.get("step_number") or 0)
        except (TypeError, ValueError):
            step_number = 0
        evidence = outcome.setdefault("control_evidence", [])
        for entry in log[start:]:
            if not isinstance(entry, Mapping):
                continue
            item = _text_evidence(entry, step_number=step_number)
            if item is not None:
                _append_unique(evidence, item)
        return outcome

    form_filler_v3._fill_step_fields = wrapped
    _sync_loaded_handoff(wrapped)
    _INSTALLED = True


__all__ = ["install_text_control_evidence"]
