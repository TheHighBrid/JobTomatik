from __future__ import annotations

import pytest

from app.services.application_entry import open_application_entry


class _Context:
    def __init__(self, page):
        self.pages = [page]


class _ApplyControl:
    def __init__(self, page, *, href: str = ""):
        self.page = page
        self.href = href
        self.clicks = 0

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def get_attribute(self, name):
        if name == "href":
            return self.href
        return None

    async def inner_text(self):
        return "Apply"

    async def click(self, timeout=None):
        self.clicks += 1
        if self.href:
            self.page.url = self.href


class _BasePage:
    def __init__(self, url: str, control: _ApplyControl | None = None):
        self.url = url
        self.frames = []
        self.main_frame = self
        self.context = _Context(self)
        self.control = control

    async def evaluate(self, _script):
        return {
            "visibleControls": 0,
            "applicantControls": 0,
            "uploadControls": 0,
            "emailControls": 0,
            "submitControls": 0,
            "url": self.url,
        }

    async def query_selector_all(self, selector):
        if self.control and selector in {
            'a:text-is("Apply")',
            'button:text-is("Apply")',
            "a",
            "button",
        }:
            return [self.control]
        return []

    async def wait_for_timeout(self, _milliseconds):
        return None

    async def goto(self, url, **_kwargs):
        self.url = url

    async def wait_for_load_state(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_classic_linkedin_plain_apply_anchor_is_clicked_automatically():
    page = _BasePage(
        "https://www.linkedin.com/jobs/view/senior-machine-learning-engineer-fraud-at-affirm-4442675569"
    )
    page.control = _ApplyControl(
        page,
        href="https://www.affirm.com/careers/senior-machine-learning-engineer-fraud/apply",
    )
    log = []

    result = await open_application_entry(
        page,
        log,
        max_clicks=1,
        settle_timeout_seconds=0.5,
    )

    assert page.control.clicks == 1
    assert result["application_url"].startswith("https://www.affirm.com/careers/")
    assert any(item["action"] == "application_entry_apply_click_started" for item in log)
    assert any(item["action"] == "application_entry_resolved" for item in log)


@pytest.mark.asyncio
async def test_plain_apply_button_on_external_ats_is_never_treated_as_doorway():
    page = _BasePage("https://careers.example.com/jobs/123/application")
    page.control = _ApplyControl(page)
    log = []

    result = await open_application_entry(
        page,
        log,
        max_clicks=1,
        settle_timeout_seconds=0.5,
    )

    assert result == {}
    assert page.control.clicks == 0
    assert any(item["action"] == "application_entry_apply_control_not_found" for item in log)
