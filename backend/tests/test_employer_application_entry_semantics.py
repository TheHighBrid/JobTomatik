from __future__ import annotations

import pytest

from app.services.ats_base import action_text
from app.services.employer_application_entry import (
    _click_safe_candidate,
    _rank_safe_candidates,
    _safe_candidate,
)


class _Element:
    def __init__(
        self,
        *,
        aria_label: str | None = None,
        inner_text: str = "Apply",
        clean_text: str = "Apply",
        control_type: str = "button",
        inside_form: bool = False,
        normal_click_fails: bool = False,
    ):
        self.attrs = {
            "aria-label": aria_label,
            "value": None,
            "title": None,
            "href": None,
            "type": control_type,
        }
        self._inner_text = inner_text
        self._clean_text = clean_text
        self._inside_form = inside_form
        self.normal_click_fails = normal_click_fails
        self.normal_clicks = 0
        self.forced_clicks = 0

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def get_attribute(self, name):
        return self.attrs.get(name)

    async def inner_text(self):
        return self._inner_text

    async def evaluate(self, expression):
        if "closest('form')" in expression:
            return self._inside_form
        return self._clean_text

    async def scroll_into_view_if_needed(self, *, timeout=None):
        return None

    async def click(self, *, timeout=None, force=False):
        if force:
            self.forced_clicks += 1
            return None
        self.normal_clicks += 1
        if self.normal_click_fails:
            raise RuntimeError("pointer actionability timeout")
        return None


class _Locator:
    def __init__(self, elements):
        self.elements = list(elements)

    async def count(self):
        return len(self.elements)

    def nth(self, index):
        return self.elements[index]


class _FallbackOnlyPage:
    def __init__(self, element):
        self.element = element

    def locator(self, selector):
        # Model a component library where :text-is selectors bind no actionable
        # outer element but a bounded semantic scan of buttons can find it.
        if selector == "button":
            return _Locator([self.element])
        return _Locator([])


@pytest.mark.asyncio
async def test_duplicate_aria_and_inner_text_still_yield_exact_apply_label():
    element = _Element(aria_label="Apply", inner_text="Apply")

    # This is the regression shape that the old implementation rejected.
    assert await action_text(element) == "apply apply"

    candidate = await _safe_candidate(element)
    assert candidate is not None
    assert candidate["label"] == "apply"


@pytest.mark.asyncio
async def test_decorative_icon_text_is_removed_for_strict_apply_semantics():
    element = _Element(
        inner_text="Apply arrow_forward",
        clean_text="Apply",
    )

    candidate = await _safe_candidate(element)
    assert candidate is not None
    assert candidate["label"] == "apply"


@pytest.mark.asyncio
async def test_bounded_fallback_finds_componentized_apply_button():
    element = _Element(inner_text="Apply arrow_forward", clean_text="Apply")
    candidates = await _rank_safe_candidates(_FallbackOnlyPage(element))

    assert len(candidates) == 1
    assert candidates[0][1]["label"] == "apply"


@pytest.mark.asyncio
async def test_verified_apply_retries_with_force_after_pointer_actionability_timeout():
    element = _Element(normal_click_fails=True)
    page = _FallbackOnlyPage(element)
    descriptor = await _safe_candidate(element)
    assert descriptor is not None
    log = []

    clicked = await _click_safe_candidate(
        page,
        element,
        descriptor,
        step=1,
        log=log,
    )

    assert clicked is True
    assert element.normal_clicks == 1
    assert element.forced_clicks == 1
    assert any(
        item.get("action") == "intermediate_employer_apply_force_clicked"
        for item in log
    )


@pytest.mark.asyncio
async def test_submit_apply_inside_form_remains_blocked():
    element = _Element(
        aria_label="Apply",
        control_type="submit",
        inside_form=True,
        normal_click_fails=True,
    )

    assert await _safe_candidate(element) is None
