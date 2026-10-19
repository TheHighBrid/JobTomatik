"""Exercise API dispatch, a real Celery worker and durable synthetic Lever retention."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from celery.contrib.testing.worker import start_worker
from playwright.async_api import async_playwright

from app.api import supervised_submissions as api
from app.celery_app import celery_app
from app.config import get_settings
from app.models.application import Application, ManualReviewTask
from app.models.handoff import ManualHandoffSession
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt
from app.services import form_filler_handoff
from app.services.browser_runtime_base import launch_retainable_browser
from app.services.handoff_session import decrypt_handoff_secret
from app.tasks import operator_assisted as operator_tasks
from tests.conftest import TestingSessionLocal
from tests.test_operator_assisted_prepare_browser import FIXTURE_HTML
from tests.test_operator_assisted_submission import (
    LEVER_URL,
    _keep_automation_off,
    _prepare_application,
    _valid_metadata,
)


async def _observe_retained_form(endpoint, target_id, evidence):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        pages = [page for context in browser.contexts for page in context.pages if page.url == LEVER_URL]
        assert len(pages) == 1
        page = pages[0]
        session = await page.context.new_cdp_session(page)
        info = await session.send("Target.getTargetInfo")
        await session.detach()
        assert info["targetInfo"]["targetId"] == target_id
        assert await page.locator("#name").input_value() == "Test User"
        assert await page.locator("#email").input_value() == "test@example.com"
        assert await page.locator("#resume").evaluate("el => el.files[0].name") == "operator-assisted-lever.pdf"
        actions = await page.evaluate("window.fixtureActions")
        assert actions == {"clicks": 0, "submits": 0}
        await page.screenshot(path=str(evidence / "durable-retained-form.png"))
        (evidence / "durable-retained-form.html").write_text(await page.content(), encoding="utf-8")
        return actions


def _install_browser_fixture(monkeypatch, tmp_path, evidence):
    state = {"runtime": None, "requests": [], "releases": []}
    original_release = form_filler_handoff.release_application_browser

    async def launch_fixture(playwright):
        runtime = await launch_retainable_browser(
            playwright, profile_dir=tmp_path / "profile", headless=True,
        )

        state["runtime"] = runtime

        async def route_fixture(route):
            request = route.request
            state["requests"].append({"method": request.method, "url": request.url})
            if request.method == "GET" and request.url == LEVER_URL:
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
        state["releases"].append(retain_controlled_page)
        await current_runtime.context.tracing.stop(path=str(evidence / "prepare-trace.zip"))
        await original_release(current_runtime, retain_controlled_page=retain_controlled_page)

    monkeypatch.setattr(form_filler_handoff, "launch_application_browser", launch_fixture)
    monkeypatch.setattr(form_filler_handoff, "release_application_browser", observe_release)
    return state


def _assert_durable_boundary(application_id, result, metadata):
    # A new session must observe the committed worker writes, not an ORM
    # object or a fabricated handoff returned by a mocked task.
    with TestingSessionLocal() as db:
        session = db.query(ManualHandoffSession).one()
        application = db.query(Application).filter_by(id=application_id).one()
        review = db.query(ManualReviewTask).one()
        assert session.public_id == result["handoff_public_id"]
        assert session.application_id == application_id
        assert session.user_id == application.user_id
        assert session.manual_review_id == review.id
        assert session.challenge_type == "final_submit"
        assert session.status == "awaiting_user"
        assert session.current_url == LEVER_URL
        assert review.reason_code == "operator_final_submit_required"
        assert application.automation_state == "needs_review"
        assert application.applied_at is None
        assert session.handoff_metadata["supervised_target"]["identity_hash"] == metadata["identity_hash"]
        assert session.handoff_metadata["controlled_page_target_id"]
        assert db.query(SubmissionApproval).count() == 0
        assert db.query(SubmissionAttempt).count() == 0
        public_id = session.public_id
        target_id = session.handoff_metadata["controlled_page_target_id"]
        endpoint = decrypt_handoff_secret(session.encrypted_browser_endpoint)

    return {"public_id": public_id, "target_id": target_id, "endpoint": endpoint}


def _assert_owner_boundary(auth_client, application_id, public_id):
    visible = auth_client.get(f"/api/handoffs/{public_id}")
    assert visible.status_code == 200, visible.text
    assert visible.json()["current_url"] == LEVER_URL
    bootstrap = auth_client.post(f"/api/handoffs/{public_id}/bootstrap")
    assert bootstrap.status_code == 409
    assert "approval" in bootstrap.json()["detail"].lower()
    # A second authenticated prepare reuses the durable boundary, so
    # it cannot enqueue another fill attempt or replace the owner tab.
    repeated = auth_client.post(
        f"/api/supervised-submissions/applications/{application_id}/operator-assisted/prepare"
    )
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["handoff_public_id"] == public_id
    assert repeated.json()["task_id"] is None


def _write_receipt(evidence, dispatch, boundary, requests, actions):
    (evidence / "durable-prepare-proof.json").write_text(json.dumps({
        "synthetic_only": True,
        "broker_dispatch": "disposable Redis, serialized non-eager Celery",
        "worker_scope": "in-process solo worker, production task and startup integrations",
        "task_id": dispatch["task_id"],
        "handoff_public_id": boundary["public_id"],
        "controlled_page_target_id": boundary["target_id"],
        "durable_owner_bound_handoff": True,
        "repeat_prepare_reused_boundary": True,
        "owner_api_visible": True,
        "token_disclosure_requires_exact_approval": True,
        "requests": requests,
        "fixture_actions": actions,
        "real_employer_submission": False,
        "scope_exclusions": ["official_metadata_refresh", "independent_worker_process", "owner_approval", "employer_confirmation"],
    }, indent=2), encoding="utf-8")


def _configure_dispatch(monkeypatch, tmp_path, broker):
    _keep_automation_off(monkeypatch)
    monkeypatch.setattr(operator_tasks, "SessionLocal", TestingSessionLocal)
    metadata = _valid_metadata()

    async def synthetic_metadata(_job):
        return dict(metadata)

    monkeypatch.setattr(api, "resolve_supervised_target_metadata", synthetic_metadata)
    monkeypatch.setattr(operator_tasks, "resolve_supervised_target_metadata", synthetic_metadata)
    # Configure REDIS_URL before importing the application. Rebinding an already
    # cached backend can silently split API results from worker result writes.
    assert celery_app.conf.broker_url == broker
    assert celery_app.conf.result_backend == broker
    monkeypatch.setitem(celery_app.conf, "task_always_eager", False)
    monkeypatch.setattr(get_settings(), "handoff_storage_dir", str(tmp_path / "handoffs"))
    return metadata


def test_api_worker_prepare_persists_exact_retained_owner_boundary(
    auth_client, monkeypatch, tmp_path,
):
    """Use an explicitly supplied disposable Redis, never production or eager mode."""
    broker = os.getenv("JT5_DURABLE_PREPARE_BROKER_URL")
    if not broker:
        pytest.skip("Requires an explicitly provisioned disposable Redis broker")
    evidence = Path(os.getenv("JT5_DURABLE_PREPARE_EVIDENCE_DIR", str(tmp_path / "evidence")))
    evidence.mkdir(parents=True, exist_ok=True)
    application_id = _prepare_application(auth_client, tmp_path)
    metadata = _configure_dispatch(monkeypatch, tmp_path, broker)
    state = _install_browser_fixture(monkeypatch, tmp_path, evidence)
    try:
        with start_worker(
            celery_app, pool="solo", concurrency=1, queues=["applications"],
            perform_ping_check=False, shutdown_timeout=15,
        ):
            response = auth_client.post(
                f"/api/supervised-submissions/applications/{application_id}/operator-assisted/prepare"
            )
            assert response.status_code == 202, response.text
            dispatch = response.json()
            assert dispatch["task_id"]
            result = operator_tasks.prepare_operator_assisted_application_task.AsyncResult(
                dispatch["task_id"]
            ).get(timeout=90)
            assert result.get("success") is True, result
            assert result["automated_submission_authorized"] is False
            assert result["final_submit_clicked_by_jobtomatik"] is False
            assert result["handoff_public_id"]

            boundary = _assert_durable_boundary(application_id, result, metadata)
            assert state["releases"] == [True]
            assert state["runtime"].process.poll() is None
            actions = asyncio.run(_observe_retained_form(
                boundary["endpoint"], boundary["target_id"], evidence,
            ))
            _assert_owner_boundary(auth_client, application_id, boundary["public_id"])
            assert state["requests"] == [{"method": "GET", "url": LEVER_URL}]
            _write_receipt(evidence, dispatch, boundary, state["requests"], actions)
    finally:
        if state["runtime"] is not None:
            state["runtime"].terminate(remove_profile=True)
