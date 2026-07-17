"""Conservative compatibility checks for Greenhouse international phone widgets.

Greenhouse separates the country selector from the national phone input. The
selected country button may collapse to a dial code, and the text input may
format punctuation or prepend that code. These helpers verify semantic equality
without weakening option matching or allowing fallback selection.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.services import control_aria
from app.services.control_engine import element_descriptor
from app.services.control_primitives import OptionRecord
from app.services.form_filler_v2 import _profile_values, _safe_field


_INSTALLED = False
_ORIGINAL_FILL_TEXT_FIELDS = None
_ORIGINAL_DISPLAY_MATCHES_OPTION = None


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def phone_values_equivalent(actual: Any, expected: Any) -> bool:
    """Verify equivalent national/international phone representations."""
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
    """Confirm that an exact matched phone-country option changed to its dial code."""
    expected_code = _dial_code(option.label) or _dial_code(option.value)
    displayed_code = _dial_code(displayed)
    if not expected_code or displayed_code != expected_code:
        return False

    expected_text = str(option.label or option.value or "")
    # Country options contain a name plus a dial code. This avoids treating an
    # unrelated numeric option as a phone-country selection.
    return bool(re.search(r"[A-Za-z]", expected_text))


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
    # Some Greenhouse forms expose the phone control as an opaque text input.
    # Candidate enumeration is intentionally broad, but descriptor classification
    # below must still identify the field as profile.phone before any review is
    # reconciled.
    candidates = await surface.query_selector_all(
        'input[type="tel"],input[name*="phone" i],input[id*="phone" i],'
        'input:not([type]),input[type="text"]'
    )
    for element in candidates:
        try:
            if not await element.is_visible() or not await element.is_enabled():
                continue
            descriptor = await element_descriptor(surface, element)
            if _safe_field(descriptor) != "phone":
                continue

            matching_reviews = _matching_phone_reviews(review_items, descriptor)
            if not matching_reviews:
                continue

            actual = str(await element.input_value())
            keyboard_retry = False
            if not phone_values_equivalent(actual, expected):
                actual = await _retry_phone_with_keyboard(
                    surface,
                    element,
                    expected,
                )
                keyboard_retry = True
            if not phone_values_equivalent(actual, expected):
                continue

            for item in matching_reviews:
                if item in review_items:
                    review_items.remove(item)

            already_verified = (
                await element.get_attribute("data-jt-phone-format-verified") == "true"
            )
            await element.evaluate(
                "(el) => el.setAttribute('data-jt-phone-format-verified', 'true')"
            )
            log.append({
                "action": "phone_format_verified",
                "field": "phone",
                "descriptor": descriptor[:200],
                "verification": (
                    "keyboard_significant_digits"
                    if keyboard_retry
                    else "significant_digits"
                ),
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
