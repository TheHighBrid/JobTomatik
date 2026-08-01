"""Pure helpers for one interactive Lever Phase A handoff exercise."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Mapping

from app.services.ats_lever import LEVER_ADAPTER_VERSION, parse_lever_job_url
from app.services.browser_handoff import current_browser_node_id
from app.services.handoff_session import encrypt_handoff_secret


SUBMIT_LOG_ACTIONS = frozenset(
    {"ats_submit_clicked", "submit_click", "submit_clicked"}
)
CHALLENGE_TYPE_BY_REASON = {
    "captcha_detected": "captcha",
    "mfa_required": "mfa",
    "login_required": "login",
    "anti_bot_challenge": "anti_bot",
}
_REQUIRED_TARGET_COLUMNS = {
    "review_id",
    "employer",
    "role",
    "site",
    "posting_id",
    "region",
    "canonical_application_url",
    "active",
    "viable",
}


class LeverPhaseAOperatorError(ValueError):
    pass


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_locked_target(review_id: str, corpus_root: Path) -> Dict[str, str]:
    requested = str(review_id or "").strip()
    if not requested:
        raise LeverPhaseAOperatorError("A locked review ID is required")
    matches: list[Dict[str, str]] = []
    for path in sorted(Path(corpus_root).glob("part-*.csv")):
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = _REQUIRED_TARGET_COLUMNS.difference(reader.fieldnames or [])
            if missing:
                raise LeverPhaseAOperatorError(
                    f"{path} is missing locked-corpus columns: {', '.join(sorted(missing))}"
                )
            for row in reader:
                if str(row.get("review_id") or "").strip() == requested:
                    record = {key: str(value or "").strip() for key, value in row.items()}
                    record["corpus_path"] = str(path)
                    matches.append(record)
    if len(matches) != 1:
        raise LeverPhaseAOperatorError(
            f"Expected exactly one locked target for {requested}; found {len(matches)}"
        )
    target = matches[0]
    if not _truthy(target.get("active")) or not _truthy(target.get("viable")):
        raise LeverPhaseAOperatorError(
            f"Locked target {requested} is not marked active and viable"
        )
    url = target["canonical_application_url"]
    observed = parse_lever_job_url(url)
    expected = (
        target["site"],
        target["posting_id"],
        target["region"].lower(),
    )
    if observed != expected:
        raise LeverPhaseAOperatorError(
            f"Locked target {requested} does not match its canonical Lever URL"
        )
    target["region"] = target["region"].lower()
    return target


def challenge_reason(result: Mapping[str, Any]) -> str:
    for item in result.get("review_items") or []:
        reason = str(item.get("reason_code") or "").strip()
        if reason in CHALLENGE_TYPE_BY_REASON:
            return reason
    return ""


def submit_clicked(result: Mapping[str, Any]) -> bool:
    return any(
        str(item.get("action") or "") in SUBMIT_LOG_ACTIONS
        for item in result.get("log") or []
        if isinstance(item, Mapping)
    )


def transient_handoff_session(
    snapshot: Mapping[str, Any],
    *,
    reason_code: str,
    target_metadata: Mapping[str, Any],
) -> SimpleNamespace:
    endpoint = str(snapshot.get("browser_endpoint") or "").strip()
    provider = str(snapshot.get("browser_provider") or "").strip()
    current_url = str(snapshot.get("current_url") or "").strip()
    if provider != "local_cdp" or not endpoint or not current_url:
        raise LeverPhaseAOperatorError(
            "The retained browser snapshot is missing a local CDP endpoint"
        )
    challenge_type = CHALLENGE_TYPE_BY_REASON.get(reason_code)
    if not challenge_type:
        raise LeverPhaseAOperatorError(
            f"Review reason {reason_code!r} is not an interactive handoff boundary"
        )
    metadata = dict(snapshot.get("metadata") or {})
    metadata.update(
        {
            "dry_run": True,
            "adapter": "lever",
            "adapter_version": LEVER_ADAPTER_VERSION,
            "supervised_target": dict(target_metadata),
            "phase_a_interactive": True,
        }
    )
    return SimpleNamespace(
        browser_provider=provider,
        browser_session_id=snapshot.get("browser_session_id"),
        encrypted_browser_endpoint=encrypt_handoff_secret(endpoint),
        browser_node_id=snapshot.get("browser_node_id") or current_browser_node_id(),
        browser_process_id=snapshot.get("browser_process_id"),
        browser_profile_path=snapshot.get("browser_profile_path"),
        current_url=current_url,
        current_fingerprint=snapshot.get("current_fingerprint"),
        challenge_type=challenge_type,
        handoff_metadata=metadata,
    )


def _merge_dicts(*values: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    merged: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for collection in values:
        for raw in collection or []:
            if not isinstance(raw, Mapping):
                continue
            item = dict(raw)
            signature = json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
            if signature in seen:
                continue
            seen.add(signature)
            merged.append(item)
    return merged


def build_resumed_exercise(
    *,
    url: str,
    initial_result: Mapping[str, Any],
    resumed_result: Mapping[str, Any],
    certification_metadata: Mapping[str, Any],
    handoff_verification: Mapping[str, Any] | None = None,
    submit_guard: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    clicked = submit_clicked(initial_result) or submit_clicked(resumed_result)
    guard = dict(submit_guard or {})
    guard_attempted_submit = bool(
        int(guard.get("blocked_clicks") or 0)
        or int(guard.get("blocked_submits") or 0)
    )
    adapter = str(
        resumed_result.get("ats_adapter")
        or initial_result.get("ats_adapter")
        or ""
    )
    adapter_version = str(
        resumed_result.get("ats_adapter_version")
        or initial_result.get("ats_adapter_version")
        or ""
    )
    ready = bool(
        resumed_result.get("success")
        and resumed_result.get("ready_to_submit")
        and adapter == "lever"
        and adapter_version == LEVER_ADAPTER_VERSION
        and not clicked
        and not guard_attempted_submit
    )
    review_items = _merge_dicts(
        initial_result.get("review_items") or [],
        resumed_result.get("review_items") or [],
    )
    validation_errors = _merge_dicts(
        initial_result.get("validation_errors") or [],
        resumed_result.get("validation_errors") or [],
    )
    upload_evidence = _merge_dicts(
        initial_result.get("upload_evidence") or [],
        resumed_result.get("upload_evidence") or [],
    )
    step_evidence = _merge_dicts(
        initial_result.get("step_evidence") or [],
        resumed_result.get("step_evidence") or [],
    )
    control_evidence = _merge_dicts(
        initial_result.get("control_evidence") or [],
        resumed_result.get("control_evidence") or [],
    )
    return {
        "url": url,
        "mode": "exercise",
        "passed": ready,
        "certification_outcome": "ready_to_submit" if ready else "failed",
        "manual_challenge_ready": False,
        "adapter": adapter,
        "adapter_version": adapter_version,
        "ready_to_submit": bool(resumed_result.get("ready_to_submit")),
        "requires_manual_review": bool(resumed_result.get("requires_manual_review")),
        "steps_completed": max(
            int(initial_result.get("steps_completed") or 0),
            int(resumed_result.get("steps_completed") or 0),
        ),
        "fields_filled": max(
            int(initial_result.get("fields_filled") or 0),
            int(resumed_result.get("fields_filled") or 0),
        ),
        "review_items": review_items,
        "validation_errors": validation_errors,
        "upload_evidence": upload_evidence,
        "step_evidence": step_evidence,
        "control_evidence_count": len(control_evidence),
        "final_submit_clicked": clicked,
        "certification_metadata": dict(certification_metadata),
        "handoff_verification": dict(handoff_verification or {}),
        "submit_guard": guard,
        "error": (
            "The submit guard intercepted an operator submit attempt."
            if guard_attempted_submit
            else resumed_result.get("error")
        ),
    }


def build_phase_a_report(
    inspection: Mapping[str, Any],
    exercise: Mapping[str, Any],
) -> Dict[str, Any]:
    reports = [dict(inspection), dict(exercise)]
    final_submit_clicked = any(
        item.get("final_submit_clicked") is True for item in reports
    )
    passed = bool(
        inspection.get("passed") is True
        and exercise.get("passed") is True
        and not final_submit_clicked
    )
    return {
        "certification": "lever_supervised_live_dry_run",
        "interactive_handoff": True,
        "final_submit_clicked": final_submit_clicked,
        "url_count": 1,
        "exercise_enabled": True,
        "reports": reports,
        "passed": passed,
    }


def write_report(path: Path, report: Mapping[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(target)
    return hashlib.sha256(target.read_bytes()).hexdigest()


__all__ = [
    "LeverPhaseAOperatorError",
    "build_phase_a_report",
    "build_resumed_exercise",
    "challenge_reason",
    "load_locked_target",
    "submit_clicked",
    "transient_handoff_session",
    "write_report",
]
