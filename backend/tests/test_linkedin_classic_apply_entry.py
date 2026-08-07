from __future__ import annotations

import pytest

from app.services.application_entry import open_application_entry


class _Context:
    def __init__(self, page):
        self.pages = [page]


class _ApplyAnchor:
    def __init__(self, page):
        self.page = page
        self.clicks = 0

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def get_attribute(self, name):
        if name == "href":
            return "https://www.affirm.com/careers/senior-machine-learning-engineer-fraud/apply"
        return None

    async def inner_text(self):
        return "Apply"

    async def click(self, timeout=None):
        self.clicks += 1
        self.page.url = "https://www.affirm.com/careers/senior-machine-learning-engineer-fraud/apply"


class _ClassicLinkedInPage:
    def __init__(self):
        self.url = "https://www.linkedin.com/jobs/view/senior-machine-learning-engineer-fraud-at-affirm-4442675569"
        self.frames = []
        self.main_frame = self
        self.context = _Context(self)
        self.apply_anchor = _ApplyAnchor(self)

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
        if selector in {
            'a:text-is("Apply")',
            "a",
        }:
            return [self.apply_anchor]
        return []

    async def wait_for_timeout(self, _milliseconds):
        return None

    async def goto(self, url, **_kwargs):
        self.url = url

    async def wait_for_load_state(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_classic_linkedin_plain_apply_anchor_is_clicked_automatically():
    page = _ClassicLinkedInPage()
    log = []

    result = await open_application_entry(
        page,
        log,
        max_clicks=1,
        settle_timeout_seconds=0.5,
    )

    assert page.apply_anchor.clicks == 1
    assert result["application_url"].startswith("https://www.affirm.com/careers/")
    assert any(item["action"] == "application_entry_apply_click_started" for item in log)
    assert any(item["action"] == "application_entry_resolved" for item in log)
