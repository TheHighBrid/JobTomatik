from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from playwright.async_api import async_playwright

from app.main import app as fastapi_app
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.handoff import HandoffSessionEvent, HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.application_state import create_manual_review_task
from app.services.browser_runtime import controlled_page_target_id
from app.services.browser_runtime_base import launch_retainable_browser
from app.services.handoff_session import issue_handoff_session
from app.tasks import handoffs as handoff_tasks
from tests.conftest import TestingSessionLocal


_FIXTURE_HTML = b"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>JobTomatik Gate 3 synthetic handoff</title>
  <link rel="icon" href="data:,">
</head>
<body>
  <h1>Gate 3 synthetic application</h1>
  <p id="state">Human verification required</p>
  <button id="human-boundary" type="button">Complete synthetic human boundary</button>
  <script>
    window.gate3Observations = { humanClicks: 0, submits: 0 };
    document.querySelector('#human-boundary').addEventListener('click', () => {
      window.gate3Observations.humanClicks += 1;
      document.querySelector('#state').textContent = 'Application submitted';
      document.body.dataset.syntheticConfirmation = 'true';
    });
    document.addEventListener('submit', event => {
      event.preventDefault();
      window.gate3Observations.submits += 1;
    });
  </script>
</body>
</html>"""


class _FixtureServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append({"method": "GET", "path": self.path})
                if self.path != "/fixture":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(_FIXTURE_HTML)))
                self.end_headers()
                self.wfile.write(_FIXTURE_HTML)

            def do_POST(self):
                requests.append({"method": "POST", "path": self.path})
                self.send_error(405)

            def log_message(self, *_args):
                return None

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/fixture"
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
            name="gate3-handoff-fixture",
        )

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


async def _launch_retained_fixture(fixture_url: str, profile_dir: Path) -> dict:
    """Launch the real JobTomatik-owned browser and detach without terminating it."""
    async with async_playwright() as playwright:
        runtime = await launch_retainable_browser(
            playwright,
            profile_dir=profile_dir,
            headless=True,
        )
        response = await runtime.page.goto(
            fixture_url,
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        assert response is not None and response.status == 200
        target_id = await controlled_page_target_id(runtime.page)
        assert target_id
        button = await runtime.page.locator("#human-boundary").bounding_box()
        assert button is not None
        snapshot = await runtime.capture_snapshot(
            metadata={"synthetic_gate3": True, "controlled_page_target_id": target_id}
        )
        observations = await runtime.page.evaluate("window.gate3Observations")
        assert observations == {"humanClicks": 0, "submits": 0}
        return {
            "snapshot": snapshot,
            "target_id": target_id,
            "click": {
                "x": button["x"] + button["width"] / 2,
                "y": button["y"] + button["height"] / 2,
            },
        }


async def _inspect_retained_target(endpoint: str, target_id: str) -> dict:
    """Reconnect independently and prove the exact controlled target still exists."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint, timeout=5_000)
        matches = []
        for context in browser.contexts:
            for page in list(context.pages):
                if await controlled_page_target_id(page) == target_id:
                    matches.append(page)
        assert len(matches) == 1
        page = matches[0]
        return {
            "target_id": target_id,
            "url": page.url,
            "confirmation": await page.locator("body").inner_text(),
            "observations": await page.evaluate("window.gate3Observations"),
        }


