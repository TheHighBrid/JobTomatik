"""Synthetic completion tests; no employer request or real application is sent."""

import asyncio
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

import app.database as database
from app.config import get_settings
from app.models.application import (
    Application, ApplicationAutomationState, ApplicationEvent, ApplicationStatus,
    ManualReviewReason, ManualReviewStatus, ManualReviewTask, SubmissionEvidence,
)
from app.models.handoff import ManualHandoffSession
from app.models.submission_approval import SubmissionApproval
from app.services import browser_handoff, browser_runtime, form_filler_handoff
from app.services import operator_assisted_completion as completion
from app.services import supervised_target_identity as target_identity
from app.services.application_state import create_manual_review_task
from app.tasks import operator_assisted as prepare_task
from tests.conftest import TestingSessionLocal
from tests.test_operator_assisted_submission import (
    LEVER_URL, POSTING_ID, _create_final_submit_boundary, _keep_automation_off,
    _prepare_application,
)

THANKS_URL = LEVER_URL.removesuffix("/apply") + "/thanks"
FORM_HTML = """
<html><head><title>Payments Risk Analyst - SafeCo</title></head><body>
<div class="posting-headline"><h2>Payments Risk Analyst</h2></div>
<form class="application-form">
  <label for="name">Full name</label><input name="name" id="name" required>
  <label for="email">Email</label><input name="email" id="email" type="email" required>
  <label for="phone">Phone</label><input name="phone" id="phone" type="tel">
  <label for="resume">Resume</label><input name="resume" id="resume" type="file">
  <button class="postings-btn" type="submit">Submit application</button>
</form>
<script>
window.submitClicks = 0;
document.querySelector('form').onsubmit = (event) => {
  event.preventDefault();
  window.submitClicks += 1;
  window.submittedName = document.querySelector('#name').value;
  window.submittedEmail = document.querySelector('#email').value;
  window.submittedResume = document.querySelector('#resume').files.length;
  COMPLETION_SCRIPT
};
</script></body></html>
"""


