"""Exercise owner outcome recovery in real Chromium against synthetic APIs only."""

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect


HARNESS = '''<div id="root"></div><script type="module">
import React from 'react'; import {createRoot} from 'react-dom/client';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter, Routes, Route} from 'react-router-dom';
import Page from '/src/pages/ApplicationDetail.jsx'; import '/src/index.css';
localStorage.setItem('jobtomatik_api_url', location.origin);
createRoot(document.getElementById('root')).render(React.createElement(QueryClientProvider,
{client:new QueryClient()},React.createElement(MemoryRouter,{initialEntries:['/applications/101']},
React.createElement(Routes,null,React.createElement(Route,{path:'/applications/:id',element:React.createElement(Page)})))));
</script>'''


class SyntheticRecoveryAPI:
    def __init__(self, origin, *, confirmation=False, rejection_mode=None, unavailable=False, applied=False,
                 receipt_only=False, incompatible=False):
        """Initialize isolated synthetic API state without contacting an employer."""
        if rejection_mode not in (None, "post_rejection", "previously_rejected"):
            raise ValueError("Unsupported synthetic rejection mode")
        self.origin, self.rejected, self.unavailable = origin, rejection_mode == "post_rejection", unavailable
        self.posts, self.forbidden, self.errors = [], [], []
        self.state, self.attempt_status, self.snapshot = "submission_uncertain", "uncertain", "a" * 64
        self.status = "applied" if applied else "pending"
        self.confirmation = confirmation
        self.receipt_only, self.incompatible = receipt_only, incompatible
        self.previously_rejected = rejection_mode == "previously_rejected"
        if incompatible:
            self.state = "needs_review"

    def application(self):
        return {
            "id": 101, "user_id": 1, "status": self.status, "automation_state": self.state,
            "notes": "", "cover_letter": "Synthetic verified letter", "events": [],
            "manual_reviews": [], "submission_evidence": [], "followups": [],
            "application_target_url": "https://employer.example.test/jobs/101",
            "application_target_status": "resolved", "job": {
                "title": "Synthetic Accounts Specialist", "company": "Synthetic Employer",
                "location": "Ottawa", "url": "https://employer.example.test/jobs/101",
            },
        }

    def recovery(self):
        evidence = [{
            "id": 7, "evidence_type": "confirmation_page", "snapshot_hash": self.snapshot,
            "confirmation_text": ("Updated " if self.snapshot.startswith("b") else "") + "Synthetic application received for posting 101",
            "final_url": "https://employer.example.test/jobs/101/thanks",
        }] if self.confirmation else []
        if evidence and self.receipt_only:
            evidence[0].update(confirmation_text="   ", external_application_id="synthetic-receipt-101")
        if self.previously_rejected or self.incompatible:
            evidence = []
        return {"attempt_reference": "jt5-synthetic", "resolution_required": self.attempt_status == "uncertain",
                "resolution_available": bool(evidence), "confirmation_evidence": evidence,
                "blockers": ["Application state changed; reload before resolving the outcome"] if self.incompatible else [],
                "automatic_retry_allowed": False}

    async def route(self, route):
        request = route.request
        if not request.url.startswith(self.origin + "/"):
            self.forbidden.append(request.url)
            await route.abort()
            return
        path = urlsplit(request.url).path
        if not path.startswith("/api/"):
            await route.continue_()
            return
        status, response = self.response(path, request)
        await route.fulfill(status=status, content_type="application/json", body=json.dumps(response))

    def response(self, path, request):
        if request.method == "POST":
            return self.post_response(path, request)
        if path.endswith("/jt5/reconciliation"):
            return (503, {"detail": "Synthetic read failure"}) if self.unavailable else (200, self.recovery())
        if path.endswith("/jt5/status"):
            return 200, {"latest_attempt": {"reference": "jt5-synthetic", "status": self.attempt_status,
                        "dispatch_status": "reconciliation_required" if self.attempt_status == "uncertain" else "reconciled"}}
        if path == "/api/applications/101":
            return 200, self.application()
        return 200, []

    def post_response(self, path, request):
        if not path.endswith("/jt5/reconcile"):
            self.forbidden.append(path)
            return 500, {"detail": "Apply and Submit are forbidden in this fixture"}
        self.posts.append(request.post_data_json)
        if self.rejected:
            self.snapshot = "b" * 64
            return 409, {"detail": "Synthetic worker busy or evidence snapshot changed"}
        self.state, self.attempt_status, self.status = "confirmed", "succeeded", "applied"
        return 200, {"automatic_retry_allowed": False, "idempotent": False}


async def open_fixture(browser, origin, **options):
    api = SyntheticRecoveryAPI(origin, **options)
    context = await browser.new_context(viewport={"width": 390, "height": 1000})
    await context.tracing.start(screenshots=True, snapshots=True)
    page = await context.new_page()
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    await page.route("**/*", api.route)
    await page.goto(origin + "/jt5-outcome-fixture.html")
    await expect(page.get_by_text("Resolve the prior outcome", exact=True)).to_be_visible()
    return api, context, page


