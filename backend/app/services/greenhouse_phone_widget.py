"""Conservative compatibility checks for Greenhouse international phone widgets.

Greenhouse separates the country selector from the national phone input. The
selected country button may collapse to a dial code, and the text input may
format punctuation or prepend that code. These helpers verify semantic equality
without weakening option matching or allowing fallback selection.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

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


def _phone_fill_candidates(profile: Dict[str, Any], expected: str) -> List[str]:
    """Return explicit representations that preserve the configured phone value."""
    values = [str(expected or "").strip()]
    digits = _digits(expected)
    country = " ".join(
        str(profile.get(key) or "")
        for key in ("country", "country_code", "phone_country")
    ).lower()

    north_american = any(
        token in country
        for token in ("canada", "united states", "usa", "u.s.a", " us ")
    )
    if north_american and len(digits) == 10:
        values.append(f"+1{digits}")
    elif north_american and len(digits) == 11 and digits.startswith("1"):
        values.append(digits[1:])

    return list(dict.fromkeys(value for value in values if value))


async def _observed_phone_values(element: Any) -> List[str]:
    values: List[str] = []
    try:
        values.append(str(await element.input_value()))
    except Exception:
        pass
    for attribute in ("value", "aria-valuetext", "data-value"):
        try:
            values.append(str(await element.get_attribute(attribute) or ""))
        except Exception:
            continue
    try:
        evaluated = await element.evaluate(
            """(el) => [
              el.value || '',
              el.defaultValue || '',
              el.getAttribute('value') || '',
              el.getAttribute('aria-valuetext') || '',
              el.dataset?.value || ''
            ]"""
        )
        if isinstance(evaluated, list):
            values.extend(str(value or "") for value in evaluated)
    except Exception:
        pass
    return list(dict.fromkeys(value for value in values if value))


async def _try_phone_candidate(
    surface: Any,
    element: Any,
    candidate: str,
    expected: str,
) -> Tuple[str, str]:
    methods = ("fill", "type", "native_setter")
    for method in methods:
        try:
            if method == "fill":
                await element.fill(candidate)
            elif method == "type":
                await element.click()
                await element.press("Control+A")
                await element.type(candidate, delay=15)
            else:
                await element.evaluate(
                    """(el, value) => {
                      const prototype = Object.getPrototypeOf(el);
                      const setter = Object.getOwnPropertyDescriptor(
                        prototype, 'value'
                      )?.set;
                      if (setter) setter.call(el, value);
                      else el.value = value;
                      el.dispatchEvent(new Event('input', {bubbles: true}));
                      el.dispatchEvent(new Event('change', {bubbles: true}));
                    }""",
                    candidate,
                )
            try:
                await element.press("Tab")
            except Exception:
                pass
            await surface.wait_for_timeout(150)
            observed = await _observed_phone_values(element)
            match = next(
                (
                    value
                    for value in observed
                    if phone_values_equivalent(value, expected)
                ),
                "",
            )
            if match:
                return match, method
        except Exception:
            continue
    return "", ""


def _phone_review_items(review_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        item
        for item in review_items
        if item.get("reason_code") == "unsupported_control"
        and (item.get("details") or {}).get("canonical_key") == "profile.phone"
        and (item.get("details") or {}).get("control_type") == "text"
    ]


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

            matching_reviews = _phone_review_items(review_items)
            if not matching_reviews:
                continue

            observed = await _observed_phone_values(element)
            actual = next(
                (
                    value
                    for value in observed
                    if phone_values_equivalent(value, expected)
                ),
                "",
            )
            fill_method = "existing_value"
            candidate_used = ""
            if not actual:
                for candidate in _phone_fill_candidates(profile, expected):
                    actual, fill_method = await _try_phone_candidate(
                        surface,
                        element,
                        candidate,
                        expected,
                    )
                    if actual:
                        candidate_used = candidate
                        break

            if not actual:
                log.append({
                    "action": "phone_widget_retry_failed",
                    "field": "phone",
                    "descriptor": descriptor[:200],
                    "expected_digit_count": len(_digits(expected)),
                    "observed_digit_counts": sorted({
                        len(_digits(value)) for value in observed if _digits(value)
                    }),
                    "verified": False,
                })
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
                "verification": "significant_digits",
                "fill_method": fill_method,
                "candidate_digit_count": len(_digits(candidate_used)),
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
