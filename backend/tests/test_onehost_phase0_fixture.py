"""Phase 0 proof on the locked path.

Uses form_filler_v2.chromium.launch arguments and _fill_fields against the
Greenhouse HTML already embedded in test_greenhouse_adapter.py. No employer
site, submit, ADB, or new browser abstraction.
"""

import os
from pathlib import Path

import pytest
import pytest_asyncio

from app.services.form_filler_v2 import _fill_fields

ADAPTER_TEST = Path(__file__).parent / "test_greenhouse_adapter.py"
LAUNCH_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]


def greenhouse_fixture_html() -> str:
    text = ADAPTER_TEST.read_text()
    start = text.index('<form id="application_form"')
    end = text.index("</script>", start) + len("</script>")
    return text[start:end]


@pytest_asyncio.fixture
async def owned_browser():
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    launch_kwargs = {"headless": True, "args": LAUNCH_ARGS}
    executable = os.getenv("JOBTOMATIK_CHROMIUM")
    if executable:
        launch_kwargs["executable_path"] = executable
    try:
        browser = await playwright.chromium.launch(**launch_kwargs)
    except Exception as exc:
        await playwright.stop()
        if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(f"Chromium is required for the OneHost phase 0 proof: {exc}")
        pytest.skip(f"Chromium is not installed in this environment: {exc}")
    try:
        yield browser
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_onehost_phase0_form_filler_v2_fills_existing_greenhouse_fixture(owned_browser, tmp_path):
    assert owned_browser.browser_type.name == "chromium"
    html = greenhouse_fixture_html()
    assert "boards.greenhouse.io/acme/jobs/123" in html

    context = await owned_browser.new_context()
    trace_path = tmp_path / "onehost-phase0-trace.zip"
    evidence_path = tmp_path / "onehost-phase0-evidence.json"
    await context.tracing.start(screenshots=True, snapshots=True)
    page = await context.new_page()
    await page.set_content(html)
    log = []
    outcome = await _fill_fields(
        page,
        {"full_name": "Phase Zero", "email": "phase0@example.test"},
        "",
        "",
        log,
    )

    assert await page.locator("#first").input_value() == "Phase"
    assert await page.locator("#last").input_value() == "Zero"
    assert await page.locator("#email").input_value() == "phase0@example.test"
    assert outcome["filled_count"] >= 3
    assert not any(item.get("action") == "submit_click" for item in log)

    await context.tracing.stop(path=str(trace_path))
    evidence_path.write_text(
        '{"fields_filled": %s, "submit_clicked": false}\n' % outcome["filled_count"],
        encoding="utf-8",
    )
    await context.close()

    assert trace_path.is_file() and trace_path.stat().st_size > 100
    assert evidence_path.is_file()
