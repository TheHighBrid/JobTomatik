"""Real private-display/API integration using intercepted synthetic pages only."""
import json
import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from app.models.handoff import ManualHandoffSession
from app.services import browser_handoff, owner_browser_input
from app.services.browser_runtime import controlled_page_target_id
from app.services.browser_runtime_base import launch_retainable_browser
from app.services.handoff_session import encrypt_handoff_secret
from tests.conftest import TestingSessionLocal
from tests.test_operator_assisted_submission import (
    LEVER_URL, _prepare_application, _create_final_submit_boundary,
    _mock_metadata, _keep_automation_off, _authorize_and_claim,
)


pytestmark = pytest.mark.skipif(os.getenv("REQUIRE_OWNER_DISPLAY_TESTS") != "1", reason="Requires the private Xvfb owner display")

PARENT = """<!doctype html><title>Synthetic owner handoff</title>
<input id="answer" value="Verified synthetic candidate" style="display:block;margin:20px">
<iframe src="https://fixture.hcaptcha.com/owner-fixture" style="width:400px;height:170px;margin:20px;border:0"></iframe>
<button id="submit" type="button" style="display:block;margin:20px;height:50px" onclick="window.syntheticSubmits += 1">Submit Application</button>
<div style="height:1500px">Synthetic fixture. No employer network request is permitted.</div>
<script>window.syntheticSubmits=0; localStorage.setItem('owner-profile-proof','persistent');</script>"""
WIDGET = """<!doctype html><button style="width:300px;height:100px" onclick="document.body.dataset.ownerClicks = Number(document.body.dataset.ownerClicks || 0) + 1">Synthetic owner pointer target, not a CAPTCHA</button>"""


@pytest.mark.asyncio
async def test_owner_display_authenticated_handoff_and_once_only_submit(auth_client, tmp_path, monkeypatch):
    _mock_metadata(monkeypatch)
    _keep_automation_off(monkeypatch)
    monkeypatch.setattr("app.api.supervised_submissions.owner_handoff_capabilities", owner_browser_input.owner_handoff_capabilities)
    app_id = _prepare_application(auth_client, tmp_path)
    runtime = None
    observed_requests = []

    async def route_fixture(route):
        url = route.request.url
        observed_requests.append(url)
        if url == LEVER_URL:
            await route.fulfill(body=PARENT, content_type="text/html")
        elif url == "https://fixture.hcaptcha.com/owner-fixture":
            await route.fulfill(body=WIDGET, content_type="text/html")
        else:
            await route.abort()

    async def verified(_page, _session, **_kwargs):
        return {"verified": True, "blockers": []}

    # This fixture has no employer metadata endpoint. Browser identity, ownership,
    # lease checks and native coordinates use their real implementations.
    monkeypatch.setattr(browser_handoff, "_verify_session_target", verified)
    async with async_playwright() as playwright:
        try:
            runtime = await launch_retainable_browser(playwright, profile_dir=tmp_path / "profile", headless=False)
            page = runtime.page
            await page.route("**/*", route_fixture)
            await page.goto(LEVER_URL)
            await page.frame_locator("iframe").locator("button").wait_for()
            await runtime.context.tracing.start(screenshots=True, snapshots=True)
            public_id = _create_final_submit_boundary(app_id)
            with TestingSessionLocal() as db:
                session = db.query(ManualHandoffSession).filter_by(public_id=public_id).one()
                session.browser_process_id = runtime.process.pid
                session.browser_profile_path = runtime.browser_profile_path
                session.browser_node_id = runtime.browser_node_id
                session.encrypted_browser_endpoint = encrypt_handoff_secret(runtime.cdp_endpoint)
                session.handoff_metadata = {**session.handoff_metadata, "controlled_page_target_id": await controlled_page_target_id(page)}
                db.commit()

            reference, lease = _authorize_and_claim(auth_client, app_id, public_id)
            body = {"lease_token": lease}
            caps = auth_client.post(f"/api/handoffs/{public_id}/capabilities", json=body)
            assert caps.status_code == 200, caps.text
            assert caps.json()["owner_pointer_enabled"] is True
            assert caps.json()["manual_verification_required"] is True
            assert caps.json()["submit_action"] == "operator_native_submit"
            assert auth_client.post(f"/api/handoffs/{public_id}/frame", json=body).headers["content-type"] == "image/png"
            assert auth_client.post(f"/api/handoffs/{public_id}/capabilities", json={"lease_token": "wrong-token" * 4}).status_code == 403
            box = await page.frame_locator("iframe").locator("button").bounding_box()
            click = {**body, "action": "click", "x": box["x"] + 50, "y": box["y"] + 30}
            response = auth_client.post(f"/api/handoffs/{public_id}/actions", json=click)
            assert response.status_code == 200, response.text
            assert await page.frame_locator("iframe").locator("body").get_attribute("data-owner-clicks") == "1"
            answer = await page.locator("#answer").bounding_box()
            blocked = auth_client.post(f"/api/handoffs/{public_id}/actions", json={**body, "action": "click", "x": answer["x"] + 10, "y": answer["y"] + 10})
            assert blocked.status_code == 400, blocked.text
            assert await page.locator("#answer").input_value() == "Verified synthetic candidate"
            assert await page.evaluate("window.syntheticSubmits") == 0

            class FixtureLeverAdapter:
                name, version = "lever", "1.1.0"
                async def resolve_surface(self, current): return current
                async def step_fingerprint(self, surface): return "synthetic-fixed-step"
                async def find_submit_button(self, surface): return surface.locator("#submit")
                async def extract_validation_errors(self, surface): return []
                async def detect_confirmation(self, surface, **kwargs): return []

            async def fixture_adapter(_page, _url): return FixtureLeverAdapter()
            monkeypatch.setattr(browser_handoff, "detect_ats_adapter", fixture_adapter)
            endpoint = f"/api/supervised-submissions/applications/{app_id}/operator-assisted/handoffs/{public_id}/submit"
            first = auth_client.post(endpoint, json=body)
            assert first.status_code == 200, first.text
            assert first.json()["submission_confirmed"] is False
            assert await page.evaluate("window.syntheticSubmits") == 1
            assert auth_client.post(endpoint, json=body).status_code == 409
            assert await page.evaluate("window.syntheticSubmits") == 1
            evidence = Path(os.getenv("JT5_OWNER_EVIDENCE_DIR", str(tmp_path)))
            evidence.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(evidence / "owner-handoff-fixture.png"))
            await runtime.context.tracing.stop(path=str(evidence / "owner-handoff-trace.zip"))
            runtime.terminate()
            runtime = None
            disconnected = auth_client.post(f"/api/handoffs/{public_id}/capabilities", json=body)
            assert disconnected.status_code == 409, disconnected.text
            (evidence / "owner-handoff-outcome.json").write_text(json.dumps({
                "synthetic_only": True, "real_employer_submission": False,
                "native_widget_clicks": 1, "native_fixture_submits": 1,
                "duplicate_submit_blocked": True, "answer_edit_blocked": True,
                "wrong_lease_blocked": True, "stopped_browser_blocked": True,
                "approval_reference": reference, "network_requests_intercepted": len(observed_requests),
            }, indent=2))
        finally:
            if runtime is not None:
                runtime.terminate()
