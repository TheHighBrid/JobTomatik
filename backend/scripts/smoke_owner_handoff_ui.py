"""Exercise the real React handoff on a Vite server with synthetic API responses."""
import asyncio
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.async_api import async_playwright, expect


async def main(origin: str, evidence: Path):
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    harness = frontend / "owner-handoff-fixture.html"
    harness.write_text('''<div id="root"></div><script type="module">
import React from 'react'; import {createRoot} from 'react-dom/client';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import Panel from '/src/components/OperatorFinalSubmitHandoffPanel.jsx';
import '/src/index.css';
localStorage.setItem('jobtomatik_api_url', location.origin);
createRoot(document.getElementById('root')).render(React.createElement(QueryClientProvider,
{client:new QueryClient()}, React.createElement(Panel,{applicationId:101})));
</script>''')
    evidence.mkdir(parents=True, exist_ok=True)
    png = io.BytesIO()
    Image.new("RGB", (1280, 900), "#eef2f6").save(png, format="PNG")
    session = {"public_id": "owner-ui-synthetic", "application_id": 101, "status": "awaiting_user", "challenge_type": "final_submit", "current_url": "https://employer.example.test/synthetic/apply", "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()}
    approvals, actions, submissions, errors = [], [], [], []
    clicked = asyncio.Event()
    preflight = {"ready": True, "blockers": [], "operator_handoff_public_id": session["public_id"], "employer": "Synthetic Employer", "role": "Synthetic Role", "application_url": session["current_url"]}

    async def route_request(route):
        request = route.request
        path = urlsplit(request.url).path
        if not path.startswith("/api/"):
            if request.url.startswith(origin + "/"):
                await route.continue_()
            else:
                await route.abort()
            return
        path = path.removeprefix("/api/")
        result, status = {}, 200
        if path.endswith("/sessions"): result = [session]
        elif path.endswith("/preflight"): result = preflight
        elif path.endswith("/approvals"):
            if request.method == "POST":
                approvals[:] = [{"reference": "synthetic-approval", "status": "active", "approval_metadata": {"approval_source": "authenticated_user_operator_assisted", "handoff_public_id": session["public_id"]}}]
                result = approvals[0]
            else: result = approvals
        elif path.endswith("/authorize-final-click"):
            approvals[0]["status"] = "consumed"
            result = approvals[0]
        elif path.endswith("/bootstrap"): result = {"resume_token": "synthetic-resume-32-characters-long"}
        elif path.endswith("/claim"):
            session["status"] = "claimed"
            result = {"lease_token": "synthetic-lease-32-characters-long", "session": session}
        elif path.endswith("/capabilities"): result = {"browser_connected": True, "owner_pointer_enabled": True, "submit_available": True}
        elif path.endswith("/frame"):
            await route.fulfill(status=200, content_type="image/png", body=png.getvalue())
            return
        elif path.endswith("/actions"):
            actions.append(request.post_data_json)
            clicked.set()
        elif path.endswith("/submit"):
            submissions.append(request.post_data_json)
            approvals[0]["approval_metadata"]["operator_submit_action_started_at"] = datetime.now(timezone.utc).isoformat()
            result = {"submission_confirmed": False}
        elif path.endswith("/complete"): result, status = {"detail": "Synthetic confirmation not present"}, 409
        await route.fulfill(status=status, content_type="application/json", body=json.dumps(result))

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(viewport={"width": 390, "height": 1000})
            await context.tracing.start(screenshots=True, snapshots=True)
            page = await context.new_page()
            page.on("pageerror", lambda error: (errors.append(str(error)), print("UI error:", str(error), flush=True)))
            await page.route("**/*", route_request)
            await page.goto(origin + "/owner-handoff-fixture.html")
            approval_button = page.get_by_role("button", name="Approve and open application")
            await expect(approval_button).to_be_disabled(timeout=20000)
            await page.get_by_role("checkbox").check()
            await expect(approval_button).to_be_enabled()
            assert submissions == []
            await approval_button.click()
            image = page.get_by_alt_text("Live retained application. Click verification widgets to interact.")
            await expect(image).to_be_visible()
            submit = page.get_by_role("button", name="Submit exact application once")
            await expect(submit).to_be_enabled()
            assert submissions == []
            await image.click()
            await asyncio.wait_for(clicked.wait(), 10)
            assert abs(actions[0]["x"] - 640) < 3 and abs(actions[0]["y"] - 450) < 3
            await expect(submit).to_be_enabled()
            await submit.click()
            await expect(page.get_by_role("button", name="Final submit already requested")).to_be_disabled()
            assert len(submissions) == 1
            await page.screenshot(path=str(evidence / "owner-handoff-mobile-ui.png"), full_page=True)
            session["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            await page.reload()
            await expect(page.get_by_role("alert")).to_contain_text("expired or stopped")
            await expect(page.get_by_role("button", name="Submit exact application once")).to_have_count(0)
            assert not errors, errors
            await context.tracing.stop(path=str(evidence / "owner-handoff-ui-trace.zip"))
            await browser.close()
        result = {"synthetic_only": True, "mobile_viewport": "390x1000", "approval_to_claim": "passed", "scaled_owner_pointer": "passed", "no_implicit_submit": True, "final_action_requests": len(submissions), "expired_controls_hidden": True, "javascript_errors": errors}
        (evidence / "owner-handoff-ui-outcome.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        harness.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1].rstrip("/"), Path(sys.argv[2])))
