import pytest

from app.services.browser_navigation import (
    navigate_job_board_listing,
    wait_for_external_application_target,
)


class FakeAnchor:
    def __init__(self, href, text):
        self.href = href
        self.text = text

    async def get_attribute(self, name):
        return self.href if name == "href" else None

    async def inner_text(self):
        return self.text


class FakeControl:
    def __init__(self, on_click=None):
        self.clicked = False
        self.on_click = on_click

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def click(self, timeout=None):
        self.clicked = True
        if self.on_click:
            self.on_click()


class FakeContext:
    def __init__(self):
        self.pages = []


class FakePage:
    def __init__(self, url, anchors=None, body="", control=None, context=None):
        self.url = url
        self.anchors = anchors or []
        self.body = body
        self.control = control
        self.navigated_to = None
        self.context = context or FakeContext()
        if self not in self.context.pages:
            self.context.pages.append(self)

    async def query_selector(self, selector):
        if not self.control:
            return None
        if "jobs-apply-button" in selector or "Show how to apply" in selector:
            return self.control
        return None

    async def wait_for_load_state(self, state, timeout=None):
        return None

    async def wait_for_timeout(self, timeout):
        return None

    async def query_selector_all(self, selector):
        return self.anchors if selector == "a[href]" else []

    async def goto(self, target, wait_until=None, timeout=None):
        self.navigated_to = target
        self.url = target

    async def inner_text(self, selector):
        return self.body


@pytest.mark.asyncio
async def test_navigate_jobbank_listing_reveals_and_follows_external_apply_link():
    control = FakeControl()
    page = FakePage(
        "https://www.jobbank.gc.ca/jobsearch/jobposting/49851398?source=searchresults",
        anchors=[FakeAnchor("https://company.example/careers/apply/123", "Apply on company site")],
        control=control,
    )
    log = []

    result = await navigate_job_board_listing(page, log)

    assert control.clicked is True
    assert page.navigated_to == "https://company.example/careers/apply/123"
    assert result["application_url"] == "https://company.example/careers/apply/123"
    assert result["resolution_method"] == "anchor_href"
    assert [entry["action"] for entry in log] == [
        "listing_page_detected",
        "apply_control_clicked",
        "external_apply_link_found",
        "external_apply_navigated",
    ]


@pytest.mark.asyncio
async def test_navigate_linkedin_listing_detects_external_popup_target():
    context = FakeContext()
    source = "https://ca.linkedin.com/jobs/view/bilingual-fraud-advisor-4439524897"
    page = FakePage(source, context=context)

    def open_employer_page():
        FakePage("https://jobs.rbc.com/ca/en/job/123", context=context)

    page.control = FakeControl(on_click=open_employer_page)
    log = []

    result = await navigate_job_board_listing(page, log)

    assert page.control.clicked is True
    assert result["application_url"] == "https://jobs.rbc.com/ca/en/job/123"
    assert result["resolution_method"] == "apply_control"
    assert any(item["action"] == "external_application_target_observed" for item in log)


@pytest.mark.asyncio
async def test_wait_for_external_target_accepts_human_opened_employer_tab():
    context = FakeContext()
    source = "https://ca.linkedin.com/jobs/view/bilingual-fraud-advisor-4439524897"
    page = FakePage(source, context=context)
    FakePage("https://jobs.rbc.com/ca/en/job/123", context=context)
    log = []

    target = await wait_for_external_application_target(
        page,
        source,
        timeout_seconds=1,
        log=log,
    )

    assert target == "https://jobs.rbc.com/ca/en/job/123"
    assert log[-1]["action"] == "application_target_human_window_completed"


@pytest.mark.asyncio
async def test_navigate_jobbank_listing_returns_manual_review_for_email_apply():
    page = FakePage(
        "https://www.jobbank.gc.ca/jobsearch/jobposting/49734098?source=searchresults",
        body="Please send your resume to hiring@example.com.",
    )
    log = []

    result = await navigate_job_board_listing(page, log)

    assert result["manual_review_only"] is True
    assert result["contact_email"] == "hiring@example.com"
    assert "email" in result["reason"].lower()
    assert log[-1]["action"] == "email_apply_detected"