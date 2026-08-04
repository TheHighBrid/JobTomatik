#!/usr/bin/env python3
"""Materialize the reviewed Lever Day 13 evidence-integrity repair."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} block in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


form_filler = ROOT / "backend/app/services/form_filler_v3.py"
replace_once(
    form_filler,
    '''    except Exception:
        return {}


async def _fill_text_fields(
''',
    '''    except Exception:
        return {}


async def _text_control_metadata(element: Any) -> Dict[str, str]:
    """Return a stable per-page identity without retaining the entered value."""
    try:
        value = await element.evaluate(
            """(el) => {
              let counter = Number(
                document.documentElement.dataset.jtTextControlCounter || 0
              );
              if (!el.dataset.jtTextControlId) {
                counter += 1;
                el.dataset.jtTextControlId = `jt-text-${counter}`;
                document.documentElement.dataset.jtTextControlCounter = String(counter);
              }
              return {
                control_id: el.dataset.jtTextControlId,
                control_type: (
                  (el.tagName || '').toLowerCase() === 'textarea'
                    ? 'textarea'
                    : (el.getAttribute('type') || 'text').toLowerCase()
                ),
                id: el.id || '',
                name: el.getAttribute('name') || ''
              };
            }"""
        )
    except Exception:
        return {}
    return {
        "control_id": str(value.get("control_id") or ""),
        "control_type": str(value.get("control_type") or "text"),
        "id": str(value.get("id") or ""),
        "name": str(value.get("name") or ""),
    }


async def _verified_text_log(
    element: Any,
    *,
    action: str,
    descriptor: str,
    canonical_key: str,
    source: str,
    policy_id: Any = None,
    prepopulated: bool,
) -> Dict[str, Any]:
    metadata = await _text_control_metadata(element)
    return {
        "action": action,
        "descriptor": descriptor[:200],
        "canonical_key": canonical_key,
        "source": source,
        "policy_id": policy_id,
        "control_id": metadata.get("control_id", ""),
        "control_type": metadata.get("control_type", "text"),
        "control_name": metadata.get("name", ""),
        "control_dom_id": metadata.get("id", ""),
        "verification_method": "browser_input_value_readback",
        "prepopulated": prepopulated,
        "verified": True,
        "ts": now_iso(),
    }


async def _fill_text_fields(
''',
    "text-control helpers",
)
replace_once(
    form_filler,
    '''                    if current == answer:
                        continue
                    await element.fill(answer)
                    if str(await element.input_value()) == answer:
                        filled += 1
                        log.append({
                            "action": "fill",
                            "descriptor": descriptor[:200],
                            "canonical_key": policy.get("canonical_key"),
                            "source": "answer_policy",
                            "verified": True,
                            "ts": now_iso(),
                        })
''',
    '''                    policy_id = (policy.get("policy") or {}).get("id")
                    if current == answer:
                        log.append(await _verified_text_log(
                            element,
                            action="text_control_verified",
                            descriptor=descriptor,
                            canonical_key=str(policy.get("canonical_key") or ""),
                            source="answer_policy",
                            policy_id=policy_id,
                            prepopulated=True,
                        ))
                        continue
                    await element.fill(answer)
                    if str(await element.input_value()) == answer:
                        filled += 1
                        log.append(await _verified_text_log(
                            element,
                            action="fill",
                            descriptor=descriptor,
                            canonical_key=str(policy.get("canonical_key") or ""),
                            source="answer_policy",
                            policy_id=policy_id,
                            prepopulated=False,
                        ))
''',
    "policy text verification",
)
replace_once(
    form_filler,
    '''                    if current == value:
                        continue
                    await element.fill(value)
                    if str(await element.input_value()) == value:
                        filled += 1
                        log.append({
                            "action": "fill",
                            "field": field,
                            "descriptor": descriptor[:200],
                            "source": "profile",
                            "verified": True,
                            "ts": now_iso(),
                        })
''',
    '''                    if current == value:
                        log.append(await _verified_text_log(
                            element,
                            action="text_control_verified",
                            descriptor=descriptor,
                            canonical_key=f"profile.{field}",
                            source="profile",
                            prepopulated=True,
                        ))
                        continue
                    await element.fill(value)
                    if str(await element.input_value()) == value:
                        filled += 1
                        log.append(await _verified_text_log(
                            element,
                            action="fill",
                            descriptor=descriptor,
                            canonical_key=f"profile.{field}",
                            source="profile",
                            prepopulated=False,
                        ))
''',
    "profile text verification",
)

text_evidence = ROOT / "backend/app/services/text_control_evidence.py"
text_evidence.write_text(
    '''"""Privacy-safe evidence for verified text-control fills."""

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
''',
    encoding="utf-8",
)

certify = ROOT / "backend/scripts/certify_lever_live.py"
replace_once(
    certify,
    '''    certification_outcome = (
        "ready_to_submit"
        if ready_to_submit
        else "manual_challenge_handoff"
        if manual_challenge_ready
        else "failed"
    )
    return {
''',
    '''    certification_outcome = (
        "ready_to_submit"
        if ready_to_submit
        else "manual_challenge_handoff"
        if manual_challenge_ready
        else "failed"
    )
    control_evidence = [
        dict(item)
        for item in result.get("control_evidence") or []
        if isinstance(item, dict)
    ]
    policy_evidence_count = sum(
        1 for item in control_evidence if item.get("source") != "profile"
    )
    return {
''',
    "exercise evidence preparation",
)
replace_once(
    certify,
    '''        "step_evidence": result.get("step_evidence") or [],
        "control_evidence_count": len(result.get("control_evidence") or []),
        "final_submit_clicked": submit_clicked,
''',
    '''        "step_evidence": result.get("step_evidence") or [],
        "control_evidence_schema_version": "1.0",
        "control_evidence": control_evidence,
        "control_evidence_count": len(control_evidence),
        "policy_evidence_count": policy_evidence_count,
        "final_submit_clicked": submit_clicked,
''',
    "exercise evidence serialization",
)

exporter = ROOT / "backend/scripts/export_lever_phase_a_record.py"
replace_once(
    exporter,
    '''def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _default_artifact_path(report_path: Path, output_path: Path) -> str:
''',
    '''def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy_evidence_count(exercise: Mapping[str, Any]) -> int:
    evidence = exercise.get("control_evidence")
    if isinstance(evidence, list):
        return sum(
            1
            for item in evidence
            if isinstance(item, Mapping) and item.get("source") != "profile"
        )
    if exercise.get("policy_evidence_count") is not None:
        return int(exercise.get("policy_evidence_count") or 0)
    return int(exercise.get("control_evidence_count") or 0)


def _default_artifact_path(report_path: Path, output_path: Path) -> str:
''',
    "policy evidence counter",
)
replace_once(
    exporter,
    '''        "policies_used": int(exercise.get("control_evidence_count") or 0),
''',
    '''        "policies_used": _policy_evidence_count(exercise),
''',
    "candidate policy count",
)

finalizer = ROOT / "backend/scripts/finalize_lever_phase_a_ready.py"
replace_once(
    finalizer,
    '''def validate_ready_report(
    report: Mapping[str, Any],
    target: Mapping[str, Any],
) -> Dict[str, Any]:
''',
    '''def _validated_control_evidence(exercise: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if exercise.get("control_evidence_schema_version") != "1.0":
        raise LeverPhaseAProvenanceError(
            "The exercise lacks the serialized control-evidence schema"
        )
    evidence = exercise.get("control_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise LeverPhaseAProvenanceError(
            "The exercise lacks serialized per-control evidence"
        )
    if int(exercise.get("control_evidence_count") or 0) != len(evidence):
        raise LeverPhaseAProvenanceError(
            "The control-evidence count does not match the serialized entries"
        )

    seen: set[tuple[str, str, str, int]] = set()
    policy_count = 0
    forbidden_text_keys = {
        "answer", "input_value", "raw_value", "text_value", "value"
    }
    for item in evidence:
        if not isinstance(item, Mapping):
            raise LeverPhaseAProvenanceError(
                "A serialized control-evidence entry is not an object"
            )
        if item.get("action") != "control_verified":
            raise LeverPhaseAProvenanceError(
                "A serialized control-evidence entry has an invalid action"
            )
        if item.get("verification") != "passed":
            raise LeverPhaseAProvenanceError(
                "A serialized control-evidence entry was not verified"
            )
        required = {
            "control_id": str(item.get("control_id") or "").strip(),
            "control_type": str(item.get("control_type") or "").strip(),
            "descriptor": str(item.get("descriptor") or "").strip(),
            "canonical_key": str(item.get("canonical_key") or "").strip(),
        }
        if not all(required.values()):
            raise LeverPhaseAProvenanceError(
                "A serialized control-evidence entry lacks required identity fields"
            )
        try:
            pass_number = int(item.get("pass") or 0)
        except (TypeError, ValueError) as exc:
            raise LeverPhaseAProvenanceError(
                "A serialized control-evidence entry has an invalid pass"
            ) from exc
        if pass_number <= 0:
            raise LeverPhaseAProvenanceError(
                "A serialized control-evidence entry has an invalid pass"
            )

        source = str(item.get("source") or "")
        if source in {"profile", "answer_policy"}:
            if item.get("value_redacted") is not True:
                raise LeverPhaseAProvenanceError(
                    "Text control evidence must explicitly redact its value"
                )
            if item.get("selected") != []:
                raise LeverPhaseAProvenanceError(
                    "Text control evidence must not serialize a selected value"
                )
            if forbidden_text_keys & set(item):
                raise LeverPhaseAProvenanceError(
                    "Text control evidence contains a forbidden raw-value field"
                )
            if source == "answer_policy" and item.get("policy_id") in (None, ""):
                raise LeverPhaseAProvenanceError(
                    "Policy-backed text evidence lacks the resolved policy ID"
                )
            if source == "profile" and item.get("policy_id") not in (None, ""):
                raise LeverPhaseAProvenanceError(
                    "Profile text evidence must not claim an answer policy"
                )
        elif source:
            raise LeverPhaseAProvenanceError(
                "A serialized control-evidence entry has an unknown source"
            )

        signature = (
            required["control_id"],
            required["canonical_key"],
            source,
            pass_number,
        )
        if signature in seen:
            raise LeverPhaseAProvenanceError(
                "The serialized control evidence contains a duplicate identity"
            )
        seen.add(signature)
        if source != "profile":
            policy_count += 1

    reported_policy_count = exercise.get("policy_evidence_count")
    try:
        reported_policy_count = int(reported_policy_count)
    except (TypeError, ValueError) as exc:
        raise LeverPhaseAProvenanceError(
            "The exercise lacks a valid policy-evidence count"
        ) from exc
    if reported_policy_count != policy_count:
        raise LeverPhaseAProvenanceError(
            "The policy-evidence count does not match serialized evidence"
        )
    return evidence


def validate_ready_report(
    report: Mapping[str, Any],
    target: Mapping[str, Any],
) -> Dict[str, Any]:
''',
    "serialized evidence validator",
)
replace_once(
    finalizer,
    '''    if int(exercise.get("control_evidence_count") or 0) <= 0:
        raise LeverPhaseAProvenanceError("The exercise lacks control evidence")
''',
    '''    _validated_control_evidence(exercise)
''',
    "aggregate-only evidence check",
)

checkpoint = ROOT / "backend/scripts/verify_lever_phase_a_checkpoint.py"
replace_once(
    checkpoint,
    "_MIN_QUALIFYING_DRY_RUNS = 20\n",
    "_MIN_QUALIFYING_DRY_RUNS = 28\n",
    "checkpoint floor",
)

progression_test = ROOT / "backend/tests/test_lever_phase_a_checkpoint_progression.py"
replace_once(
    progression_test,
    '''    assert 20 <= result["qualifying_dry_run_count"] <= 30
''',
    '''    assert 28 <= result["qualifying_dry_run_count"] <= 30
''',
    "progression floor test",
)

text_test = ROOT / "backend/tests/test_text_control_evidence.py"
text_test.write_text(
    '''import json
import os

import pytest
import pytest_asyncio

from app.services import form_filler_v3
from app.services.lever_certification import _synthetic_policy
from app.services.text_control_evidence import install_text_control_evidence


install_text_control_evidence()


@pytest_asyncio.fixture
async def page():
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:
        await playwright.stop()
        if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(f"Chromium is required for text-evidence certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def _assert_redacted(evidence, raw_value):
    assert evidence["action"] == "control_verified"
    assert evidence["verification"] == "passed"
    assert evidence["value_redacted"] is True
    assert evidence["selected"] == []
    assert raw_value not in json.dumps(evidence, sort_keys=True)


@pytest.mark.asyncio
async def test_verified_profile_text_fill_retains_redacted_control_evidence(page):
    synthetic_email = "phase-a-day13@example.invalid"
    await page.set_content(
        '<label for="candidate-email">Email</label>'
        '<input id="candidate-email" name="email" type="email" required>'
    )

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={"email": synthetic_email, "answer_policies": []},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    assert outcome["filled_count"] == 1
    assert len(outcome["control_evidence"]) == 1
    evidence = outcome["control_evidence"][0]
    assert evidence["canonical_key"] == "profile.email"
    assert evidence["source"] == "profile"
    assert evidence["policy_id"] is None
    _assert_redacted(evidence, synthetic_email)


@pytest.mark.asyncio
async def test_prepopulated_profile_text_still_retains_evidence(page):
    synthetic_email = "prepopulated@example.invalid"
    await page.set_content(
        f'<label for="email">Email</label>'
        f'<input id="email" name="email" type="email" value="{synthetic_email}" required>'
    )

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={"email": synthetic_email, "answer_policies": []},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    assert outcome["filled_count"] == 0
    assert len(outcome["control_evidence"]) == 1
    assert outcome["control_evidence"][0]["prepopulated"] is True
    _assert_redacted(outcome["control_evidence"][0], synthetic_email)


@pytest.mark.asyncio
async def test_policy_text_evidence_retains_resolved_policy_id(page):
    answer = "Synthetic certification response."
    descriptor = "Why are you interested in this role?"
    policy = _synthetic_policy(
        77,
        canonical_key="custom.why_role",
        category="synthetic_certification",
        sensitivity="synthetic",
        answer=answer,
        descriptor=descriptor,
    )
    await page.set_content(
        '<label for="why">Why are you interested in this role?</label>'
        '<textarea id="why" name="why" required></textarea>'
    )

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={"answer_policies": [policy]},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    assert len(outcome["control_evidence"]) == 1
    evidence = outcome["control_evidence"][0]
    assert evidence["source"] == "answer_policy"
    assert evidence["policy_id"] == 77
    _assert_redacted(evidence, answer)


@pytest.mark.asyncio
async def test_repeated_text_controls_keep_distinct_identities(page):
    raw_value = "Synthetic Candidate"
    await page.set_content(
        '<label for="name-a">Full name</label><input id="name-a" required>'
        '<label for="name-b">Full name</label><input id="name-b" required>'
    )

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={"full_name": raw_value, "answer_policies": []},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    evidence = [
        item for item in outcome["control_evidence"]
        if item.get("canonical_key") == "profile.full_name"
    ]
    assert len(evidence) == 2
    assert len({item["control_id"] for item in evidence}) == 2
    for item in evidence:
        _assert_redacted(item, raw_value)


@pytest.mark.asyncio
async def test_text_evidence_installer_is_idempotent(page):
    install_text_control_evidence()
    install_text_control_evidence()
    await page.set_content(
        '<label for="name">Full name</label><input id="name" required>'
    )

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={"full_name": "Synthetic Candidate", "answer_policies": []},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    evidence = [
        item for item in outcome["control_evidence"]
        if item.get("canonical_key") == "profile.full_name"
    ]
    assert len(evidence) == 1
''',
    encoding="utf-8",
)

integrity_test = ROOT / "backend/tests/test_lever_control_evidence_integrity.py"
integrity_test.write_text(
    '''from __future__ import annotations

import pytest

from scripts import certify_lever_live


@pytest.mark.asyncio
async def test_exercise_serializes_per_control_evidence_and_separate_policy_count(
    monkeypatch,
):
    profile_evidence = {
        "action": "control_verified",
        "control_id": "jt-text-1",
        "control_type": "email",
        "descriptor": "Email",
        "canonical_key": "profile.email",
        "policy_id": None,
        "selected": [],
        "options_fingerprint": "a" * 16,
        "verification": "passed",
        "pass": 1,
        "source": "profile",
        "value_redacted": True,
    }
    policy_evidence = {
        "action": "control_verified",
        "control_id": "jt-text-2",
        "control_type": "textarea",
        "descriptor": "Why this role?",
        "canonical_key": "why_this_role",
        "policy_id": 7,
        "selected": [],
        "options_fingerprint": "b" * 16,
        "verification": "passed",
        "pass": 1,
        "source": "answer_policy",
        "value_redacted": True,
    }
    structured_evidence = {
        "action": "control_verified",
        "control_id": "jt-3",
        "control_type": "radio",
        "descriptor": "Authorized to work?",
        "canonical_key": "work_authorization",
        "policy_id": 8,
        "selected": [{"label": "Yes", "value": "yes"}],
        "options_fingerprint": "c" * 16,
        "verification": "passed",
        "pass": 1,
    }

    async def fake_fill_and_submit_application(**_kwargs):
        return {
            "success": True,
            "ready_to_submit": True,
            "ats_adapter": "lever",
            "ats_adapter_version": "1.1.0",
            "requires_manual_review": False,
            "steps_completed": 1,
            "fields_filled": 3,
            "review_items": [],
            "validation_errors": [],
            "upload_evidence": [{"verification": "passed"}],
            "step_evidence": [],
            "control_evidence": [
                profile_evidence,
                policy_evidence,
                structured_evidence,
            ],
            "log": [],
            "error": None,
        }

    monkeypatch.setattr(
        certify_lever_live,
        "fill_and_submit_application",
        fake_fill_and_submit_application,
    )
    report = await certify_lever_live.exercise_live_url(
        "https://jobs.lever.co/example/00000000-0000-0000-0000-000000000000/apply",
        profile={},
        resume_path="synthetic.pdf",
        cover_letter="",
        certification_metadata={"synthetic_profile": True},
    )

    assert report["control_evidence_schema_version"] == "1.0"
    assert report["control_evidence_count"] == 3
    assert report["policy_evidence_count"] == 2
    assert report["control_evidence"] == [
        profile_evidence,
        policy_evidence,
        structured_evidence,
    ]
''',
    encoding="utf-8",
)

provenance_test = ROOT / "backend/tests/test_lever_phase_a_ready_provenance.py"
replace_once(
    provenance_test,
    '''                "control_evidence_count": 5,
                "final_submit_clicked": False,
''',
    '''                "control_evidence_schema_version": "1.0",
                "control_evidence": [
                    {
                        "action": "control_verified",
                        "control_engine_version": "2.1.0",
                        "control_id": "jt-text-1",
                        "control_type": "email",
                        "descriptor": "Email",
                        "canonical_key": "profile.email",
                        "policy_id": None,
                        "selected": [],
                        "options_fingerprint": "a" * 16,
                        "verification": "passed",
                        "pass": 1,
                        "source": "profile",
                        "value_redacted": True,
                    },
                    {
                        "action": "control_verified",
                        "control_engine_version": "2.1.0",
                        "control_id": "jt-text-2",
                        "control_type": "textarea",
                        "descriptor": "Why this role?",
                        "canonical_key": "why_this_role",
                        "policy_id": 7,
                        "selected": [],
                        "options_fingerprint": "b" * 16,
                        "verification": "passed",
                        "pass": 1,
                        "source": "answer_policy",
                        "value_redacted": True,
                    },
                ],
                "control_evidence_count": 2,
                "policy_evidence_count": 1,
                "final_submit_clicked": False,
''',
    "ready-report fixture evidence",
)
replace_once(
    provenance_test,
    '''    assert rows[0]["source_reference"].endswith("/actions/runs/" + RUN_ID)
    assert sources == [
''',
    '''    assert rows[0]["source_reference"].endswith("/actions/runs/" + RUN_ID)
    assert rows[0]["policies_used"] == "1"
    assert sources == [
''',
    "candidate policy assertion",
)
replace_once(
    provenance_test,
    '''def test_manual_challenge_report_is_rejected() -> None:
''',
    '''def test_count_only_control_evidence_is_rejected() -> None:
    target = load_locked_target(
        REVIEW_ID,
        Path("evidence/lever-phase-a-target-corpus"),
    )
    report = _report()
    exercise = report["reports"][1]
    exercise.pop("control_evidence")
    with pytest.raises(LeverPhaseAProvenanceError, match="per-control"):
        validate_ready_report(report, target)


def test_policy_text_evidence_requires_resolved_policy_id() -> None:
    target = load_locked_target(
        REVIEW_ID,
        Path("evidence/lever-phase-a-target-corpus"),
    )
    report = _report()
    report["reports"][1]["control_evidence"][1]["policy_id"] = None
    with pytest.raises(LeverPhaseAProvenanceError, match="policy ID"):
        validate_ready_report(report, target)


def test_text_evidence_rejects_raw_value_fields() -> None:
    target = load_locked_target(
        REVIEW_ID,
        Path("evidence/lever-phase-a-target-corpus"),
    )
    report = _report()
    report["reports"][1]["control_evidence"][0]["value"] = "secret"
    with pytest.raises(LeverPhaseAProvenanceError, match="raw-value"):
        validate_ready_report(report, target)


def test_duplicate_control_evidence_identity_is_rejected() -> None:
    target = load_locked_target(
        REVIEW_ID,
        Path("evidence/lever-phase-a-target-corpus"),
    )
    report = _report()
    duplicate = dict(report["reports"][1]["control_evidence"][0])
    report["reports"][1]["control_evidence"].append(duplicate)
    report["reports"][1]["control_evidence_count"] = 3
    with pytest.raises(LeverPhaseAProvenanceError, match="duplicate identity"):
        validate_ready_report(report, target)


def test_manual_challenge_report_is_rejected() -> None:
''',
    "provenance rejection tests",
)

freeze_path = ROOT / "docs/operations/lever-phase-2-measurement-freeze.json"
freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
freeze["contract_version"] = "2026-08-04.day13.2"
freeze["amendment"]["previous_contract_version"] = "2026-08-04.day13.1"
freeze["amendment"]["purpose"] = (
    "Harden the retained Day 13 checkpoint with serialized per-control evidence, "
    "prepopulated and repeated text-control identities, resolved policy IDs, "
    "source-correct policy counts, and a monotonic 28-run floor."
)
additional_inputs = [
    "backend/app/services/form_filler_v3.py",
    "backend/scripts/certify_lever_live.py",
    "backend/scripts/finalize_lever_phase_a_ready.py",
    "backend/tests/test_lever_control_evidence_integrity.py",
    "backend/tests/test_lever_phase_a_ready_provenance.py",
]
for value in additional_inputs:
    if value not in freeze["canonical_inputs"]:
        freeze["canonical_inputs"].append(value)
freeze["canonical_inputs"] = sorted(freeze["canonical_inputs"])
for value in freeze["canonical_inputs"]:
    path = ROOT / value
    if not path.is_file():
        raise RuntimeError(f"Frozen canonical input is missing: {value}")
    blob = subprocess.check_output(
        ["git", "hash-object", str(path)],
        cwd=ROOT,
        text=True,
    ).strip()
    freeze["locked_input_blobs"][value] = blob
freeze["locked_input_blobs"] = {
    key: freeze["locked_input_blobs"][key]
    for key in sorted(freeze["locked_input_blobs"])
}
freeze_path.write_text(
    json.dumps(freeze, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

print("Materialized Lever Day 13 evidence-integrity repair")
