#!/usr/bin/env python3
"""Prove FastAPI -> Redis/Celery -> owned Chromium against the local fixture."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.auth import create_access_token, hash_password
from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User


API_URL = str(os.getenv("JOBTOMATIK_ONEHOST_API_URL") or "http://backend:8000").rstrip("/")
FIXTURE_URL = str(
    os.getenv("JOBTOMATIK_ONEHOST_FIXTURE_URL")
    or "http://fixture:8000/onehost_http_form.html"
).strip()


def _request_json(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: bytes | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Unsupported API URL: {url!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Credential-bearing API URLs are forbidden")

    connection_type = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        if response.status >= 400:
            raise RuntimeError(
                f"API request failed with HTTP {response.status}: {body[:500]}"
            )
        return json.loads(body) if body else {}
    finally:
        connection.close()


def _wait_for_api(timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            payload = _request_json(f"{API_URL}/api/system/ready", timeout=3)
            if payload:
                return
        except (OSError, http.client.HTTPException, RuntimeError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"FastAPI did not become ready: {last_error}")


def _seed_run(index: int) -> tuple[int, str, str]:
    email = f"phase0-run-{index:03d}@example.test"
    db = SessionLocal()
    try:
        user = User(
            email=email,
            hashed_password=hash_password("phase0-proof-only"),
            full_name="Fixture Candidate",
            profile_data={},
            automation_settings={},
        )
        db.add(user)
        db.flush()

        job = Job(
            external_id=f"phase0-{index:03d}",
            title="Synthetic Phase 0 Application",
            company="JobTomatik Fixture",
            location="Local fixture",
            description="Synthetic fixture used only for the recovery contract.",
            url=FIXTURE_URL,
            source=JobSource.manual,
            status=JobStatus.approved,
            relevance_score=1.0,
            raw_data={
                "application_method": "external_url",
                "selected_apply_url": FIXTURE_URL,
                "reason": "Phase 0 synthetic fixture",
            },
        )
        db.add(job)
        db.flush()

        application = Application(
            user_id=user.id,
            job_id=job.id,
            status=ApplicationStatus.pending,
            automation_state=ApplicationAutomationState.ready_to_apply.value,
            source_listing_url=FIXTURE_URL,
            application_target_url=FIXTURE_URL,
            application_target_status="resolved",
            cover_letter="Synthetic Phase 0 cover letter.",
            submission_idempotency_key=f"phase0:{index:03d}",
        )
        db.add(application)
        db.commit()
        token = create_access_token({"sub": str(user.id)})
        return application.id, token, email
    finally:
        db.close()


def _dispatch(application_id: int, token: str) -> str:
    payload = _request_json(
        f"{API_URL}/api/applications/{application_id}/submit?dry_run=true",
        method="POST",
        token=token,
        payload=b"",
        timeout=10,
    )
    task_id = str(payload.get("task_id") or "")
    if not task_id or payload.get("status") != "queued" or payload.get("dry_run") is not True:
        raise RuntimeError(f"FastAPI did not queue the expected dry-run task: {payload}")
    return task_id


def _wait_for_task(task_id: str, timeout_seconds: int = 120) -> tuple[str, Any]:
    result = celery_app.AsyncResult(task_id)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state = str(result.state)
        if result.ready():
            if state != "SUCCESS":
                raise RuntimeError(f"Celery task {task_id} ended in {state}: {result.result!r}")
            return state, result.result
        time.sleep(0.5)
    raise RuntimeError(f"Celery task {task_id} did not finish within {timeout_seconds}s")


def _database_evidence(application_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).one()
        events = (
            db.query(ApplicationEvent)
            .filter(ApplicationEvent.application_id == application_id)
            .order_by(ApplicationEvent.id.asc())
            .all()
        )
        return {
            "status": application.status.value,
            "automation_state": application.automation_state,
            "submission_attempt_count": application.submission_attempt_count,
            "automation_log": application.automation_log or [],
            "events": [event.event_type for event in events],
        }
    finally:
        db.close()


def _verify_trace(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f"Trace is corrupt: {path}")
        if not any(name.endswith(".trace") for name in archive.namelist()):
            raise RuntimeError(f"Trace payload is incomplete: {path}")
    payload = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _verify_run(
    output_dir: Path,
    *,
    index: int,
    application_id: int,
    email: str,
    task_id: str,
    task_state: str,
    task_result: dict[str, Any],
) -> dict[str, Any]:
    run_token = email.split("@", 1)[0]
    browser_dir = output_dir / "browser" / run_token
    browser_evidence_path = browser_dir / "browser-evidence.json"
    trace_path = browser_dir / "trace.zip"
    if not browser_evidence_path.is_file():
        raise RuntimeError(f"Browser evidence was not persisted: {browser_evidence_path}")
    browser_evidence = json.loads(browser_evidence_path.read_text(encoding="utf-8"))
    trace = _verify_trace(trace_path)
    database = _database_evidence(application_id)

    checks = {
        "api_dispatched_celery_task": bool(task_id) and task_state == "SUCCESS",
        "real_application_task_returned": task_result.get("phase0_owned_browser_proof") is True,
        "dry_run_only": task_result.get("dry_run") is True and task_result.get("submitted_at") is None,
        "fields_filled": int(task_result.get("fields_filled") or 0) >= 3,
        "ready_without_submit": task_result.get("success") is True
        and task_result.get("ready_to_submit") is True
        and task_result.get("requires_manual_review") is not True,
        "state_returned_to_ready": database["status"] == ApplicationStatus.pending.value
        and database["automation_state"] == ApplicationAutomationState.ready_to_apply.value,
        "attempt_checkpointed": int(database["submission_attempt_count"] or 0) == 1,
        "state_events_persisted": "application_attempt_started" in database["events"]
        and "dry_run_completed" in database["events"],
        "browser_values_verified": browser_evidence.get("checks", {}).get("values_verified") is True,
        "submit_not_clicked": browser_evidence.get("checks", {}).get("submit_not_clicked") is True,
        "network_is_fixture_only": browser_evidence.get("checks", {}).get("no_nonfixture_requests") is True,
        "browser_and_driver_shutdown": browser_evidence.get("checks", {}).get("browser_and_driver_shutdown") is True,
        "trace_retained": browser_evidence.get("checks", {}).get("trace_retained") is True,
    }

    record = {
        "run": index,
        "synthetic": True,
        "application_id": application_id,
        "task_id": task_id,
        "task_state": task_state,
        "task_result": task_result,
        "database": database,
        "browser_evidence": browser_evidence,
        "trace": trace,
        "checks": checks,
        "status": "passed" if all(checks.values()) else "failed",
    }
    run_dir = output_dir / f"run-{index:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if record["status"] != "passed":
        failed = [name for name, value in checks.items() if not value]
        raise RuntimeError(f"Phase 0 integration checks failed: {failed}")
    return record


def run_gate(output_dir: Path, repeats: int, revision: str) -> dict[str, Any]:
    if repeats < 3:
        raise ValueError("Phase 0 integration proof requires at least three independent API/Celery runs")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "gate": "onehost-api-celery-phase0",
        "synthetic": True,
        "api_celery_dispatch_proven": False,
        "employer_certification": False,
        "repository_revision": revision,
        "requested_runs": repeats,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "runs": [],
        "status": "failed",
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    _wait_for_api()
    for index in range(1, repeats + 1):
        application_id, token, email = _seed_run(index)
        task_id = _dispatch(application_id, token)
        task_state, task_result = _wait_for_task(task_id)
        if not isinstance(task_result, dict):
            raise RuntimeError(f"Application task returned unexpected payload: {task_result!r}")
        record = _verify_run(
            output_dir,
            index=index,
            application_id=application_id,
            email=email,
            task_id=task_id,
            task_state=task_state,
            task_result=task_result,
        )
        summary["runs"].append({
            "run": index,
            "application_id": application_id,
            "task_id": task_id,
            "status": record["status"],
            "evidence": f"run-{index:03d}/evidence.json",
        })
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    summary["api_celery_dispatch_proven"] = True
    summary["status"] = "passed"
    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--revision",
        default=str(os.getenv("JOBTOMATIK_RUNTIME_REVISION") or "unattested-local"),
    )
    args = parser.parse_args()
    try:
        summary = run_gate(args.output_dir, args.repeats, args.revision)
    except Exception as exc:
        failure_path = args.output_dir / "failure.json"
        args.output_dir.mkdir(parents=True, exist_ok=True)
        failure_path.write_text(
            json.dumps(
                {
                    "gate": "onehost-api-celery-phase0",
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {str(exc)[:1000]}",
                    "repository_revision": args.revision,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        raise
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
