"""Exercise an isolated production Compose deployment without employer traffic."""

import asyncio
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from alembic.config import Config
from alembic.script import ScriptDirectory
from playwright.async_api import async_playwright
from sqlalchemy import inspect, text

from app.auth import hash_password
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models.application import Application, ApplicationStatus
from app.models.job import Job
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services.application_attempt_jt5 import reserve_jt5_attempt
from app.services.application_attempt_lifecycle_jt5 import claim_jt5_attempt
from app.services.browser_runtime import launch_application_browser
from app.tasks.runtime import application_queue_canary

EMAIL = "onehost-smoke@example.invalid"
FIXTURE = "http://127.0.0.1:19190"


def require_isolated_smoke():
    """Refuse writes unless the harness explicitly selected an isolated stack."""
    if os.environ.get("JT5_ISOLATED_SMOKE") != "1":
        raise RuntimeError("This probe writes synthetic records; isolated smoke only")
    for name in (
        "ALLOW_REAL_APPLICATION_SUBMIT", "AUTOPILOT_ENABLED",
        "ALLOW_REAL_FOLLOWUP_SEND", "GREENHOUSE_SUPERVISED_PILOT_ENABLED",
        "LEVER_SUPERVISED_PILOT_ENABLED",
    ):
        if os.environ.get(name) != "false":
            raise RuntimeError(f"Unsafe smoke flag: {name}")


def smoke_password():
    return hmac.new(
        get_settings().secret_key.encode(), b"isolated-onehost-smoke", hashlib.sha256,
    ).hexdigest()


def database_probe(phase):
    """Verify durable schema and an interrupted JT5 claim across a restart."""
    assert engine.dialect.name == "postgresql"
    assert {"users", "applications", "submission_attempts"} <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        versions = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    heads = set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())
    assert versions == heads
    columns = {column["name"] for column in inspect(engine).get_columns("applications")}
    assert {"automation_state", "application_target_url", "submission_attempt_count"} <= columns
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=EMAIL).first()
        if phase == "before":
            assert user is None, "Smoke requires a fresh isolated database"
            user = User(email=EMAIL, hashed_password=hash_password(smoke_password()))
            job = Job(title="Synthetic smoke", company="Local fixture", url=FIXTURE)
            db.add_all([user, job])
            db.flush()
            application = Application(
                user_id=user.id, job_id=job.id, status=ApplicationStatus.pending,
                automation_state="ready_to_apply", application_target_url=FIXTURE,
                submission_idempotency_key="isolated-onehost-smoke",
            )
            db.add(application)
            db.flush()
            _, attempt = reserve_jt5_attempt(
                db, application_id=application.id, authenticated_user_id=user.id,
            )
            db.commit()
            assert claim_jt5_attempt(db, application.id, attempt.reference) is not None
            application.automation_state = "applying"
            db.commit()
        else:
            assert user is not None
            application = db.query(Application).filter_by(user_id=user.id).one()
            attempt = db.query(SubmissionAttempt).filter_by(application_id=application.id).one()
            assert attempt.status == "uncertain"
            assert application.automation_state == "submission_uncertain"
            assert attempt.attempt_metadata["automatic_retry_allowed"] is False
            assert claim_jt5_attempt(db, application.id, attempt.reference) is None
        return application.id


def api_queue_probe(application_id):
    """Use real HTTP authentication and the production worker's safe queue canary."""
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        assert client.get("/api/system/ready").status_code == 200
        assert client.get(f"/api/applications/{application_id}/jt5/status").status_code == 401
        login = client.post("/api/auth/login", data={"username": EMAIL, "password": smoke_password()})
        assert login.status_code == 200
        status = client.get(
            f"/api/applications/{application_id}/jt5/status",
            headers={"Authorization": "Bearer " + login.json()["access_token"]},
        )
        assert status.status_code == 200
        assert status.json()["automatic_retry_allowed"] is False
    revision = os.environ["JOBTOMATIK_RUNTIME_REVISION"]
    result = application_queue_canary.apply_async(args=[revision], queue="applications").get(timeout=45)
    assert result["ok"] and result["deployment_attested"]
    assert result["runtime_role"] == "worker"
    assert result["revision"] == revision


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<title>Local smoke</title><input aria-label='Synthetic name'>")

    def log_message(self, *_args):
        pass


async def browser_probe(phase):
    """Use the production owned-browser launcher and the persistent state volume."""
    server = ThreadingHTTPServer(("127.0.0.1", 19190), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        async with async_playwright() as playwright:
            runtime = await launch_application_browser(playwright)
            try:
                async def local_only(route):
                    if route.request.url.startswith(FIXTURE + "/"):
                        await route.continue_()
                    else:
                        await route.abort()

                await runtime.context.route("**/*", local_only)
                await runtime.page.goto(FIXTURE + "/", wait_until="domcontentloaded")
                await runtime.page.get_by_label("Synthetic name").fill("Synthetic OneHost")
                marker = os.environ["JOBTOMATIK_RUNTIME_REVISION"]
                if phase == "before":
                    await runtime.page.evaluate(
                        "value => localStorage.setItem('jt5-smoke', value)", marker
                    )
                    await runtime.context.storage_state()
                else:
                    assert await runtime.page.evaluate("localStorage.getItem('jt5-smoke')") == marker
                assert Path(runtime.browser_profile_path).is_dir()
                await runtime.browser.close()
                deadline = time.monotonic() + 15
                while runtime.process.poll() is None and time.monotonic() < deadline:
                    await asyncio.sleep(0.25)
            finally:
                runtime.terminate(remove_profile=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert httpx.get("http://127.0.0.1:8000/api/system/ready", timeout=10).status_code == 200


def main():
    require_isolated_smoke()
    component, phase = sys.argv[1:]
    assert component in {"api", "browser"} and phase in {"before", "after"}
    if component == "api":
        api_queue_probe(database_probe(phase))
    else:
        asyncio.run(browser_probe(phase))
    print(json.dumps({
        "component": component, "phase": phase, "status": "passed",
        "revision": os.environ["JOBTOMATIK_RUNTIME_REVISION"],
        "synthetic": True, "employer_traffic": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
