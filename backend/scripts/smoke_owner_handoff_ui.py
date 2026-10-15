"""Exercise the real React handoff on a Vite server with synthetic API responses."""
import asyncio
import io
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.async_api import async_playwright, expect


HARNESS = '''<div id="root"></div><script type="module">
import React from 'react'; import {createRoot} from 'react-dom/client';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import Panel from '/src/components/OperatorFinalSubmitHandoffPanel.jsx';
import '/src/index.css';
localStorage.setItem('jobtomatik_api_url', location.origin);
createRoot(document.getElementById('root')).render(React.createElement(QueryClientProvider,
{client:new QueryClient()}, React.createElement(Panel,{applicationId:101})));
</script>'''


class SyntheticHandoffAPI:
    def __init__(self, origin):
        """Create an isolated API fixture with no live credentials or employer requests."""
        self.origin = origin
        self.session = {
            "public_id": "owner-ui-synthetic", "application_id": 101,
            "status": "awaiting_user", "challenge_type": "final_submit",
            "current_url": "https://employer.example.test/synthetic/apply",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
        }
        self.approvals, self.actions, self.submissions, self.errors = [], [], [], []
        self.clicked = asyncio.Event()
        self.frame_interrupted = False
        self.capabilities_interrupted = False
        self.png = io.BytesIO()
        Image.new("RGB", (1280, 900), "#eef2f6").save(self.png, format="PNG")

    def preflight(self, _request):
        return {
            "ready": True, "blockers": [], "operator_handoff_public_id": self.session["public_id"],
            "employer": "Synthetic Employer", "role": "Synthetic Role", "application_url": self.session["current_url"],
        }

    def approval(self, request):
        if request.method != "POST":
            return self.approvals
        self.approvals[:] = [{
            "reference": "synthetic-approval", "status": "active", "approval_metadata": {
                "approval_source": "authenticated_user_operator_assisted", "handoff_public_id": self.session["public_id"],
            },
        }]
        return self.approvals[0]

    def authorize(self, _request):
        self.approvals[0]["status"] = "consumed"
        return self.approvals[0]

    def claim(self, _request):
        self.session["status"] = "claimed"
        return {"lease_token": secrets.token_urlsafe(32), "session": self.session}

    def action(self, request):
        self.actions.append(request.post_data_json)
        self.clicked.set()
        return {}

    def submit(self, request):
        self.submissions.append(request.post_data_json)
        self.approvals[0]["approval_metadata"]["operator_submit_action_started_at"] = datetime.now(timezone.utc).isoformat()
        return {"submission_confirmed": False}

    def response(self, endpoint, request):
        handlers = {
            "sessions": lambda _: [self.session], "preflight": self.preflight,
            "approvals": self.approval, "authorize-final-click": self.authorize,
            "bootstrap": lambda _: {"resume_token": secrets.token_urlsafe(32)}, "claim": self.claim,
            "capabilities": lambda _: {"browser_connected": True, "owner_pointer_enabled": True, "submit_available": True},
            "actions": self.action, "submit": self.submit,
        }
        return handlers.get(endpoint, lambda _: {})(request)

    async def route_request(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if not path.startswith("/api/"):
            if request.url.startswith(self.origin + "/"):
                await route.continue_()
            else:
                await route.abort()
            return
        endpoint = path.rsplit("/", 1)[-1]
        if endpoint == "frame":
            if self.actions and not self.frame_interrupted:
                self.frame_interrupted = True
                await route.abort()
                return
            await route.fulfill(status=200, content_type="image/png", body=self.png.getvalue())
            return
        if endpoint == "capabilities" and self.actions and not self.capabilities_interrupted:
            self.capabilities_interrupted = True
            await route.abort()
            return
        status, result = 200, self.response(endpoint, request)
        if endpoint == "complete":
            status, result = 409, {"detail": "Synthetic confirmation not present"}
        await route.fulfill(status=status, content_type="application/json", body=json.dumps(result))


async def exercise_approval_and_pointer(page, api):
    approval_button = page.get_by_role("button", name="Approve and open application")
    await expect(approval_button).to_be_disabled(timeout=20000)
    await page.get_by_role("checkbox").check()
    await expect(approval_button).to_be_enabled()
    assert api.submissions == []
    await approval_button.click()
    image = page.get_by_alt_text("Live retained application. Click verification widgets to interact.")
    await expect(image).to_be_visible()
    submit = page.get_by_role("button", name="Submit exact application once")
    await expect(submit).to_be_enabled()
    assert api.submissions == []
    await image.click()
    await asyncio.wait_for(api.clicked.wait(), 10)
    assert abs(api.actions[0]["x"] - 640) < 3 and abs(api.actions[0]["y"] - 450) < 3
    await expect(page.get_by_role("alert")).to_contain_text("Reconnecting automatically")
    await expect(submit).to_be_enabled(timeout=15000)
    assert api.frame_interrupted and api.capabilities_interrupted
    assert len(api.actions) == 1 and not api.submissions


async def exercise_submit_and_expiry(page, api, evidence):
    await page.get_by_role("button", name="Submit exact application once").click()
    await expect(page.get_by_role("button", name="Final submit already requested")).to_be_disabled()
    assert len(api.submissions) == 1
    await page.screenshot(path=str(evidence / "owner-handoff-mobile-ui.png"), full_page=True)
    api.session["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    await page.reload()
    await expect(page.get_by_role("status")).to_contain_text("employer receipt unconfirmed")
    await expect(page.get_by_role("alert")).to_contain_text("new submission must stay blocked")
    await expect(page.get_by_role("button", name="Submit exact application once")).to_have_count(0)
    assert not api.errors, api.errors


async def exercise_mobile_view(origin, evidence, api):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(viewport={"width": 390, "height": 1000})
        await context.tracing.start(screenshots=True, snapshots=True)
        page = await context.new_page()
        page.on("pageerror", lambda error: (api.errors.append(str(error)), print("UI error:", str(error), flush=True)))
        await page.route("**/*", api.route_request)
        await page.goto(origin + "/owner-handoff-fixture.html")
        await exercise_approval_and_pointer(page, api)
        await exercise_submit_and_expiry(page, api, evidence)
        await context.tracing.stop(path=str(evidence / "owner-handoff-ui-trace.zip"))
        await browser.close()


async def main(origin: str, evidence: Path):
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    harness = frontend / "owner-handoff-fixture.html"
    harness.write_text(HARNESS)
    evidence.mkdir(parents=True, exist_ok=True)
    api = SyntheticHandoffAPI(origin)
    try:
        await exercise_mobile_view(origin, evidence, api)
        result = {
            "synthetic_only": True, "mobile_viewport": "390x1000", "approval_to_claim": "passed",
            "scaled_owner_pointer": "passed", "no_implicit_submit": True, "final_action_requests": len(api.submissions),
            "expired_controls_hidden": True, "javascript_errors": api.errors,
            "transient_frame_and_capability_recovery": api.frame_interrupted and api.capabilities_interrupted,
        }
        (evidence / "owner-handoff-ui-outcome.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        harness.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1].rstrip("/"), Path(sys.argv[2])))
