"""Prove synthetic Lever preparation with the production filler and retention."""

# Only browser launch is supplied by the fixture to install a deny-all network
# route before navigation. This does not certify employer metadata, API/Celery
# dispatch, owner authorization, a real submission, or an employer confirmation.
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from app.services import form_filler_handoff
from app.services.browser_runtime_base import launch_retainable_browser
from app.services.operator_assisted_handoff_integration import (
    install_operator_assisted_handoff_integration,
    operator_prepare_scope,
)
from app.tasks import applications as application_tasks


FIXTURE_URL = "https://jobs.lever.co/jt5-synthetic/prepare-proof/apply"
FIXTURE_HTML = """<!doctype html><title>Synthetic retained Lever preparation</title>
<form class="application-form">
<label for="name">Full name</label><input id="name" name="name" required>
<label for="email">Email</label><input id="email" name="email" type="email" required>
<label for="resume">Resume/CV</label>
<input id="resume" name="resume" type="file" accept=".pdf" required>
<button id="submit" class="postings-btn" type="submit">Submit application</button>
</form><script>
window.fixtureActions = {clicks: 0, submits: 0};
document.querySelector('#submit').addEventListener('click', () => window.fixtureActions.clicks++);
document.querySelector('form').addEventListener('submit', event => {
 event.preventDefault(); window.fixtureActions.submits++;
});
</script>"""


def _assert_prepared_boundary(result, target):
    """Check upload evidence and the exact final-owner snapshot binding."""
    assert result["success"] is True, result
    assert result["ready_to_submit"] is True
    assert result["requires_manual_review"] is True
    assert result["ats_adapter"] == "lever"
    assert result["submitted_at"] is None
    assert result["upload_evidence"][0]["verification"] == "passed"
    assert any(item["reason_code"] == "operator_final_submit_required" for item in result["review_items"])
    assert not any(item.get("action") == "ats_submit_clicked" for item in result["log"])
    snapshot = result["handoff_snapshot"]
    assert snapshot["current_url"] == FIXTURE_URL
    assert snapshot["metadata"]["supervised_target"] == target
    assert snapshot["metadata"]["operator_target_identity_hash"] == target["identity_hash"]
    assert snapshot["metadata"]["operator_assisted_final_submit"] is True
    assert snapshot["metadata"]["automated_submission_authorized"] is False
    target_id = snapshot["metadata"]["controlled_page_target_id"]
    assert target_id

    return snapshot


async def _reconnect_and_observe(snapshot, resume, evidence_dir):
    """Observe the same filled target after the original controller exits."""
    target_id = snapshot["metadata"]["controlled_page_target_id"]
    # The production wrapper's Playwright manager has stopped. Reconnect with
    # an independent manager and locate the retained page by its CDP identity.
    async with async_playwright() as reconnect:
        browser = await reconnect.chromium.connect_over_cdp(snapshot["browser_endpoint"])
        pages = [page for context in browser.contexts for page in context.pages]
        retained = [page for page in pages if page.url == FIXTURE_URL]
        assert len(retained) == 1
        page = retained[0]
        session = await page.context.new_cdp_session(page)
        try:
            info = await session.send("Target.getTargetInfo")
            assert info["targetInfo"]["targetId"] == target_id
        finally:
            await session.detach()
        assert await page.locator("#name").input_value() == "Synthetic Candidate"
        assert await page.locator("#email").input_value() == "candidate@example.test"
        assert await page.locator("#resume").evaluate("el => el.files[0].name") == resume.name
        actions = await page.evaluate("window.fixtureActions")
        assert actions == {"clicks": 0, "submits": 0}
        await page.screenshot(path=str(evidence_dir / "retained-preparation.png"))
        (evidence_dir / "retained-preparation.html").write_text(await page.content(), encoding="utf-8")
    return actions


@pytest.mark.asyncio
async def test_operator_prepare_upload_retains_exact_form_after_disconnect(monkeypatch, tmp_path):
    """Prove fill/upload -> final owner boundary -> same retained browser page."""
    install_operator_assisted_handoff_integration()
    evidence_dir = Path(os.getenv("JT5_PREPARE_EVIDENCE_DIR", str(tmp_path / "evidence")))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    resume = tmp_path / "synthetic-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n% Synthetic upload fixture, not an applicant document.\n")
    target = {
        "platform": "lever", "target_url": FIXTURE_URL,
        "identity_hash": "synthetic-preparation-identity", "verified": True,
        "blockers": [],
    }
    requests = []
    runtime = None
    release_calls = []
    original_release = form_filler_handoff.release_application_browser

    async def launch_fixture_browser(playwright):
        nonlocal runtime
        try:
            runtime = await launch_retainable_browser(
                playwright, profile_dir=tmp_path / "profile", headless=True,
            )
        except Exception as exc:
            if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
                pytest.fail(f"Owned Chromium required for prepare proof: {exc}")
            pytest.skip(f"Owned Chromium unavailable: {exc}")

        async def route_fixture(route):
            request = route.request
            requests.append({"method": request.method, "url": request.url})
            if request.url == FIXTURE_URL and request.method == "GET":
                await route.fulfill(body=FIXTURE_HTML, content_type="text/html")
            else:
                await route.abort("blockedbyclient")

        async def deny_websocket(route):
            await route.close(code=1008, reason="Synthetic fixture only")

        await runtime.context.route("**/*", route_fixture)
        await runtime.context.route_web_socket("**/*", deny_websocket)
        await runtime.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        return runtime

    async def observe_release(current_runtime, *, retain_controlled_page=False):
        release_calls.append(retain_controlled_page)
        await current_runtime.context.tracing.stop(path=str(evidence_dir / "prepare-trace.zip"))
        await original_release(current_runtime, retain_controlled_page=retain_controlled_page)

    monkeypatch.setattr(form_filler_handoff, "launch_application_browser", launch_fixture_browser)
    monkeypatch.setattr(form_filler_handoff, "release_application_browser", observe_release)
    try:
        with operator_prepare_scope(target):
            result = await application_tasks.fill_and_submit_application(
                FIXTURE_URL,
                {"full_name": "Synthetic Candidate", "email": "candidate@example.test", "answer_policies": []},
                "", str(resume), dry_run=True,
            )
        snapshot = _assert_prepared_boundary(result, target)
        assert release_calls == [True]
        assert runtime.process.poll() is None
        actions = await _reconnect_and_observe(snapshot, resume, evidence_dir)
        target_id = snapshot["metadata"]["controlled_page_target_id"]
        assert requests == [{"method": "GET", "url": FIXTURE_URL}]
        receipt = {
            "synthetic_only": True, "real_employer_submission": False,
            "production_lever_adapter": True, "production_fill_and_retain_wrapper": True,
            "resume_upload_verified": True, "same_target_retained_after_disconnect": True,
            "controlled_page_target_id": target_id, "fixture_actions": actions,
            "final_action_authorized": False, "requests": requests,
            "resume_sha256": hashlib.sha256(resume.read_bytes()).hexdigest(),
            "trace_sha256": hashlib.sha256((evidence_dir / "prepare-trace.zip").read_bytes()).hexdigest(),
            "scope_exclusions": [
                "official_metadata_refresh", "API/Celery_dispatch",
                "durable_handoff_database_row", "owner_approval", "employer_confirmation",
            ],
        }
        (evidence_dir / "prepare-proof.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    finally:
        if runtime is not None:
            runtime.terminate(remove_profile=True)