def _process_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _wait_process_exit(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(0.05)
    return not _process_alive(pid)


def _copy_if_present(source: str | None, destination: Path) -> None:
    if not source:
        return
    path = Path(source)
    if path.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _write_evidence(payload: dict, frame: bytes, snapshot: dict) -> None:
    raw = os.getenv("JOBTOMATIK_GATE3_EVIDENCE_DIR", "").strip()
    if not raw:
        return
    root = Path(raw)
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    (root / "handoff-frame.png").write_bytes(frame)
    _copy_if_present(snapshot.get("screenshot_path"), root / "pre-handoff.png")
    _copy_if_present(snapshot.get("html_snapshot_path"), root / "pre-handoff.html")
    _copy_if_present(snapshot.get("storage_state_path"), root / "storage-state.json")


def test_gate3_real_chromium_authenticated_handoff_resumes_same_target_and_reconciles_confirmation(
    auth_client,
    tmp_path,
    monkeypatch,
):
    """Exercise the retained browser through the real authenticated handoff API."""
    handoff_root = tmp_path / "handoff-sessions"
    monkeypatch.setenv("HANDOFF_STORAGE_DIR", str(handoff_root))
    monkeypatch.setattr(handoff_tasks, "SessionLocal", TestingSessionLocal)

    with _FixtureServer() as fixture:
        launched = asyncio.run(
            _launch_retained_fixture(fixture.url, tmp_path / "chromium-profile")
        )
        snapshot = launched["snapshot"]
        target_id = launched["target_id"]
        click = launched["click"]
        browser_pid = int(snapshot["browser_process_id"])
        endpoint = str(snapshot["browser_endpoint"])
        assert _process_alive(browser_pid)
        assert httpx.get(f"{endpoint}/json/version", timeout=2).status_code == 200

        db = TestingSessionLocal()
        user = db.query(User).filter(User.email == "test@example.com").one()
        job = Job(
            external_id="gate3-onehost-handoff",
            title="Synthetic Gate 3 Role",
            company="JobTomatik Fixture",
            url=fixture.url,
            source=JobSource.manual,
            status=JobStatus.approved,
            raw_data={"application_method": "external_url", "selected_apply_url": fixture.url},
        )
        db.add(job)
        db.flush()
        application = Application(
            user_id=user.id,
            job_id=job.id,
            status=ApplicationStatus.pending,
            automation_state=ApplicationAutomationState.needs_review.value,
            submission_idempotency_key="gate3-onehost-handoff",
            cover_letter="Synthetic Gate 3 cover letter",
            application_target_url=fixture.url,
        )
        db.add(application)
        db.flush()
        review = create_manual_review_task(
            db,
            application,
            ManualReviewReason.captcha_detected,
            "Synthetic Gate 3 human boundary.",
            details={"synthetic_gate3": True, "submit_clicked": False},
            blocking_url=fixture.url,
            target_state=ApplicationAutomationState.needs_review,
        )
        db.flush()
        issued = issue_handoff_session(
            db,
            application,
            review,
            browser_provider=str(snapshot["browser_provider"]),
            browser_session_id=str(snapshot["browser_session_id"]),
            browser_endpoint=endpoint,
            browser_node_id=str(snapshot["browser_node_id"]),
            browser_process_id=browser_pid,
            browser_profile_path=str(snapshot["browser_profile_path"]),
            active_page_hint=str(snapshot["active_page_hint"]),
            current_url=str(snapshot["current_url"]),
            current_fingerprint=str(snapshot["current_fingerprint"]),
            storage_state_path=str(snapshot["storage_state_path"]),
            storage_state_hash=str(snapshot["storage_state_hash"]),
            screenshot_path=str(snapshot["screenshot_path"]),
            metadata={
                "synthetic_gate3": True,
                "dry_run": True,
                "adapter": "synthetic",
                "adapter_version": "gate3",
                "controlled_page_target_id": target_id,
            },
        )
        public_id = issued.session.public_id
        application_id = application.id
        review_id = review.id
        db.commit()
        db.close()

        unauthenticated = TestClient(fastapi_app)
        denied = unauthenticated.post(
            f"/api/handoffs/{public_id}/frame",
            json={"lease_token": "not-authorized"},
        )
        assert denied.status_code in {401, 403}

        bootstrap = auth_client.post(f"/api/handoffs/{public_id}/bootstrap")
        assert bootstrap.status_code == 200
        resume_token = bootstrap.json()["resume_token"]

        second_bootstrap = auth_client.post(f"/api/handoffs/{public_id}/bootstrap")
        assert second_bootstrap.status_code == 409

        bad_claim = auth_client.post(
            f"/api/handoffs/{public_id}/claim",
            json={"resume_token": "wrong-resume-token"},
        )
        assert bad_claim.status_code == 403

        claim = auth_client.post(
            f"/api/handoffs/{public_id}/claim",
            json={"resume_token": resume_token},
        )
        assert claim.status_code == 200
        lease_token = claim.json()["lease_token"]

        replayed_claim = auth_client.post(
            f"/api/handoffs/{public_id}/claim",
            json={"resume_token": resume_token},
        )
        assert replayed_claim.status_code == 409

        bad_frame = auth_client.post(
            f"/api/handoffs/{public_id}/frame",
            json={"lease_token": "wrong-lease-token"},
        )
        assert bad_frame.status_code == 403

        frame = auth_client.post(
            f"/api/handoffs/{public_id}/frame",
            json={"lease_token": lease_token},
        )
        assert frame.status_code == 200
        assert frame.headers["content-type"].startswith("image/png")
        assert len(frame.content) > 100

        action = auth_client.post(
            f"/api/handoffs/{public_id}/actions",
            json={
                "lease_token": lease_token,
                "action": "click",
                "x": click["x"],
                "y": click["y"],
            },
        )
        assert action.status_code == 200
        assert _process_alive(browser_pid)

        retained_after_action = asyncio.run(
            _inspect_retained_target(endpoint, target_id)
        )
        assert retained_after_action["url"] == fixture.url
        assert "Application submitted" in retained_after_action["confirmation"]
        assert retained_after_action["observations"] == {"humanClicks": 1, "submits": 0}

        completed = auth_client.post(
            f"/api/handoffs/{public_id}/complete",
            json={"lease_token": lease_token},
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == HandoffSessionStatus.ready_to_resume.value
        assert _process_alive(browser_pid)

        result = handoff_tasks.resume_handoff_session_task.run(public_id)
        assert result["success"] is True
        assert result["submission_confirmed"] is True
        assert result["ready_to_submit"] is False
        assert result["confirmation_evidence"]
        assert result["confirmation_evidence"][0]["is_sufficient"] is True

        db = TestingSessionLocal()
        refreshed_app = db.query(Application).filter(Application.id == application_id).one()
        refreshed_review = db.query(ManualReviewTask).filter(ManualReviewTask.id == review_id).one()
        refreshed_handoff = db.query(ManualHandoffSession).filter(
            ManualHandoffSession.public_id == public_id
        ).one()
        evidence = db.query(SubmissionEvidence).filter(
            SubmissionEvidence.application_id == application_id
        ).all()
        events = db.query(HandoffSessionEvent).filter(
            HandoffSessionEvent.handoff_session_id == refreshed_handoff.id
        ).order_by(HandoffSessionEvent.id.asc()).all()

        assert refreshed_app.status == ApplicationStatus.applied
        assert refreshed_app.automation_state == ApplicationAutomationState.confirmed.value
        assert refreshed_app.applied_at is not None
        assert refreshed_review.status == ManualReviewStatus.resolved.value
        assert refreshed_handoff.status == HandoffSessionStatus.completed.value
        assert len(evidence) == 1
        assert evidence[0].is_sufficient is True
        assert evidence[0].evidence_type in {"success_banner", "confirmation_page"}
        event_types = [item.event_type for item in events]
        assert "handoff_issued" in event_types
        assert "handoff_claimed" in event_types
        assert "handoff_ready_to_resume" in event_types
        assert "handoff_resume_started" in event_types
        assert "handoff_resume_completed" in event_types
        db.close()

        idempotent = handoff_tasks.resume_handoff_session_task.run(public_id)
        assert idempotent["success"] is True
        assert idempotent["idempotent"] is True

        assert _wait_process_exit(browser_pid)
        assert all(item["method"] == "GET" for item in fixture.requests)
        assert {item["path"] for item in fixture.requests} == {"/fixture"}

        evidence_payload = {
            "gate": 3,
            "proof": "onehost-retained-handoff",
            "synthetic": True,
            "browser": {
                "session_id": snapshot["browser_session_id"],
                "process_id": browser_pid,
                "endpoint": endpoint,
                "node_id": snapshot["browser_node_id"],
                "controlled_page_target_id": target_id,
                "process_alive_before_handoff": True,
                "same_target_after_action": retained_after_action["target_id"] == target_id,
                "process_terminated_after_reconciliation": not _process_alive(browser_pid),
            },
            "api": {
                "unauthenticated_frame_status": denied.status_code,
                "second_bootstrap_status": second_bootstrap.status_code,
                "bad_claim_status": bad_claim.status_code,
                "replayed_claim_status": replayed_claim.status_code,
                "bad_lease_status": bad_frame.status_code,
                "frame_status": frame.status_code,
                "action_status": action.status_code,
                "complete_status": completed.status_code,
            },
            "confirmation": {
                "submission_confirmed": result["submission_confirmed"],
                "evidence_count": len(evidence),
                "application_status": refreshed_app.status.value if hasattr(refreshed_app.status, "value") else str(refreshed_app.status),
                "automation_state": refreshed_app.automation_state,
                "review_status": refreshed_review.status.value if hasattr(refreshed_review.status, "value") else str(refreshed_review.status),
                "handoff_status": refreshed_handoff.status,
                "idempotent_resume": bool(idempotent.get("idempotent")),
            },
            "fixture": {
                "requests": list(fixture.requests),
                "human_clicks": retained_after_action["observations"]["humanClicks"],
                "submit_events": retained_after_action["observations"]["submits"],
            },
            "handoff_events": event_types,
            "verdict": "PASS",
            "violations": [],
        }
        _write_evidence(evidence_payload, frame.content, snapshot)
