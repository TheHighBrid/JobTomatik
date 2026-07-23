import pytest

from app.services.form_filler import _navigate_job_board_listing


class FakeAnchor:
    def __init__(self, href, text):
        self.href = href
        self.text = text

    async def get_attribute(self, name):
        return self.href if name == "href" else None

    async def inner_text(self):
        return self.text


class FakeControl:
    def __init__(self, page=None, target_url=None):
        self.page = page
        self.target_url = target_url
        self.clicked = False

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def click(self, timeout=None):
        self.clicked = True
        if self.page is not None and self.target_url:
            self.page.url = self.target_url


class FakePage:
    def __init__(
        self,
        url,
        anchors=None,
        body="",
        control=None,
        control_selector=None,
    ):
        self.url = url
        self.anchors = anchors or []
        self.body = body
        self.control = control
        self.control_selector = control_selector
        self.navigated_to = None

    async def query_selector(self, selector):
        if not self.control:
            return None
        if self.control_selector is None or selector == self.control_selector:
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
    page = FakePage(
        "https://www.jobbank.gc.ca/jobsearch/jobposting/49851398?source=searchresults",
        anchors=[FakeAnchor("https://company.example/careers/apply/123", "Apply on company site")],
        control_selector='button:has-text("Show how to apply")',
    )
    control = FakeControl(page)
    page.control = control
    log = []

    result = await _navigate_job_board_listing(page, log)

    assert control.clicked is True
    assert page.navigated_to == "https://company.example/careers/apply/123"
    assert result == {"application_url": "https://company.example/careers/apply/123"}
    assert [entry["action"] for entry in log] == [
        "listing_page_detected",
        "apply_control_clicked",
        "external_apply_link_found",
        "external_apply_navigated",
    ]


@pytest.mark.asyncio
async def test_navigate_jobbank_listing_returns_manual_review_for_email_apply():
    page = FakePage(
        "https://www.jobbank.gc.ca/jobsearch/jobposting/49734098?source=searchresults",
        body="Please send your resume to hiring@example.com.",
    )
    log = []

    result = await _navigate_job_board_listing(page, log)

    assert result["manual_review_only"] is True
    assert result["contact_email"] == "hiring@example.com"
    assert "email" in result["reason"].lower()
    assert log[-1]["action"] == "email_apply_detected"


@pytest.mark.asyncio
async def test_navigate_regional_linkedin_listing_follows_employer_apply_link():
    employer_url = (
        "https://jobs.rbc.com/ca/en/hvhapply?"
        "jobSeqNo=RBCAA0088R0000171559EXTERNALENCA&utm_source=LinkedIn"
    )
    page = FakePage(
        "https://ca.linkedin.com/jobs/view/bilingual-fraud-advisor-at-rbc-4439524897/",
        anchors=[FakeAnchor(employer_url, "Apply")],
    )
    log = []

    result = await _navigate_job_board_listing(page, log)

    assert page.navigated_to == employer_url
    assert result == {"application_url": employer_url}
    assert [entry["action"] for entry in log] == [
        "listing_page_detected",
        "external_apply_link_found",
        "external_apply_navigated",
    ]


@pytest.mark.asyncio
async def test_navigate_linkedin_apply_control_detects_direct_redirect():
    employer_url = (
        "https://jobs.rbc.com/ca/en/hvhapply?"
        "jobSeqNo=RBCAA0088R0000171559EXTERNALENCA&utm_source=LinkedIn"
    )
    page = FakePage(
        "https://ca.linkedin.com/jobs/view/bilingual-fraud-advisor-at-rbc-4439524897/",
        control_selector="#jobs-apply-button-id",
    )
    control = FakeControl(page, employer_url)
    page.control = control
    log = []

    result = await _navigate_job_board_listing(page, log)

    assert control.clicked is True
    assert page.url == employer_url
    assert result == {"application_url": employer_url}
    assert [entry["action"] for entry in log] == [
        "listing_page_detected",
        "apply_control_clicked",
        "external_apply_control_navigated",
    ]


@pytest.mark.asyncio
async def test_linkedin_listing_without_employer_target_fails_closed():
    linkedin_url = "https://ca.linkedin.com/jobs/view/example-role-123/"
    page = FakePage(linkedin_url, body="Job details without an outbound apply destination")
    log = []

    result = await _navigate_job_board_listing(page, log)

    assert result["manual_review_only"] is True
    assert result["application_url"] == linkedin_url
    assert "no outbound employer" in result["reason"].lower()
    assert log[-1]["action"] == "apply_target_not_found"
