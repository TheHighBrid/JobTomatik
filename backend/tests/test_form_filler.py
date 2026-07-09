import pytest

from app.services.form_filler import _navigate_job_board_listing, _select_answer_hint


class FakeAnchor:
    def __init__(self, href, text):
        self.href = href
        self.text = text
        self.clicked = False

    async def get_attribute(self, name):
        return self.href if name == "href" else None

    async def inner_text(self):
        return self.text

    async def click(self, timeout=None):
        self.clicked = True


class FakeControl:
    def __init__(self):
        self.clicked = False

    async def click(self, timeout=None):
        self.clicked = True


class FakePage:
    def __init__(self, url, anchors=None, body="", control=None):
        self.url = url
        self.anchors = anchors or []
        self.body = body
        self.control = control
        self.navigated_to = None

    async def query_selector(self, selector):
        return self.control if self.control and "Show how to apply" in selector else None

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

    result = await _navigate_job_board_listing(page, log)

    assert control.clicked is True
    assert page.navigated_to == "https://company.example/careers/apply/123"
    assert result == {"application_url": "https://company.example/careers/apply/123"}
    actions = [entry["action"] for entry in log]
    assert "listing_page_detected" in actions
    assert "apply_instructions_revealed" in actions
    assert "external_apply_link_found" in actions
    assert "external_apply_navigated" in actions


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


def test_select_answer_hint_maps_common_screening_questions():
    assert _select_answer_hint("Are you legally authorized to work in Canada?") == "yes"
    assert _select_answer_hint("Will you require sponsorship now or in the future?") == "no"
    assert _select_answer_hint("Voluntary self ID gender") == "prefer not"
