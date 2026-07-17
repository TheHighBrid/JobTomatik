"""Exact-ID lookup for Greenhouse ARIA listboxes with CSS-special IDs.

Some Greenhouse React controls expose ``aria-controls`` values containing square
brackets. Passing those values through a CSS ID selector raises a DOMException.
This compatibility layer resolves the referenced element with
``document.getElementById`` and otherwise preserves the control engine's
fail-closed option collection behavior.
"""

from __future__ import annotations

from typing import Any

from app.services import control_aria
from app.services.control_primitives import OptionRecord, element_text, normalize_text


_INSTALLED = False


async def _exact_id_combobox_options(page: Any, combobox: Any):
    controls_id = (
        await combobox.get_attribute("aria-controls")
        or await combobox.get_attribute("aria-owns")
    )
    listbox = None
    if controls_id:
        try:
            handle = await page.evaluate_handle(
                "(id) => document.getElementById(id)",
                controls_id,
            )
            listbox = handle.as_element()
        except Exception:
            listbox = None

    if listbox is None:
        for candidate in await page.query_selector_all('[role="listbox"]'):
            try:
                if await candidate.is_visible():
                    listbox = candidate
                    break
            except Exception:
                continue

    handles = await listbox.query_selector_all('[role="option"]') if listbox else []
    options = []
    for index, option in enumerate(handles):
        label = await element_text(option) or await option.get_attribute("aria-label") or ""
        value = (
            await option.get_attribute("data-value")
            or await option.get_attribute("value")
            or label
        )
        options.append(OptionRecord(
            key=(
                await option.get_attribute("data-jt-control-id")
                or f"aria-option:{index}:{value}"
            ),
            label=label,
            value=value,
            disabled=normalize_text(
                await option.get_attribute("aria-disabled")
            ) == "true",
            selected=normalize_text(
                await option.get_attribute("aria-selected")
            ) == "true",
        ))
    return listbox, handles, options


def install_greenhouse_aria_id_compat() -> None:
    """Install exact DOM-ID lookup without changing matching or activation rules."""
    global _INSTALLED
    if _INSTALLED:
        return
    control_aria._combobox_options = _exact_id_combobox_options
    _INSTALLED = True


__all__ = ["install_greenhouse_aria_id_compat"]
