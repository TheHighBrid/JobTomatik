"""Conservative compatibility checks for Greenhouse international phone widgets.

Greenhouse can render a hidden required-marker input beside the real international
phone control. These helpers reconcile an exact phone review only through one
unambiguous visible phone input in the same field shell and only after semantic
digit verification.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.services import control_aria
from app.services.control_engine import element_descriptor
from app.services.control_primitives import OptionRecord, normalize_text
from app.services.form_filler_v2 import _profile_values, _safe_field


_INSTALLED = False
_ORIGINAL_FILL_TEXT_FIELDS = None
_ORIGINAL_DISPLAY_MATCHES_OPTION = None
_PHONE_SHELL_SELECTOR = (
    '[data-field],.field-wrapper,.application-field,'
    '[class*="field-wrapper"],[class*="application-field"],fieldset'
)
_PHONE_INPUT_SELECTOR = (
    'input[type="tel"],input[name*="phone" i],input[id*="phone" i],'
    'input[class*="tel-input" i],input:not([type]),input[type="text"]'
)


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def phone_values_equivalent(actual: Any, expected: Any) -> bool:
    """Verify equivalent national and international phone representations."""
    actual_digits = _digits(actual)
    expected_digits = _digits(expected)
    if not actual_digits or not expected_digits:
        return False
    if actual_digits == expected_digits:
        return True
    if min(len(actual_digits), len(expected_digits)) < 8:
        return False
    return (
        actual_digits.endswith(expected_digits)
        or expected_digits.endswith(actual_digits)
    )


def _dial_code(value: Any) -> str:
    match = re.search(r"\+\d{1,4}\b", str(value or ""))
    return match.group(0) if match else ""


def dial_code_option_equivalent(displayed: str, option: OptionRecord) -> bool:
    """Confirm that an exact matched country option collapsed to its dial code."""
    expected_code = _dial_code(option.label) or _dial_code(option.value)
    displayed_code = _dial_code(displayed)
    if not expected_code or displayed_code != expected_code:
        return False
    return bool(re.search(r"[A-Za-z]", str(option.label or option.value or "")))


def _matching_phone_reviews(
    review_items: List[Dict[str, Any]],
    descriptor: str,
) -> List[Dict[str, Any]]:
    return [
        item
        for item in review_items
        if (
            item.get("reason_code") == "unsupported_control"
            and (item.get("details") or {}).get("canonical_key") == "profile.phone"
            and (item.get("details") or {}).get("descriptor") == descriptor
            and (item.get("details") or {}).get("control_type") == "text"
        )
    ]


async def _retry_phone_with_keyboard(
    surface: Any,
    element: Any,
    expected: str,
) -> str:
    """Use normal keyboard events when a masked phone input rejects bulk fill."""
    try:
        await element.evaluate("(el) => el.focus()")
        await element.press("Control+A")
        await element.type(expected, delay=25)
        await element.press("Tab")
        await surface.wait_for_timeout(150)
        return str(await element.input_value())
    except Exception:
        return ""


async def _phone_candidate_score(surface: Any, element: Any) -> Tuple[int, str]:
    """Score only explicit phone signals; zero means the control is ineligible."""
    descriptor = await element_descriptor(surface, element)
    input_type = normalize_text(await element.get_attribute("type"))
    element_id = normalize_text(await element.get_attribute("id"))
    name = normalize_text(await element.get_attribute("name"))
    class_name = normalize_text(await element.get_attribute("class"))

    score = 0
    if input_type == "tel":
        score += 100
    if re.search(r"\bphone\b", f"{element_id} {name}"):
        score += 40
    if "tel input" in class_name or "tel-input" in class_name:
        score += 30
    if _safe_field(descriptor) == "phone":
        score += 20
    return score, descriptor


async def _same_shell_phone_control(
    surface: Any,
    marker: Any,
) -> Tuple[Optional[Any], str]:
    """Return one uniquely strongest visible phone input from the marker's shell."""
    shell_handle = await marker.evaluate_handle(
        f'(el) => el.closest({repr(_PHONE_SHELL_SELECTOR)}) || el.parentElement'
    )
    shell = shell_handle.as_element()
    if shell is None:
        return None, ""

    scored: List[Tuple[int, Any, str]] = []
    for candidate in await shell.query_selector_all(_PHONE_INPUT_SELECTOR):
        try:
            if not await candidate.is_visible() or not await candidate.is_enabled():
                continue
            if normalize_text(await candidate.get_attribute("aria-hidden")) == "true":
                continue
            if await candidate.get_attribute("readonly") is not None:
                continue
            score, descriptor = await _phone_candidate_score(surface, candidate)
            if score > 0:
                scored.append((score, candidate, descriptor))
        except Exception:
            continue

    if not scored:
        return None, ""
    top_score = max(score for score, _, _ in scored)
    strongest = [(candidate, descriptor) for score, candidate, descriptor in scored if score == top_score]
    if len(strongest) != 1:
        return None, ""
    return strongest[0]


