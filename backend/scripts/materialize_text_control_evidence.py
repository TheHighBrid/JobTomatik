#!/usr/bin/env python3
"""Apply the audited text-control evidence patch and focused regression tests."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/app/services/form_filler_v3.py"
TEST = ROOT / "backend/tests/test_text_control_evidence.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} block, found {count}")
    return text.replace(old, new, 1)


source = SOURCE.read_text(encoding="utf-8")
source = replace_once(
    source,
    "from __future__ import annotations\n\nfrom typing import Any, Dict, List, Mapping, Optional\n",
    "from __future__ import annotations\n\nimport hashlib\nfrom typing import Any, Dict, List, Mapping, Optional\n",
    "import",
)

anchor = '''async def _fill_text_fields(
    surface: Any,
    *,
    profile: Dict[str, Any],
    cover_letter: str,
    policies: List[Dict[str, Any]],
    log: List[Dict[str, Any]],
    review_items: List[Dict[str, Any]],
) -> int:
'''
helper = '''async def _verified_text_control_evidence(
    element: Any,
    *,
    descriptor: str,
    value: str,
    canonical_key: str,
    source: str,
    policy_id: Any = None,
) -> Dict[str, Any]:
    metadata = await element.evaluate(
        """(el) => {
          let counter = Number(document.documentElement.dataset.jtTextEvidenceCounter || 0);
          if (!el.dataset.jtTextEvidenceId) {
            counter += 1;
            el.dataset.jtTextEvidenceId = `jt-text-${counter}`;
            document.documentElement.dataset.jtTextEvidenceCounter = String(counter);
          }
          return {
            controlId: el.dataset.jtTextEvidenceId,
            tag: (el.tagName || '').toLowerCase(),
            inputType: el.getAttribute('type') || '',
            name: el.getAttribute('name') || '',
            id: el.id || ''
          };
        }"""
    )
    control_id = str(metadata.get("controlId") or "")
    control_type = (
        "textarea"
        if metadata.get("tag") == "textarea"
        else str(metadata.get("inputType") or "text").lower()
    )
    fingerprint_input = (
        f"jobtomatik-text-evidence-v1\\0{control_id}\\0{value}"
    ).encode("utf-8")
    return {
        "action": "text_fill_verified",
        "control_id": control_id,
        "control_type": control_type,
        "descriptor": descriptor[:200],
        "canonical_key": canonical_key,
        "policy_id": policy_id,
        "source": source,
        "verification": "passed",
        "verification_method": "browser_input_value_readback",
        "value_sha256": hashlib.sha256(fingerprint_input).hexdigest(),
        "value_length": len(value),
        "name": str(metadata.get("name") or ""),
        "id": str(metadata.get("id") or ""),
    }


async def _fill_text_fields(
    surface: Any,
    *,
    profile: Dict[str, Any],
    cover_letter: str,
    policies: List[Dict[str, Any]],
    log: List[Dict[str, Any]],
    review_items: List[Dict[str, Any]],
    control_evidence: List[Dict[str, Any]],
) -> int:
'''
source = replace_once(source, anchor, helper, "text fill signature")

policy_log = '''                        log.append({
                            "action": "fill",
                            "descriptor": descriptor[:200],
                            "canonical_key": policy.get("canonical_key"),
                            "source": "answer_policy",
                            "verified": True,
                            "ts": now_iso(),
                        })
'''
policy_log_new = policy_log + '''                        evidence = await _verified_text_control_evidence(
                            element,
                            descriptor=descriptor,
                            value=answer,
                            canonical_key=str(policy.get("canonical_key") or ""),
                            source="answer_policy",
                            policy_id=(policy.get("policy") or {}).get("id"),
                        )
                        control_evidence.append(evidence)
                        log.append(dict(evidence))
'''
source = replace_once(source, policy_log, policy_log_new, "policy text evidence")

profile_log = '''                        log.append({
                            "action": "fill",
                            "field": field,
                            "descriptor": descriptor[:200],
                            "source": "profile",
                            "verified": True,
                            "ts": now_iso(),
                        })
'''
profile_log_new = profile_log + '''                        evidence = await _verified_text_control_evidence(
                            element,
                            descriptor=descriptor,
                            value=value,
                            canonical_key=f"profile.{field}",
                            source="profile",
                        )
                        control_evidence.append(evidence)
                        log.append(dict(evidence))
'''
source = replace_once(source, profile_log, profile_log_new, "profile text evidence")

source = replace_once(
    source,
    '''    policies = list(profile.get("answer_policies") or [])
    review_items: List[Dict[str, Any]] = []
    filled = 0
''',
    '''    policies = list(profile.get("answer_policies") or [])
    review_items: List[Dict[str, Any]] = []
    text_evidence: List[Dict[str, Any]] = []
    filled = 0
''',
    "step evidence initialization",
)

call = '''        log=log,
        review_items=review_items,
    )
'''
call_new = '''        log=log,
        review_items=review_items,
        control_evidence=text_evidence,
    )
'''
if source.count(call) != 2:
    raise RuntimeError(f"Expected two text fill calls, found {source.count(call)}")
source = source.replace(call, call_new)

source = replace_once(
    source,
    '''        "control_evidence": control_outcome.evidence,
''',
    '''        "control_evidence": text_evidence + control_outcome.evidence,
''',
    "step control evidence return",
)
SOURCE.write_text(source, encoding="utf-8")

TEST.write_text(
    '''import json
import os
import re

import pytest
import pytest_asyncio

from app.services.form_filler_v3 import _fill_step_fields
from app.services.lever_certification import _synthetic_policy


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


def assert_redacted(evidence, raw_value):
    assert evidence["action"] == "text_fill_verified"
    assert evidence["verification"] == "passed"
    assert evidence["verification_method"] == "browser_input_value_readback"
    assert evidence["value_length"] == len(raw_value)
    assert re.fullmatch(r"[0-9a-f]{64}", evidence["value_sha256"])
    assert raw_value not in json.dumps(evidence, sort_keys=True)


@pytest.mark.asyncio
async def test_profile_text_field_emits_redacted_verified_evidence(page):
    raw_value = "Avery Certification"
    await page.set_content(
        '<label for="name">Full name</label>'
        '<input id="name" name="name" required>'
    )

    outcome = await _fill_step_fields(
        page,
        profile={"full_name": raw_value, "answer_policies": []},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    assert outcome["review_items"] == []
    assert outcome["filled_count"] == 1
    assert len(outcome["control_evidence"]) == 1
    evidence = outcome["control_evidence"][0]
    assert evidence["source"] == "profile"
    assert evidence["canonical_key"] == "profile.full_name"
    assert evidence["policy_id"] is None
    assert evidence["control_type"] == "text"
    assert await page.locator("#name").input_value() == raw_value
    assert_redacted(evidence, raw_value)


@pytest.mark.asyncio
async def test_policy_textarea_emits_one_redacted_evidence_record(page):
    raw_value = "Synthetic certification response that is never submitted."
    descriptor = "Why are you interested in this role?"
    policy = _synthetic_policy(
        77,
        canonical_key="custom.why_role",
        category="synthetic_certification",
        sensitivity="synthetic",
        answer=raw_value,
        descriptor=descriptor,
    )
    await page.set_content(
        '<label for="why">Why are you interested in this role?</label>'
        '<textarea id="why" name="why" required></textarea>'
    )

    outcome = await _fill_step_fields(
        page,
        profile={"answer_policies": [policy]},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    assert outcome["review_items"] == []
    assert outcome["filled_count"] == 1
    assert len(outcome["control_evidence"]) == 1
    evidence = outcome["control_evidence"][0]
    assert evidence["source"] == "answer_policy"
    assert evidence["canonical_key"] == "custom.why_role"
    assert evidence["policy_id"] == 77
    assert evidence["control_type"] == "textarea"
    assert await page.locator("#why").input_value() == raw_value
    assert_redacted(evidence, raw_value)
''',
    encoding="utf-8",
)

print("Materialized verified text-control evidence and regression tests")
