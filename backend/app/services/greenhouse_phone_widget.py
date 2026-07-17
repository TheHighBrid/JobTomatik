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
    actual_digits = _digits(actual)
    expected_digits = _digits(expected)
    if not actual_digits or not expected_digits:
        return False
    if actual_digits == expected_digits:
        return True
    if min(len(actual_digits), len(expected_digits)) < 8:
        return False
    return actual_digits.endswith(expected_digits) or expected_digits.endswith(actual_digits)


def _dial_code(value: Any) -> str:
    match = re.search(r"\+\d{1,4}\b", str(value or ""))
    return match.group(0) if match else ""


def dial_code_option_equivalent(displayed: str, option: OptionRecord) -> bool:
    expected_code = _dial_code(option.label) or _dial_code(option.value)
    displayed_code = _dial_code(displayed)
    if not expected_code or displayed_code != expected_code:
        return False
    return bool(re.search(r"[A-Za-z]", str(option.label or option.value or "")))


def _matching_phone_reviews(
    review_items: List[Dict[str, Any]], descriptor: str,
) -> List[Dict[str, Any]]:
    return [
        item for item in review_items
        if (
            item.get("reason_code") == "unsupported_control"
            and (item.get("details") or {}).get("canonical_key") == "profile.phone"
            and (item.get("details") or {}).get("descriptor") == descriptor
            and (item.get("details") or {}).get("control_type") == "text"
        )
    ]


def _phone_attempts(profile: Dict[str, Any], expected: str) -> List[Tuple[str, str]]:
    attempts = [("profile", expected)]
    country = str(profile.get("country") or "").strip().casefold()
    digits = _digits(expected)
    if (
        profile.get("synthetic_certification_only") is True
        and country == "canada"
        and not str(expected).strip().startswith("+")
        and len(digits) == 10
    ):
        attempts.append(("canada_e164", f"+1{digits}"))
    return attempts


async def _phone_surface_diagnostics(element: Any) -> Dict[str, Any]:
    """Return structural metadata only, never raw control values."""
    try:
        return await element.evaluate(
            """(el) => {
              const root = el.closest(
                '[data-field],.field-wrapper,.application-field,' +
                '[class*="field-wrapper"],[class*="application-field"],fieldset'
              ) || el.parentElement;
              const controls = Array.from(root?.querySelectorAll(
                'input,textarea,[contenteditable="true"],[role="textbox"],' +
                'button,[role="combobox"]'
              ) || []).slice(0, 16);
              const describe = (node) => {
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                const value = ('value' in node ? node.value : '') || '';
                return {
                  target: node === el,
                  active: document.activeElement === node,
                  tag: node.tagName.toLowerCase(),
                  id: (node.id || '').slice(0, 120),
                  name: (node.getAttribute('name') || '').slice(0, 120),
                  type: node.getAttribute('type') || '',
                  role: node.getAttribute('role') || '',
                  inputmode: node.getAttribute('inputmode') || '',
                  autocomplete: node.getAttribute('autocomplete') || '',
                  contenteditable: node.getAttribute('contenteditable') || '',
                  ariaHidden: node.getAttribute('aria-hidden') || '',
                  ariaControls: (node.getAttribute('aria-controls') || '').slice(0, 120),
                  disabled: Boolean(node.disabled || node.getAttribute('disabled') !== null),
                  readonly: Boolean(node.readOnly || node.getAttribute('readonly') !== null),
                  visible: style.display !== 'none' && style.visibility !== 'hidden'
                    && rect.width > 0 && rect.height > 0,
                  width: Math.round(rect.width),
                  height: Math.round(rect.height),
                  maxLength: typeof node.maxLength === 'number' ? node.maxLength : null,
                  digitCount: String(value).replace(/\D/g, '').length,
                  className: String(node.className || '').slice(0, 180)
                };
              };
              return {
                activeIsTarget: document.activeElement === el,
                rootTag: root?.tagName?.toLowerCase() || '',
                rootId: (root?.id || '').slice(0, 120),
                rootClassName: String(root?.className || '').slice(0, 180),
                controlCount: controls.length,
                controls: controls.map(describe)
              };
            }"""
        )
    except Exception as exc:
        return {
            "error_type": type(exc).__name__,
            "error": str(exc)[:200],
        }


