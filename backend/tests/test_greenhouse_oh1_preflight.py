from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.models.application import Application, ApplicationAutomationState, ApplicationStatus
from app.models.job import Job, JobSource, JobStatus
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services import greenhouse_oh1_preflight as preflight
from app.services.greenhouse_oh1_preflight import render_preflight_report, run_gh_oh1_preflight
from tests.conftest import TestingSessionLocal


def _load_cli():
    path = Path(__file__).resolve().parents[1] / "scripts" / "jobtomatik.py"
    spec = importlib.util.spec_from_file_location("jobtomatik_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


jobtomatik_cli = _load_cli()


GREENHOUSE_URL = "https://job-boards.greenhouse.io/safeco/jobs/123456"


class _Settings:
    allow_real_application_submit = False
    greenhouse_supervised_pilot_enabled = False


class _Operations:
    def __init__(self, armed: bool) -> None:
        self.global_kill_switch = armed


def _healthy(**_kwargs):
    return {"ok": True}


def _schema(_url: str):
    return {
        "verified": True,
        "questions": [
            {"label": "Years of Python", "required": True},
            {"label": "Work authorization", "required": True},
        ],
    }


def _policies():
    return [
        {
            "question_text": "Years of Python",
            "mode": "answer",
            "allow_autofill": True,
            "confirmed_at": "2026-10-06T00:00:00Z",
            "provenance": "owner_confirmed",
            "is_active": True,
        }
    ]


@pytest.fixture
def application_id(auth_client, tmp_path, monkeypatch):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nGH-OH1 fixture\n")
    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").one()
    user.full_name = "Mohamed Alem"
    user.resume_path = str(resume)
    user.resume_filename = "resume.pdf"
    job = Job(
        external_id="gh-oh1-preflight",
        title="Fraud Operations Analyst",
        company="SafeCo",
        url=GREENHOUSE_URL,
        source=JobSource.manual,
        status=JobStatus.approved,
        raw_data={"selected_apply_url": GREENHOUSE_URL},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        cover_letter="Exact GH-OH1 cover letter.",
        submission_idempotency_key="gh-oh1-idem-1",
    )
    db.add(application)
    db.commit()
    application_id = application.id
    db.close()
    monkeypatch.setattr(preflight, "get_settings", lambda: _Settings())
    monkeypatch.setattr(preflight, "get_operations_settings", lambda: _Operations(True))
    return application_id


def _run(application_id, **overrides):
    db = TestingSessionLocal()
    try:
        kwargs = {
            "schema_probe": _schema,
            "onehost_probe": _healthy,
            "browser_probe": _healthy,
            "evidence_probe": _healthy,
            "policy_override": _policies(),
        }
        kwargs.update(overrides)
        return run_gh_oh1_preflight(db, application_id, **kwargs)
    finally:
        db.close()


def test_ready_report_keeps_submit_authority_closed(application_id):
    report = _run(application_id)
    rendered = render_preflight_report(report)
    assert report["ready"] is True
    assert report["submit_attempted"] is False
    assert report["final_submit_authority"]["status"] == "CLOSED"
    assert "READY FOR SUPERVISED EXECUTION" in rendered
    assert "Final submit authority  CLOSED" in rendered
    assert all(report["checks"][name]["status"] == "PASS" for name in preflight.CHECK_ORDER)


def test_preflight_does_not_write_application_events(application_id):
    db = TestingSessionLocal()
    before = db.query(Application).filter(Application.id == application_id).one().automation_state
    db.close()
    report = _run(application_id)
    db = TestingSessionLocal()
    after = db.query(Application).filter(Application.id == application_id).one()
    db.close()
    assert report["ready"] is True
    assert after.automation_state == before


def test_missing_resume_fails_closed(application_id):
    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").one()
    user.resume_path = None
    db.commit()
    db.close()
    report = _run(application_id)
    assert report["ready"] is False
    assert report["checks"]["resume_binding"]["reason"] == "resume_hash_missing"


def test_missing_required_policy_fails_closed(application_id):
    report = _run(application_id, policy_override=[])
    assert report["ready"] is False
    assert report["checks"]["answer_policies"]["reason"] == "required_answer_policy_missing"


def test_prohibited_autofill_fails_closed(application_id):
    policies = _policies() + [
        {
            "question_text": "Work authorization",
            "mode": "answer",
            "allow_autofill": True,
            "confirmed_at": "2026-10-06T00:00:00Z",
            "provenance": "owner_confirmed",
            "is_active": True,
        }
    ]
    report = _run(application_id, policy_override=policies)
    assert report["checks"]["answer_policies"]["reason"] == "prohibited_question_would_be_autofilled"


def test_unverified_schema_fails_closed(application_id):
    report = _run(application_id, schema_probe=lambda _url: {"verified": False, "blocker": "schema_unavailable"})
    assert report["checks"]["answer_policies"]["reason"] == "schema_unavailable"


def test_duplicate_target_is_blocked(application_id):
    db = TestingSessionLocal()
    current = db.query(Application).filter(Application.id == application_id).one()
    duplicate = Application(
        user_id=current.user_id,
        job_id=current.job_id,
        status=ApplicationStatus.applied,
        automation_state=ApplicationAutomationState.confirmed.value,
        submission_idempotency_key="gh-oh1-idem-other",
    )
    db.add(duplicate)
    db.commit()
    db.close()
    report = _run(application_id)
    assert report["checks"]["duplicate_check"]["reason"] == "duplicate_application_blocked"


def test_disarmed_kill_switch_fails(application_id, monkeypatch):
    monkeypatch.setattr(preflight, "get_operations_settings", lambda: _Operations(False))
    report = _run(application_id)
    assert report["checks"]["kill_switch"]["reason"] == "kill_switch_not_armed"


def test_open_submit_authority_fails(application_id, monkeypatch):
    class OpenSettings(_Settings):
        allow_real_application_submit = True

    monkeypatch.setattr(preflight, "get_settings", lambda: OpenSettings())
    report = _run(application_id)
    assert report["ready"] is False
    assert report["final_submit_authority"]["status"] == "OPEN"


def test_mismatched_approval_fails(application_id):
    db = TestingSessionLocal()
    current = db.query(Application).filter(Application.id == application_id).one()
    db.add(
        SubmissionApproval(
            application_id=current.id,
            user_id=current.user_id,
            platform="greenhouse",
            status=SubmissionApprovalStatus.active.value,
            employer="Other Co",
            role="Other Role",
            application_url=GREENHOUSE_URL,
            submission_idempotency_key="gh-oh1-idem-1",
            profile_snapshot_hash="a" * 64,
            resume_hash="b" * 64,
            cover_letter_hash="c" * 64,
            answer_payload_hash="d" * 64,
            combined_payload_hash="e" * 64,
            reference="ghsup-test",
            expires_at=datetime.utcnow() + timedelta(minutes=20),
        )
    )
    db.commit()
    db.close()
    report = _run(application_id)
    assert report["approval_binding"]["reason"] == "approval_binding_mismatch"
    assert report["ready"] is False


def test_cli_prints_ready_report_and_never_submits(application_id, capsys, monkeypatch):
    monkeypatch.setattr(jobtomatik_cli, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(preflight, "default_schema_probe", _schema)
    monkeypatch.setattr(preflight, "default_onehost_probe", _healthy)
    monkeypatch.setattr(preflight, "default_browser_probe", _healthy)
    monkeypatch.setattr(preflight, "default_evidence_probe", _healthy)
    monkeypatch.setattr(preflight, "load_runtime_policies", lambda *args, **kwargs: _policies())
    exit_code = jobtomatik_cli.main(["greenhouse", "preflight", str(application_id), "--json"])
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert exit_code == 0
    assert payload["submit_attempted"] is False
    assert payload["ready"] is True


def test_command_source_has_no_submit_path():
    source = Path(preflight.__file__).read_text(encoding="utf-8")
    cli = Path(jobtomatik_cli.__file__).read_text(encoding="utf-8")
    assert "submit_application_task" not in source
    assert "issue_supervised_approval" not in source
    assert "submit_application_task" not in cli
