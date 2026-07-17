"""Fail-closed support for delayed Greenhouse location autocomplete controls."""

from __future__ import annotations

from typing import Any

from app.services import control_aria
from app.services.control_engine import element_descriptor
from app.services.control_primitives import normalize_text


_INSTALLED = False
_ORIGINAL_TYPE_SEARCH_ANSWER = None


def _is_location_descriptor(descriptor: str) -> bool:
    normalized = normalize_text(descriptor)
    return any(
        phrase in normalized
        for phrase in (
            "location city",
            "candidate location",
            "where are you located",
            "where are you based",
        )
    )


async def _options_available(page: Any, combobox: Any) -> bool:
    try:
        _, _, options = await control_aria._combobox_options(page, combobox)
        return bool(options)
    except Exception:
        return False


async def _type_location_with_keyboard(page: Any, combobox: Any, answer: str) -> None:
    tag = await combobox.evaluate("(el) => el.tagName.toLowerCase()")
    await combobox.evaluate("(el) => el.focus()")
    if tag in {"input", "textarea"}:
        await combobox.fill("")
    else:
        await combobox.press("Control+A")
    await combobox.type(answer, delay=25)


async def wait_for_location_options(
    page: Any,
    combobox: Any,
    answer: str,
    *,
    attempts: int = 12,
    delay_ms: int = 250,
) -> bool:
    """Wait for a real option list after keyboard input, never synthesize an option."""
    if await _options_available(page, combobox):
        return True

    try:
        await _type_location_with_keyboard(page, combobox, answer)
    except Exception:
        return False

    for _ in range(attempts):
        await page.wait_for_timeout(delay_ms)
        if await _options_available(page, combobox):
            return True
    return False


def install_greenhouse_location_widget_compat() -> None:
    """Install an idempotent delayed-option retry for location comboboxes."""
    global _INSTALLED, _ORIGINAL_TYPE_SEARCH_ANSWER
    if _INSTALLED:
        return

    _ORIGINAL_TYPE_SEARCH_ANSWER = control_aria._type_search_answer

    async def type_search_answer_with_location_retry(
        page: Any,
        combobox: Any,
        answer: str,
    ) -> bool:
        attempted = await _ORIGINAL_TYPE_SEARCH_ANSWER(page, combobox, answer)
        if not attempted:
            return False
        if await _options_available(page, combobox):
            return True

        try:
            descriptor = await element_descriptor(page, combobox)
        except Exception:
            descriptor = ""
        if not _is_location_descriptor(descriptor):
            return True

        await wait_for_location_options(page, combobox, answer)
        # Returning true means a search was attempted. The control engine still
        # re-collects options and rejects the control when no real option exists.
        return True

    control_aria._type_search_answer = type_search_answer_with_location_retry
    _INSTALLED = True


__all__ = [
    "install_greenhouse_location_widget_compat",
    "wait_for_location_options",
]
