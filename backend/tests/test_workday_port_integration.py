import os

import pytest
import pytest_asyncio

from app.services.ats_registry import detect_ats_adapter
from app.services.ats_workday import WorkdayAdapter, parse_workday_target
from app.services.browser_navigation import detect_blocking_challenge
from app.services.workday_port_integration import (
    workday_cxs_full_job_url,
    workday_public_apply_url,
)


WORKDAY_URL = (
    "https://workday.wd5.myworkdayjobs.com/en-US/Workday/job/"
    "Australia-VIC-Melbourne/Principal-Enterprise-Architect_JR-0108745"
)


@pytest_asyncio.fixture
async def browser_page():
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    browser = None
    context = None
    try:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception as exc:
            if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
                pytest.fail(f"Chromium is required for Workday port certification: {exc}")
            pytest.skip("Chromium is not installed in this environment")
        context = await browser.new_context()
        page = await context.new_page()
        yield page
    finally:
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()
        await playwright.stop()


def test_workday_cxs_metadata_uses_complete_external_path():
    target = parse_workday_target(WORKDAY_URL)
    assert target is not None
    assert workday_cxs_full_job_url(target) == (
        "https://workday.wd5.myworkdayjobs.com/wday/cxs/workday/Workday/job/"
        "Australia-VIC-Melbourne/Principal-Enterprise-Architect_JR-0108745"
    )
    assert workday_public_apply_url(target) == f"{WORKDAY_URL}/apply"


@pytest.mark.asyncio
async def test_workday_apply_popup_is_retained_as_manual_login_boundary(browser_page):
    await browser_page.set_content(
        """
        <a id="apply">Apply</a>
        <script>
          document.querySelector('#apply').onclick = () => {
            const popup = window.open('about:blank', '_blank');
            popup.document.write(`
              <main>
                <button data-automation-id="bottom-navigation-next-button">Continue</button>
                <label for="password">Password</label>
                <input id="password" type="password" data-automation-id="password">
              </main>
            `);
            popup.document.close();
          };
        </script>
        """
    )

    adapter = WorkdayAdapter()
    log = []
    await adapter.prepare(browser_page, log)
    surface = await adapter.resolve_surface(browser_page)

    assert surface is not browser_page
    assert any(item.get("action") == "workday_application_popup_captured" for item in log)

    boundary = await detect_blocking_challenge(browser_page)
    assert boundary is not None
    assert boundary["reason_code"] == "login_required"
    assert boundary["details"]["context_page_count"] == 2
    assert boundary["details"]["credentials_entered"] is False
    assert boundary["details"]["account_created"] is False
    assert boundary["details"]["bypass_attempted"] is False

    detected = await detect_ats_adapter(browser_page, WORKDAY_URL)
    assert detected.name == "workday"


@pytest.mark.asyncio
async def test_workday_noop_apply_uses_one_same_origin_public_route(browser_page):
    async def route_handler(route):
        if route.request.url.endswith("/apply"):
            await route.fulfill(
                status=200,
                content_type="text/html",
                body="""
                  <main>
                    <label for="password">Password</label>
                    <input id="password" type="password" data-automation-id="password">
                  </main>
                """,
            )
            return
        await route.fulfill(
            status=200,
            content_type="text/html",
            body="""
              <main>
                <h1>Principal Enterprise Architect</h1>
                <div role="dialog">Cookie settings</div>
                <a id="apply">Apply</a>
                <script>
                  document.querySelector('#apply').onclick = (event) => {
                    event.preventDefault();
                  };
                </script>
              </main>
            """,
        )

    await browser_page.route("**/*", route_handler)
    await browser_page.goto(WORKDAY_URL)

    adapter = WorkdayAdapter()
    log = []
    await adapter.prepare(browser_page, log)

    assert browser_page.url == f"{WORKDAY_URL}/apply"
    fallback = next(
        item for item in log if item.get("action") == "workday_public_apply_route_fallback"
    )
    assert fallback["same_origin"] is True
    assert fallback["credentials_entered"] is False
    assert fallback["account_created"] is False
    assert fallback["bypass_attempted"] is False

    boundary = await detect_blocking_challenge(browser_page)
    assert boundary is not None
    assert boundary["reason_code"] == "login_required"