async def assert_no_replay(page, api):
    await expect(page.get_by_role("button", name="Apply with JobTomatik")).to_have_count(0)
    assert not api.forbidden and not api.errors, (api.forbidden, api.errors)


async def exercise_unknown_and_read_failure(browser, origin, evidence):
    api, context, page = await open_fixture(browser, origin)
    await expect(page.get_by_text("Recovery is unavailable.", exact=False)).to_be_visible()
    await expect(page.get_by_role("button", name="Record verified outcome")).to_have_count(0)
    await assert_no_replay(page, api)
    assert not api.posts
    await page.screenshot(path=str(evidence / "unknown-outcome-mobile.png"), full_page=True)
    await context.tracing.stop(path=str(evidence / "unknown-outcome-trace.zip"))
    await context.close()
    api, context, page = await open_fixture(browser, origin, unavailable=True)
    await expect(page.get_by_role("alert")).to_contain_text("could not be loaded")
    await expect(page.get_by_role("button", name="Record verified outcome")).to_have_count(0)
    await assert_no_replay(page, api)
    assert not api.posts
    await context.close()


async def exercise_confirmation(browser, origin, evidence):
    api, context, page = await open_fixture(browser, origin, confirmation=True, rejection_mode="post_rejection")
    await page.get_by_label("Retained confirmation").select_option("7")
    await expect(page.get_by_text("Synthetic application received for posting 101", exact=True)).to_be_visible()
    await page.get_by_label("What did the evidence establish?").fill("Retained employer confirmation matches this exact application.")
    await page.get_by_role("checkbox").check()
    await page.get_by_role("button", name="Record verified outcome").click()
    await expect(page.get_by_role("checkbox")).not_to_be_checked()
    await expect(page.get_by_text("Updated Synthetic application received for posting 101", exact=True)).to_be_visible()
    await assert_no_replay(page, api)
    assert len(api.posts) == 1 and api.posts[0]["evidence_snapshot_hash"] == "a" * 64
    api.rejected = False
    await page.screenshot(path=str(evidence / "retained-confirmation-mobile.png"), full_page=True)
    await page.get_by_role("checkbox").check()
    await page.get_by_role("button", name="Record verified outcome").click()
    await expect(page.get_by_text("Application submitted. New submission attempts are hidden for this record.")).to_be_visible()
    assert len(api.posts) == 2 and api.posts[1]["evidence_snapshot_hash"] == "b" * 64
    await assert_no_replay(page, api)
    await context.tracing.stop(path=str(evidence / "confirmation-trace.zip"))
    await context.close()


async def exercise_owner_history(browser, origin):
    api, context, page = await open_fixture(browser, origin, applied=True)
    await expect(page.get_by_role("button", name="Record verified outcome")).to_have_count(0)
    await assert_no_replay(page, api)
    assert not api.posts
    await context.close()


async def exercise_review_findings(browser, origin):
    api, context, page = await open_fixture(browser, origin, confirmation=True, receipt_only=True)
    await page.get_by_label("Retained confirmation").select_option("7")
    await expect(page.get_by_text("synthetic-receipt-101", exact=True)).to_be_visible()
    assert not api.posts and not api.errors
    await context.close()
    for options in ({"incompatible": True}, {"rejection_mode": "previously_rejected"}):
        api, context, page = await open_fixture(browser, origin, confirmation=True, **options)
        await expect(page.get_by_text("Recovery is unavailable.", exact=False)).to_be_visible()
        await expect(page.get_by_role("button", name="Record verified outcome")).to_have_count(0)
        await expect(page.get_by_label("Retained confirmation")).to_have_count(0)
        await assert_no_replay(page, api)
        assert not api.posts
        await context.close()


async def main(origin, evidence):
    harness = Path(__file__).resolve().parents[2] / "frontend" / "jt5-outcome-fixture.html"
    harness.write_text(HARNESS)
    evidence.mkdir(parents=True, exist_ok=True)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            await exercise_unknown_and_read_failure(browser, origin, evidence)
            await exercise_confirmation(browser, origin, evidence)
            await exercise_owner_history(browser, origin)
            await exercise_review_findings(browser, origin)
            await browser.close()
        result = {"synthetic_only": True, "real_react_application_page": True, "mobile_viewport": "390x1000",
                  "unverified_non_submission_unavailable": True, "confirmation_and_snapshot_drift": "passed",
                  "unknown_read_failure_and_rejected_resolution": "passed", "owner_history_preserved": True,
                  "receipt_id_fallback_and_unavailable_choices": "passed",
                  "automatic_apply_or_submit_requests": 0, "javascript_errors": 0}
        (evidence / "outcome-recovery-ui.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        harness.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1].rstrip("/"), Path(sys.argv[2])))