async def _reconcile_phone_review(
    surface: Any,
    *,
    profile: Dict[str, Any],
    cover_letter: str,
    log: List[Dict[str, Any]],
    review_items: List[Dict[str, Any]],
) -> int:
    expected = str(_profile_values(profile, cover_letter).get("phone") or "")
    if not expected:
        return 0

    reconciled = 0
    for marker in await surface.query_selector_all(_PHONE_INPUT_SELECTOR):
        try:
            if not await marker.is_visible() or not await marker.is_enabled():
                continue
            marker_descriptor = await element_descriptor(surface, marker)
            matching_reviews = _matching_phone_reviews(review_items, marker_descriptor)
            if not matching_reviews:
                continue

            phone_control, control_descriptor = await _same_shell_phone_control(
                surface,
                marker,
            )
            if phone_control is None:
                continue

            actual = str(await phone_control.input_value())
            keyboard_retry = False
            if not phone_values_equivalent(actual, expected):
                actual = await _retry_phone_with_keyboard(
                    surface,
                    phone_control,
                    expected,
                )
                keyboard_retry = True
            if not phone_values_equivalent(actual, expected):
                continue

            for item in matching_reviews:
                if item in review_items:
                    review_items.remove(item)

            already_verified = (
                await phone_control.get_attribute("data-jt-phone-format-verified") == "true"
            )
            await phone_control.evaluate(
                "(el) => el.setAttribute('data-jt-phone-format-verified', 'true')"
            )
            log.append({
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
        except Exception:
            continue
    return reconciled


def install_greenhouse_phone_widget_compat() -> None:
    """Install idempotent phone verification wrappers after form_filler_v3 loads."""
    global _INSTALLED, _ORIGINAL_FILL_TEXT_FIELDS, _ORIGINAL_DISPLAY_MATCHES_OPTION
    if _INSTALLED:
        return

    from app.services import form_filler_v3

    _ORIGINAL_FILL_TEXT_FIELDS = form_filler_v3._fill_text_fields
    _ORIGINAL_DISPLAY_MATCHES_OPTION = control_aria._display_matches_option

    async def fill_text_fields_with_phone_compat(
        surface: Any,
        *,
        profile: Dict[str, Any],
        cover_letter: str,
        policies: List[Dict[str, Any]],
        log: List[Dict[str, Any]],
        review_items: List[Dict[str, Any]],
    ) -> int:
        filled = await _ORIGINAL_FILL_TEXT_FIELDS(
            surface,
            profile=profile,
            cover_letter=cover_letter,
            policies=policies,
            log=log,
            review_items=review_items,
        )
        filled += await _reconcile_phone_review(
            surface,
            profile=profile,
            cover_letter=cover_letter,
            log=log,
            review_items=review_items,
        )
        return filled

    def display_matches_option_with_dial_code(
        displayed: str,
        option: OptionRecord,
    ) -> bool:
        return bool(
            _ORIGINAL_DISPLAY_MATCHES_OPTION(displayed, option)
            or dial_code_option_equivalent(displayed, option)
        )

    form_filler_v3._fill_text_fields = fill_text_fields_with_phone_compat
    control_aria._display_matches_option = display_matches_option_with_dial_code
    _INSTALLED = True


__all__ = [
    "dial_code_option_equivalent",
    "install_greenhouse_phone_widget_compat",
    "phone_values_equivalent",
]
