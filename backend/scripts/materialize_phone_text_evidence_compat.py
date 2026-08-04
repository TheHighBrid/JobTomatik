#!/usr/bin/env python3
"""Forward text evidence through the Greenhouse phone compatibility wrapper."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/app/services/greenhouse_phone_widget.py"
TEST = ROOT / "backend/tests/test_text_control_evidence.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} block, found {count}")
    return text.replace(old, new, 1)


source = SOURCE.read_text(encoding="utf-8")
source = replace_once(
    source,
    '''async def _reconcile_phone_review(
    surface: Any,
    *,
    profile: Dict[str, Any],
    cover_letter: str,
    log: List[Dict[str, Any]],
    review_items: List[Dict[str, Any]],
) -> int:
''',
    '''async def _reconcile_phone_review(
    surface: Any,
    *,
    profile: Dict[str, Any],
    cover_letter: str,
    log: List[Dict[str, Any]],
    review_items: List[Dict[str, Any]],
    control_evidence: List[Dict[str, Any]],
) -> int:
''',
    "phone reconcile signature",
)

old_log = '''            log.append({
                "action": "phone_format_verified",
                "field": "phone",
                "descriptor": marker_descriptor[:200],
                "control_descriptor": control_descriptor[:200],
                "verification": (
                    "same_shell_keyboard_significant_digits"
                    if keyboard_retry
                    else "same_shell_significant_digits"
                ),
                "proxy_reconciled": phone_control is not marker,
                "actual_digit_count": len(_digits(actual)),
                "expected_digit_count": len(_digits(expected)),
                "counted": not already_verified,
                "verified": True,
            })
            if not already_verified:
                reconciled += 1
'''
new_log = '''            verification_method = (
                "same_shell_keyboard_significant_digits"
                if keyboard_retry
                else "same_shell_significant_digits"
            )
            log.append({
                "action": "phone_format_verified",
                "field": "phone",
                "descriptor": marker_descriptor[:200],
                "control_descriptor": control_descriptor[:200],
                "verification": verification_method,
                "proxy_reconciled": phone_control is not marker,
                "actual_digit_count": len(_digits(actual)),
                "expected_digit_count": len(_digits(expected)),
                "counted": not already_verified,
                "verified": True,
            })
            if not already_verified:
                from app.services import form_filler_v3

                evidence = await form_filler_v3._verified_text_control_evidence(
                    phone_control,
                    descriptor=control_descriptor or marker_descriptor,
                    value=actual,
                    canonical_key="profile.phone",
                    source="profile",
                )
                evidence["verification_method"] = verification_method
                evidence["semantic_verification"] = "significant_digits"
                control_evidence.append(evidence)
                log.append(dict(evidence))
                reconciled += 1
'''
source = replace_once(source, old_log, new_log, "phone evidence emission")

source = replace_once(
    source,
    '''    async def fill_text_fields_with_phone_compat(
        surface: Any,
        *,
        profile: Dict[str, Any],
        cover_letter: str,
        policies: List[Dict[str, Any]],
        log: List[Dict[str, Any]],
        review_items: List[Dict[str, Any]],
    ) -> int:
''',
    '''    async def fill_text_fields_with_phone_compat(
        surface: Any,
        *,
        profile: Dict[str, Any],
        cover_letter: str,
        policies: List[Dict[str, Any]],
        log: List[Dict[str, Any]],
        review_items: List[Dict[str, Any]],
        control_evidence: List[Dict[str, Any]],
    ) -> int:
''',
    "phone wrapper signature",
)

source = replace_once(
    source,
    '''            log=log,
            review_items=review_items,
        )
        filled += await _reconcile_phone_review(
''',
    '''            log=log,
            review_items=review_items,
            control_evidence=control_evidence,
        )
        filled += await _reconcile_phone_review(
''',
    "original recorder forwarding",
)

source = replace_once(
    source,
    '''            log=log,
            review_items=review_items,
        )
        return filled
''',
    '''            log=log,
            review_items=review_items,
            control_evidence=control_evidence,
        )
        return filled
''',
    "phone reconcile forwarding",
)
SOURCE.write_text(source, encoding="utf-8")

text = TEST.read_text(encoding="utf-8")
text = replace_once(
    text,
    "import json\nimport os\nimport re\n",
    "import inspect\nimport json\nimport os\nimport re\n",
    "test inspect import",
)
text = replace_once(
    text,
    "from app.services.lever_certification import _synthetic_policy\n",
    "from app.services.lever_certification import _synthetic_policy\n"
    "from app.services.greenhouse_phone_widget import (\n"
    "    install_greenhouse_phone_widget_compat,\n"
    ")\n"
    "from app.services import form_filler_v3\n",
    "test compatibility imports",
)
text += '''\n\ndef test_phone_widget_compat_forwards_text_evidence_argument():
    install_greenhouse_phone_widget_compat()
    signature = inspect.signature(form_filler_v3._fill_text_fields)
    assert "control_evidence" in signature.parameters
'''
TEST.write_text(text, encoding="utf-8")

print("Materialized phone-widget text evidence compatibility")