async def _retry_phone_with_keyboard(
    surface: Any, element: Any, candidate: str,
) -> Tuple[str, Dict[str, Any]]:
    diagnostics: Dict[str, Any] = {
        "attempted": True,
        "candidate_digit_count": len(_digits(candidate)),
    }
    try:
        diagnostics.update({
            "tag": await element.evaluate("(el) => el.tagName.toLowerCase()"),
            "type": await element.get_attribute("type") or "",
            "inputmode": await element.get_attribute("inputmode") or "",
            "autocomplete": await element.get_attribute("autocomplete") or "",
            "role": await element.get_attribute("role") or "",
            "before_digit_count": len(_digits(await element.input_value())),
            "active_before_focus": await element.evaluate(
                "(el) => document.activeElement === el"
            ),
        })
        await element.evaluate("(el) => el.focus()")
        diagnostics["active_after_focus"] = await element.evaluate(
            "(el) => document.activeElement === el"
        )
        await element.press("Control+A")
        await element.type(candidate, delay=25)
        diagnostics["active_after_type"] = await element.evaluate(
            "(el) => document.activeElement === el"
        )
        diagnostics["immediate_digit_count"] = len(_digits(await element.input_value()))
        await element.press("Tab")
        await surface.wait_for_timeout(150)
        actual = str(await element.input_value())
        diagnostics["after_blur_digit_count"] = len(_digits(actual))
        return actual, diagnostics
    except Exception as exc:
        diagnostics.update({
            "error_type": type(exc).__name__,
            "error": str(exc)[:200],
        })
        return "", diagnostics


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
    candidates = await surface.query_selector_all(
        'input[type="tel"],input[name*="phone" i],input[id*="phone" i],'
        'input:not([type]),input[type="text"]'
    )
    for element in candidates:
        descriptor = ""
        try:
            if not await element.is_visible() or not await element.is_enabled():
                continue
            descriptor = await element_descriptor(surface, element)
            if _safe_field(descriptor) != "phone":
                continue
            matching_reviews = _matching_phone_reviews(review_items, descriptor)
            if not matching_reviews:
                continue

            surface_before = await _phone_surface_diagnostics(element)
            actual = str(await element.input_value())
            keyboard_retry = False
            attempt_diagnostics: List[Dict[str, Any]] = []
            if not phone_values_equivalent(actual, expected):
                keyboard_retry = True
                for attempt_name, candidate in _phone_attempts(profile, expected):
                    actual, diagnostics = await _retry_phone_with_keyboard(
                        surface, element, candidate,
                    )
                    diagnostics["attempt_format"] = attempt_name
                    diagnostics["equivalent_to_profile"] = phone_values_equivalent(
                        actual, expected,
                    )
                    attempt_diagnostics.append(diagnostics)
                    if phone_values_equivalent(actual, expected):
                        break

            if not phone_values_equivalent(actual, expected):
                safe_diagnostics = {
                    "surface_before": surface_before,
                    "surface_after": await _phone_surface_diagnostics(element),
                    "attempts": attempt_diagnostics,
                    "expected_digit_count": len(_digits(expected)),
                    "final_digit_count": len(_digits(actual)),
                    "equivalent": False,
                }
                for item in matching_reviews:
                    item.setdefault("details", {})["phone_surface_diagnostics"] = (
                        safe_diagnostics
                    )
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
                    "keyboard_significant_digits" if keyboard_retry else "significant_digits"
                ),
                "actual_digit_count": len(_digits(actual)),
                "expected_digit_count": len(_digits(expected)),
                "counted": not already_verified,
                "verified": True,
            })
            if not already_verified:
                reconciled += 1
        except Exception as exc:
            log.append({
                "action": "phone_reconciliation_skipped",
                "descriptor": descriptor[:200],
                "error_type": type(exc).__name__,
                "error": str(exc)[:200],
            })
    return reconciled


def install_greenhouse_phone_widget_compat() -> None:
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
        displayed: str, option: OptionRecord,
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
