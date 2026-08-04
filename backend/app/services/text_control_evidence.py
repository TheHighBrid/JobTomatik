"""Privacy-safe evidence for verified text-control fills."""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from functools import wraps
from typing import Any, Dict, Mapping

from app.services.control_engine import CONTROL_ENGINE_VERSION


_INSTALLED = False


def _text_evidence(
    entry: Mapping[str, Any],
    *,
    step_number: int,
) -> Dict[str, Any] | None:
    if (
        entry.get("action") not in {"fill", "text_control_verified"}
        or entry.get("verified") is not True
        or str(entry.get("source") or "") not in {"profile", "answer_policy"}
    ):
        return None

    descriptor = str(entry.get("descriptor") or "").strip()
    canonical_key = str(entry.get("canonical_key") or "").strip()
    control_id = str(entry.get("control_id") or "").strip()
    control_type = str(entry.get("control_type") or "text").strip()
    source = str(entry.get("source") or "")
    if not descriptor or not canonical_key or not control_id:
        return None

    identity = json.dumps(
        {
            "canonical_key": canonical_key,
            "control_id": control_id,
            "control_type": control_type,
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
        "control_id": control_id,
        "control_type": control_type,
        "descriptor": descriptor,
        "canonical_key": canonical_key,
        "policy_id": entry.get("policy_id"),
        "selected": [],
        "options_fingerprint": fingerprint[:16],
        "verification": "passed",
        "verification_method": str(
            entry.get("verification_method") or "browser_input_value_readback"
        ),
        "pass": step_number,
        "source": source,
        "prepopulated": bool(entry.get("prepopulated")),
        "value_redacted": True,
    }


def _append_unique(target: list[Dict[str, Any]], item: Dict[str, Any]) -> None:
    signature = (
        item.get("control_id"),
        item.get("canonical_key"),
        item.get("source"),
        item.get("pass"),
    )
    if any(
        signature
        == (
            existing.get("control_id"),
            existing.get("canonical_key"),
            existing.get("source"),
            existing.get("pass"),
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
