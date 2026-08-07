from __future__ import annotations

import pytest

from app.services.application_entry import open_application_entry


class _Context:
    def __init__(self, page):
        self.pages = [page]


class _ApplyControl:
    def __init__(self, page, *, href: str = "", text: str = "Apply"):
        self.page = page
        self.href = href
        self.text = text
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
        return self.text

    async def click(self, timeout=None):
        self.clicks += 1
        if self.href:
            self.page.url = self.href


class _Locator:
    def __init__(self, elements):
        self.elements = list(elements)

    async def count(self):
        return len(self.elements)

    def nth(self, index):
        return self.elements[index]


class _BasePage:
    def __init__(self, url: str, *, locator_mode: bool = False):
        self.url = url
        self.frames = []
        self.main_frame = self
        self.context = _Context(self)
        self.control = None
        self.locator_mode = locator_mode
        self.goto_calls = []

    async def evaluate(self, _script):
        return {
            "visibleControls": 0,
            "applicantControls": 0,
            "uploadControls": 0,
            "emailControls": 0,
            "submitControls": 0,
            "url": self.url,
        }

    def locator(self, selector):
        if not self.locator_mode:
            raise AttributeError("locator unavailable")
        matching = {
            'a:text-is("Apply")',
            'button:text-is("Apply")',
            '[role="button"]:text-is("Apply")',
            "a",
            "button",
            '[role="button"]',
        }
        return _Locator([self.control] if self.control and selector in matching else [])

    async def query_selector_all(self, selector):
        matching = {
            'a:text-is("Apply")',
            'button:text-is("Apply")',
            "a",
            "button",
        }
        if self.control and selector in matching:
            return [self.control]
        return []

    async def wait_for_timeout(self, _milliseconds):
        return None

    async def goto(self, url, **_kwargs):
        self.goto_calls.append(url)
        self.url = url

    async def wait_for_load_state(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_classic_linkedin_plain_apply_anchor_is_followed_automatically():
    page = _BasePage(
        "https://www.linkedin.com/jobs/view/senior-machine-learning-engineer-fraud-at-affirm-4442675569",
        locator_mode=True,
    )
    page.control = _ApplyControl(
        page,
        href="https://job-boards.greenhouse.io/affirm/jobs/7806920003",
    )
    log = []

    result = await open_application_entry(
        page,
        log,
        max_clicks=1,
        settle_timeout_seconds=0.5,
    )

    # A proven external href is followed directly so LinkedIn popup/rerender behavior
    # cannot swallow the Apply action.
    assert page.control.clicks == 0
    assert page.goto_calls == ["https://job-boards.greenhouse.io/affirm/jobs/7806920003"]
    assert result["application_url"] == "https://job-boards.greenhouse.io/affirm/jobs/7806920003"
    assert any(item["action"] == "application_entry_external_href_navigated" for item in log)


@pytest.mark.asyncio
async def test_linkedin_redirect_href_is_unwrapped_before_navigation():
    page = _BasePage(
        "https://www.linkedin.com/jobs/view/4442675569",
        locator_mode=True,
    )
    page.control = _ApplyControl(
        page,
        href=(
            "https://www.linkedin.com/redir/redirect?url="
            "https%3A%2F%2Fjob-boards.greenhouse.io%2Faffirm%2Fjobs%2F7806920003"
        ),
    )
    log = []

    result = await open_application_entry(page, log, max_clicks=1, settle_timeout_seconds=0.5)

    assert page.goto_calls == ["https://job-boards.greenhouse.io/affirm/jobs/7806920003"]
    assert result["application_url"] == "https://job-boards.greenhouse.io/affirm/jobs/7806920003"


@pytest.mark.asyncio
async def test_plain_apply_button_on_external_ats_is_never_treated_as_doorway():
    page = _BasePage("https://careers.example.com/jobs/123/application", locator_mode=True)
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
    assert page.goto_calls == []
    assert any(item["action"] == "application_entry_apply_control_not_found" for item in log)
