from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest

from app.models.application import ManualReviewReason
from app.services.application_entry import apply_candidate_score, open_application_entry
from app.services.application_target import is_valid_application_target
from app.services.application_target_resolver import resolve_application_target_with_browser
from app.services.browser_navigation import classify_challenge_context
from app.services.form_filler_handoff import fill_and_submit_application_with_handoff
from app.services.handoff_session import HandoffSessionError, challenge_type_for_review


class _FakeContext:
    def __init__(self, page):
        self.pages = [page]


class _FakeApplyControl:
    def __init__(self, page):
        self.page = page
        self.clicks = 0

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def get_attribute(self, name):
        if name == "href":
            return ""
        if name == "aria-label":
            return "Apply now"
        return None

    async def inner_text(self):
        return "Apply now"

    async def click(self, timeout=None):
        self.clicks += 1
        self.page.form_open = True


class _FakePage:
    def __init__(self):
        self.url = "https://www.linkedin.com/jobs/view/123"
        self.form_open = False
        self.context = _FakeContext(self)
        self.frames = []
        self.main_frame = self
        self.control = _FakeApplyControl(self)

    async def evaluate(self, _script):
        return {
            "visibleControls": 6 if self.form_open else 0,
            "applicantControls": 4 if self.form_open else 0,
            "uploadControls": 1 if self.form_open else 0,
            "emailControls": 1 if self.form_open else 0,
            "submitControls": 1 if self.form_open else 0,
            "url": self.url,
        }

    async def query_selector_all(self, selector):
        if "apply" in selector.lower() or "jobs-apply-button" in selector.lower():
            return [self.control]
        return []

    async def wait_for_timeout(self, _milliseconds):
        return None

    async def goto(self, url, **_kwargs):
        self.url = url

    async def wait_for_load_state(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_apply_doorway_is_clicked_before_form_handoff():
    page = _FakePage()
    log = []

    result = await open_application_entry(
        page,
        log,
        max_clicks=1,
        settle_timeout_seconds=0.5,
    )

    assert page.control.clicks == 1
    assert result["application_form_detected"] is True
    assert result["resolution_method"] == "apply_control_same_page_form"
    assert any(item["action"] == "application_entry_resolved" for item in log)


def test_apply_candidate_scoring_never_treats_final_submit_as_doorway():
    assert apply_candidate_score("Apply now") > 100
    assert apply_candidate_score("Start application") > 80
    assert apply_candidate_score("Submit application") == -1
    assert apply_candidate_score("Apply filters") == -1
    assert apply_candidate_score("View applications") == -1


def test_passive_captcha_footer_copy_does_not_trigger_handoff():
    context = {
        "title": "Fraud Analyst",
        "headings": ["Fraud Analyst", "About the role"],
        "alerts": [],
        "dialogs": [],
        "mainText": (
            "Apply for this role. This site is protected by reCAPTCHA and the Google "
            "Privacy Policy applies."
        ),
        "visibleControlCount": 12,
        "applicantControlCount": 5,
    }

    assert classify_challenge_context(context) is None


def test_active_human_verification_heading_triggers_captcha_boundary():
    context = {
        "title": "Verify you are human",
        "headings": ["Verify you are human"],
        "alerts": [],
        "dialogs": [],
        "mainText": "Complete the CAPTCHA to continue.",
        "visibleControlCount": 1,
        "applicantControlCount": 0,
    }

    challenge = classify_challenge_context(context)
    assert challenge is not None
    assert challenge["reason_code"] == "captcha_detected"


def test_verified_same_page_application_form_is_a_valid_target():
    source = "https://www.linkedin.com/jobs/view/123"
    assert not is_valid_application_target(source, source)
    assert is_valid_application_target(
        source,
        source,
        application_form_detected=True,
    )


def test_target_resolver_never_requests_a_manual_apply_click():
    source = inspect.getsource(resolve_application_target_with_browser)

    assert "wait_for_external_application_target" not in source
    assert "application_target_required" not in source
    assert "application_target_security_handoff_retained" in source


@pytest.mark.parametrize(
    "browser_flow",
    [resolve_application_target_with_browser, fill_and_submit_application_with_handoff],
)
def test_controlled_page_release_occurs_inside_playwright_lifetime(browser_flow):
    """Keep page cleanup ahead of ``async_playwright().__aexit__``."""
    tree = ast.parse(inspect.getsource(browser_flow))
    playwright_blocks = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncWith)
        and any("async_playwright" in ast.unparse(item.context_expr) for item in node.items)
    ]

    assert len(playwright_blocks) == 1
    release_calls = [
        node
        for node in ast.walk(playwright_blocks[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "release_application_browser"
    ]
    assert len(release_calls) == 1


def test_navigation_only_review_cannot_issue_a_retained_browser_handoff():
    review = SimpleNamespace(
        reason_code=ManualReviewReason.application_target_required.value,
    )

    with pytest.raises(HandoffSessionError, match="not resumable"):
        challenge_type_for_review(review)