@pytest.fixture
def env(auth_client, tmp_path, monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "api")
    app_id = _prepare_application(auth_client, tmp_path)
    _keep_automation_off(monkeypatch)
    for module in (completion, prepare_task, database):
        monkeypatch.setattr(module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(completion, "CONFIRMATION_RECHECK_INTERVAL_SECONDS", 0.2)

    async def official(*_args, **_kwargs):
        return {
            "id": POSTING_ID, "text": "Payments Risk Analyst", "categories": {},
            "description": "Risk analyst", "descriptionPlain": "Risk analyst",
            "hostedUrl": LEVER_URL.removesuffix("/apply"), "applyUrl": LEVER_URL,
        }

    monkeypatch.setattr(target_identity, "_fetch_supervised_lever_posting", official)
    queued = []

    def enqueue(*, args, queue):
        queued.append((args, queue))
        return SimpleNamespace(id="synthetic-fill-task")

    monkeypatch.setattr(prepare_task.prepare_operator_assisted_application_task, "apply_async", enqueue)
    return SimpleNamespace(app_id=app_id, client=auth_client, queued=queued, tmp_path=tmp_path, monkeypatch=monkeypatch,
        url=f"/api/supervised-submissions/applications/{app_id}/operator-assisted")


def _request(env, *, submit=True):
    response = env.client.post(env.url + "/prepare", json={"submit_when_ready": submit})
    assert response.status_code == 202, response.text
    return response.json()


def _complete(env, request):
    return env.client.post(env.url + "/complete", json={"completion_request_id": request["completion_request_id"]})


def test_explicit_request_preserves_the_fill_only_worker_contract(env):
    result = _request(env)
    assert env.queued == [([env.app_id], "applications")]
    assert result["completion_requested"] is True
    with TestingSessionLocal() as db:
        request = db.query(ApplicationEvent).filter(ApplicationEvent.id == result["completion_request_id"]).one()
        assert request.payload["combined_payload_hash"]
        assert request.payload["target_identity_hash"]
        assert db.query(SubmissionApproval).count() == 0
    assert _complete(env, result).status_code == 409  # Still not filled.


def test_fill_only_request_does_not_authorize_completion(env):
    result = _request(env, submit=False)
    assert result["completion_request_id"] is None
    _create_final_submit_boundary(env.app_id)
    response = env.client.post(env.url + "/complete", json={"completion_request_id": 987654})
    assert response.status_code == 409
    with TestingSessionLocal() as db:
        assert db.query(SubmissionApproval).count() == 0


def test_already_filled_page_does_not_queue_another_fill(env):
    public_id = _create_final_submit_boundary(env.app_id)
    result = _request(env)
    assert result["handoff_public_id"] == public_id
    assert result["completion_request_id"]
    assert result["task_id"] is None
    assert env.queued == []


def test_payload_drift_blocks_before_browser_connection(env, monkeypatch):
    request = _request(env)
    _create_final_submit_boundary(env.app_id)
    with TestingSessionLocal() as db:
        application = db.query(Application).filter(Application.id == env.app_id).one()
        application.cover_letter = "A different letter was written after the request."
        db.commit()

    async def unexpected(*_args, **_kwargs):
        pytest.fail("payload drift must not reach the browser")

    monkeypatch.setattr(browser_handoff, "perform_handoff_action", unexpected)
    result = _complete(env, request).json()
    assert result["success"] is False
    assert "payload or target changed" in result["error"]
    with TestingSessionLocal() as db:
        assert db.query(SubmissionApproval).count() == 0


def test_worker_and_api_bootstrap_do_not_import_completion():
    for module in ("app.tasks.operator_assisted", "app.main"):
        completed = subprocess.run([sys.executable, "-c", f"""
import importlib, sys
importlib.import_module({module!r})
assert 'app.services.operator_assisted_completion' not in sys.modules
from app.services import operator_assisted_handoff_integration as integration
assert integration._INSTALLED
"""], capture_output=True, text=True, check=False)
        assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("confirmed", [True, False])
def test_durable_approval_checkpoint_outcome_and_duplicate_request(env, monkeypatch, confirmed):
    from app.services.operator_assisted_handoff_integration import _checkpoint_fresh_live_snapshot

    request = _request(env)
    public_id = _create_final_submit_boundary(env.app_id)
    clicks = []

    async def action(session, *, action):
        assert action == "operator_submit"
        assert session.public_id == public_id  # Exercises post-commit detached attributes.
        with TestingSessionLocal() as db:
            approval = db.query(SubmissionApproval).one()
            assert approval.status == "consumed"
            assert approval.approval_metadata["operator_submit_action_started_at"]
        _checkpoint_fresh_live_snapshot(session, current_url=LEVER_URL, current_fingerprint="live-before")
        clicks.append(public_id)
        return {"action": action, "current_url": THANKS_URL if confirmed else LEVER_URL,
            "current_fingerprint": "live-after", "submission_confirmed": confirmed,
            "confirmation_detector": "synthetic-test", "confirmation_evidence": [{
                "evidence_type": "success_banner", "is_sufficient": True,
                "final_url": THANKS_URL, "confirmation_text": "Thanks for applying",
            }] if confirmed else []}

    async def no_confirmation(_session):
        return browser_handoff.BrowserVerification(challenge_cleared=False, provider="local_cdp",
            current_url=LEVER_URL, current_fingerprint="live-after", evidence={})

    monkeypatch.setattr(browser_handoff, "perform_handoff_action", action)
    monkeypatch.setattr(browser_handoff, "verify_browser_handoff_completion", no_confirmation)
    result = _complete(env, request).json()
    assert result["success"] is confirmed, result
    with TestingSessionLocal() as db:
        application = db.query(Application).filter(Application.id == env.app_id).one()
        assert application.automation_state == ("confirmed" if confirmed else "submission_uncertain")
        assert application.status == (ApplicationStatus.applied if confirmed else ApplicationStatus.pending)
    assert _complete(env, request).status_code == 409
    assert clicks == [public_id]


def test_pre_click_block_retains_form_and_does_not_replay(env, monkeypatch):
    request = _request(env)
    _create_final_submit_boundary(env.app_id)
    calls = []

    async def blocked(*_args, **_kwargs):
        calls.append(True)
        raise browser_handoff.BrowserHandoffError("Submit control is disabled")

    monkeypatch.setattr(browser_handoff, "perform_handoff_action", blocked)
    result = _complete(env, request).json()
    assert result["success"] is False
    assert result["final_submit_click_possible"] is False
    assert result["automation_state"] == "needs_review"
    assert "disabled" in result["error"]
    assert _complete(env, request).json()["success"] is False
    assert calls == [True]


def test_other_review_blocks_without_issuing_approval(env, monkeypatch):
    request = _request(env)
    _create_final_submit_boundary(env.app_id)
    with TestingSessionLocal() as db:
        application = db.query(Application).filter(Application.id == env.app_id).one()
        create_manual_review_task(db, application, ManualReviewReason.ambiguous_question, "An answer is missing.")
        db.commit()
    assert _complete(env, request).status_code == 409
    with TestingSessionLocal() as db:
        assert db.query(SubmissionApproval).count() == 0


@pytest.fixture
def browser_env(env, monkeypatch):
    """A real CDP browser with an unrelated existing tab, all page requests intercepted."""
    from playwright.async_api import async_playwright

    settings = get_settings()
    monkeypatch.setattr(settings, "application_browser_profile_dir", str(env.tmp_path / "profile"))
    monkeypatch.setattr(settings, "application_browser_provider", "external_cdp")
    monkeypatch.setattr(settings, "handoff_storage_dir", str(env.tmp_path / "handoffs"))
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_MODE", raising=False)

    async def start():
        async with async_playwright() as playwright:
            runtime = await browser_runtime.launch_retainable_browser(playwright,
                profile_dir=env.tmp_path / "profile", executable_path=settings.application_browser_executable)
            await runtime.page.goto("data:text/html,<title>Personal tab</title><p>Keep this tab</p>")
            return runtime

    try:
        owner = asyncio.run(start())
    except Exception as exc:
        if os.environ.get("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(f"Chromium is required: {exc}")
        pytest.skip(f"Chromium unavailable: {exc}")
    monkeypatch.setattr(settings, "application_browser_cdp_endpoint", owner.cdp_endpoint)
    original_launch = form_filler_handoff.launch_application_browser
    env.launched = []
    env.html = FORM_HTML.replace("COMPLETION_SCRIPT", f"history.pushState({{}}, '', '{THANKS_URL}'); document.body.innerHTML = '<h1>Thanks for applying</h1>';")

    async def launch(playwright, **kwargs):
        runtime = await original_launch(playwright, **kwargs)

        async def route(request):
            if request.request.url == LEVER_URL:
                await request.fulfill(status=200, content_type="text/html", body=env.html)
            else:
                await request.abort()

        await runtime.context.route("**/*", route)
        env.launched.append(await browser_runtime.controlled_page_target_id(runtime.page))
        return runtime

    monkeypatch.setattr(form_filler_handoff, "launch_application_browser", launch)
    env.endpoint = owner.cdp_endpoint
    try:
        yield env
    finally:
        owner.terminate(remove_profile=True)


def _browser_observation(env):
    from playwright.async_api import async_playwright

    async def observe():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(env.endpoint)
            pages = browser.contexts[0].pages
            personal = [page for page in pages if page.url.startswith("data:")]
            application = [page for page in pages if page.url.startswith("https://jobs.lever.co/")]
            assert len(personal) == 1
            assert await personal[0].title() == "Personal tab"
            assert len(application) == 1
            page = application[0]
            return {"url": page.url, "target_id": await browser_runtime.controlled_page_target_id(page),
                **await page.evaluate("({clicks: window.submitClicks, name: window.submittedName, email: window.submittedEmail, resume: window.submittedResume})")}

    return asyncio.run(observe())


def _fill(env):
    with env.monkeypatch.context() as worker:
        worker.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")
        result = prepare_task.prepare_operator_assisted_application_task.run(env.app_id)
    assert result.get("handoff_public_id"), result
    assert result["final_submit_clicked_by_jobtomatik"] is False
    assert len(env.launched) == 1
    return result


def test_real_tab_fill_retain_submit_confirm_and_no_replay(browser_env):
    env = browser_env
    request = _request(env)
    filled = _fill(env)
    assert _browser_observation(env)["clicks"] == 0
    result = _complete(env, request).json()
    assert result.get("success") is True, result
    assert result["submission_confirmed"] is True
    observed = _browser_observation(env)
    assert observed == {"url": THANKS_URL, "target_id": env.launched[0], "clicks": 1,
        "name": "Test User", "email": "test@example.com", "resume": 1}
    with TestingSessionLocal() as db:
        application = db.query(Application).filter(Application.id == env.app_id).one()
        assert application.status == ApplicationStatus.applied
        assert application.automation_state == ApplicationAutomationState.confirmed.value
        assert application.applied_at
        assert "Lever submission confirmed" in application.notes
        evidence = db.query(SubmissionEvidence).filter(SubmissionEvidence.application_id == env.app_id).all()
        assert any(item.is_sufficient and item.final_url == THANKS_URL for item in evidence)
        session = db.query(ManualHandoffSession).filter(ManualHandoffSession.public_id == filled["handoff_public_id"]).one()
        assert session.status == "completed"
        assert db.query(ManualReviewTask).filter(ManualReviewTask.id == session.manual_review_id).one().status == "resolved"
    assert _complete(env, request).status_code == 409
    assert _request_closed(env).status_code == 409
    assert _browser_observation(env)["clicks"] == 1
    assert len(env.launched) == 1


def _request_closed(env):
    return env.client.post(env.url + "/prepare", json={"submit_when_ready": True})


def test_real_click_without_confirmation_stays_uncertain(browser_env):
    env = browser_env
    env.html = FORM_HTML.replace("COMPLETION_SCRIPT", "")
    request = _request(env)
    _fill(env)
    result = _complete(env, request).json()
    assert result["success"] is False, result
    assert result["final_submit_clicked_by_jobtomatik"] is True
    with TestingSessionLocal() as db:
        application = db.query(Application).filter(Application.id == env.app_id).one()
        assert application.status == ApplicationStatus.pending
        assert application.automation_state == "submission_uncertain"
    assert _complete(env, request).status_code == 409
    assert _browser_observation(env)["clicks"] == 1


@pytest.mark.parametrize("control", ["missing", "disabled", "hidden", "hcaptcha"])
def test_changed_retained_form_fails_closed_without_refilling(browser_env, control):
    env = browser_env
    request = _request(env)
    filled = _fill(env)
    from playwright.async_api import async_playwright

    async def change():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(env.endpoint)
            page = next(page for page in browser.contexts[0].pages if page.url == LEVER_URL)
            if control == "missing":
                await page.locator('button[type="submit"]').evaluate("el => el.remove()")
            elif control == "disabled":
                await page.locator('button[type="submit"]').evaluate("el => el.disabled = true")
            elif control == "hidden":
                await page.locator('button[type="submit"]').evaluate("el => el.hidden = true")
            else:
                await page.evaluate("window.hcaptcha = {}")

    asyncio.run(change())
    result = _complete(env, request).json()
    assert result["success"] is False, result
    assert result["final_submit_click_possible"] is False
    assert _browser_observation(env)["clicks"] == 0
    with TestingSessionLocal() as db:
        assert db.query(Application).filter(Application.id == env.app_id).one().automation_state == "needs_review"
        assert db.query(ManualHandoffSession).filter(ManualHandoffSession.public_id == filled["handoff_public_id"]).one().status == "awaiting_user"
    assert len(env.launched) == 1
