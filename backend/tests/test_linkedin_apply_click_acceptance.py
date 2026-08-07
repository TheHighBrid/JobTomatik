from __future__ import annotations

import os

import pytest
import pytest_asyncio

from app.services import application_target_resolver
from app.services.application_target_resolver import resolve_application_target_with_browser


LINKEDIN_URL = "https://www.linkedin.com/jobs/view/4442675569"
GREENHOUSE_URL = "https://job-boards.greenhouse.io/affirm/jobs/7806920003"

LINKEDIN_CLICK_ONLY_HTML = f"""
<!doctype html>
<html>
  <head><title>Senior Machine Learning Engineer (Fraud) | LinkedIn</title></head>
  <body>
    <div role="alert">Emails aren't getting through to one of your email addresses. Please update or confirm your email.</div>
    <main>
      <h1>Senior Machine Learning Engineer (Fraud)</h1>
      <div>Affirm · Ottawa, ON · Remote · Full-time</div>
      <button
        id="jobs-apply-button-id"
        class="jobs-apply-button"
        type="button"
        aria-label="Apply on company website"
      >Apply ↗</button>
      <script>
        document.querySelector('#jobs-apply-button-id').addEventListener('click', () => {{
          window.location.assign('{GREENHOUSE_URL}');
        }});
      </script>
    </main>
  </body>
</html>
"""

GREENHOUSE_HTML = """
<!doctype html>
<html>
  <head><title>Senior Machine Learning Engineer (Fraud) | Affirm</title></head>
  <body>
    <main>
      <h1>Senior Machine Learning Engineer (Fraud)</h1>
      <form id="application_form">
        <label for="first_name">First Name</label>
        <input id="first_name" name="first_name" type="text" required>
        <label for="last_name">Last Name</label>
        <input id="last_name" name="last_name" type="text" required>
        <label for="email">Email</label>
        <input id="email" name="email" type="email" required>
        <button id="submit_app" type="submit">Submit Application</button>
      </form>
    </main>
  </body>
</html>
"""


class _Runtime:
    def __init__(self, page):
        self.page = page
        self.capture_calls = 0

    async def capture_snapshot(self, *, metadata=None):
        self.capture_calls += 1
        raise AssertionError("Apply navigation must never create a handoff snapshot")

    def terminate(self, *, remove_profile=False):
        return None


@pytest_asyncio.fixture
async def click_only_page():
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:
        await playwright.stop()
        if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(f"Chromium is required for Apply-click certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")

    page = await browser.new_page()

    async def route_fixture(route):
        url = route.request.url
        if url.startswith(LINKEDIN_URL):
            await route.fulfill(
                status=200,
                content_type="text/html",
                body=LINKEDIN_CLICK_ONLY_HTML,
            )
            return
        if url.startswith(GREENHOUSE_URL):
            await route.fulfill(status=200, content_type="text/html", body=GREENHOUSE_HTML)
            return
        await route.abort()

    await page.route("**/*", route_fixture)
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_real_browser_click_only_apply_reaches_form_without_handoff(
    monkeypatch,
    click_only_page,
):
    runtime = _Runtime(click_only_page)

    async def use_test_runtime(_playwright, **_kwargs):
        return runtime

    monkeypatch.setattr(
        application_target_resolver,
        "launch_application_browser",
        use_test_runtime,
    )

    result = await resolve_application_target_with_browser(LINKEDIN_URL)

    assert result["success"] is True
    assert result["application_target_status"] == "resolved"
    assert result["application_target_url"] == GREENHOUSE_URL
    assert result["application_form_detected"] is True
    assert result["requires_manual_review"] is False
    assert result["handoff_snapshot"] is None
    assert runtime.capture_calls == 0
    assert click_only_page.url == GREENHOUSE_URL
    actions = [item.get("action") for item in result["log"]]
    assert "application_entry_apply_click_started" in actions
    assert "application_entry_resolved" in actions
    assert "application_target_security_handoff_retained" not in actions
