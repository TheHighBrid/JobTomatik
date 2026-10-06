"""Fail-closed GH-OH1 preflight.

This module prepares a Greenhouse application for supervised OneHost execution.
It never submits, never issues an approval, and never promotes application state.
A ready report means the mechanical gates passed and final-submit authority is
still closed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.job import Job
from app.models.submission_approval import (
    SubmissionApproval,
    SubmissionApprovalStatus,
)
from app.models.user import User
from app.services.answer_policy import load_runtime_policies
from app.services.ats_greenhouse import parse_greenhouse_job_url
from app.services.operations_settings import get_operations_settings
from app.services.supervised_submission import (
    build_submission_snapshot,
    _greenhouse_form_schema_status,
)

CHECK_ORDER = (
    "target_identity",
    "applicant_dossier",
    "resume_binding",
    "answer_policies",
    "duplicate_check",
    "onehost_health",
    "browser_affinity",
    "evidence_storage",
    "kill_switch",
)

CHECK_LABELS = {
    "target_identity": "Target identity",
    "applicant_dossier": "Applicant dossier",
    "resume_binding": "Resume binding",
    "answer_policies": "Answer policies",
    "duplicate_check": "Duplicate check",
    "onehost_health": "OneHost health",
    "browser_affinity": "Browser affinity",
    "evidence_storage": "Evidence storage",
    "kill_switch": "Kill switch",
}

IN_FLIGHT_STATES = {
    ApplicationAutomationState.applying.value,
    ApplicationAutomationState.submitted.value,
    ApplicationAutomationState.confirmed.value,
    ApplicationAutomationState.submission_uncertain.value,
}
DUPLICATE_STATUSES = {
    ApplicationStatus.applied,
    ApplicationStatus.interviewing,
    ApplicationStatus.offer,
}
BLOCKED_BROWSER_MARKERS = (
    "termux",
    "native-chrome",
    "native_chrome",
    "adb",
    "proot",
)
PROHIBITED_MARKERS = (
    "work authorization",
    "authorized to work",
    "sponsorship",
    "visa",
    "demographic",
    "gender",
    "race",
    "ethnicity",
    "veteran",
    "disability",
    "consent",
    "gdpr",
    "equal opportunity",
    "eeo",
    "captcha",
    "mfa",
    "password",
    "login",
    "assessment",
    "social security",
    "date of birth",
    "legal name change",
)
Probe = Callable[[], Mapping[str, Any]]


def _check(status: str, **detail: Any) -> Dict[str, Any]:
    payload = {"status": status}
    payload.update(detail)
    return payload


def _fail(reason: str, **detail: Any) -> Dict[str, Any]:
    return _check("FAIL", reason=reason, **detail)


def _pass(**detail: Any) -> Dict[str, Any]:
    return _check("PASS", **detail)


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _question_text(question: Mapping[str, Any]) -> str:
    return _normalize(
        question.get("label")
        or question.get("question")
        or question.get("text")
        or question.get("name")
    )


def _is_prohibited(text: str) -> bool:
    return any(marker in text for marker in PROHIBITED_MARKERS)


def _policy_text(policy: Mapping[str, Any]) -> str:
    return _normalize(
        policy.get("question_text")
        or policy.get("label")
        or policy.get("canonical_key")
        or policy.get("category")
    )


def _policy_matches(policy: Mapping[str, Any], question: str) -> bool:
    policy_text = _policy_text(policy)
    return bool(policy_text) and (policy_text in question or question in policy_text)


def _explicit_policy(policy: Mapping[str, Any]) -> bool:
    mode = _normalize(policy.get("mode"))
    provenance = _normalize(policy.get("provenance"))
    return bool(
        policy.get("is_active", True)
        and policy.get("confirmed_at")
        and mode in {"answer", "decline"}
        and provenance
        and provenance != "unknown"
    )


def default_schema_probe(application_url: str) -> Dict[str, Any]:
    """Live public schema probe. Failure stays fail-closed and does not submit."""

    try:
        return dict(_greenhouse_form_schema_status(application_url))
    except Exception as exc:  # noqa: BLE001 - preflight must fail closed
        return {"checked": True, "verified": False, "blocker": f"schema_probe_error:{exc.__class__.__name__}"}


def default_onehost_probe() -> Dict[str, Any]:
    base = os.environ.get("ONEHOST_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    worker_url = os.environ.get("ONEHOST_WORKER_HEALTH_URL", "").strip()
    try:
        response = httpx.get(f"{base}/api/system/ready", timeout=3.0)
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        api_ready = response.status_code == 200 and payload.get("status") == "ready"
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"onehost_api_unreachable:{exc.__class__.__name__}"}
    if not api_ready:
        return {"ok": False, "reason": "onehost_api_not_ready"}
    if not worker_url:
        return {"ok": False, "reason": "onehost_worker_unverified"}
    try:
        worker = httpx.get(worker_url, timeout=3.0)
        worker_ok = worker.status_code == 200
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"onehost_worker_unreachable:{exc.__class__.__name__}"}
    if not worker_ok:
        return {"ok": False, "reason": "onehost_worker_not_ready"}
    return {"ok": True, "api": "ready", "worker": "ready", "database": "ready"}


def default_browser_probe() -> Dict[str, Any]:
    profile = os.environ.get("APPLICATION_BROWSER_PROFILE_DIR", "").strip()
    if not profile:
        return {"ok": False, "reason": "browser_profile_unconfigured"}
    lowered = profile.lower()
    if any(marker in lowered for marker in BLOCKED_BROWSER_MARKERS):
        return {"ok": False, "reason": "browser_affinity_not_onehost", "profile": profile}
    path = Path(profile)
    if not path.is_dir():
        return {"ok": False, "reason": "browser_profile_missing", "profile": profile}
    return {"ok": True, "owner": "onehost", "profile": profile}


def default_evidence_probe() -> Dict[str, Any]:
    configured = os.environ.get("JOBTOMATIK_GH_OH1_EVIDENCE_DIR", "").strip()
    directory = Path(configured) if configured else Path("evidence") / "gh-oh1-preflight"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-probe"
        probe.write_text("gh-oh1-preflight", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return {"ok": False, "reason": f"evidence_storage_not_writable:{exc.__class__.__name__}"}
    return {"ok": True, "path": str(directory)}


def _load_application(db: Session, application_id: int) -> tuple[Optional[Application], Optional[User], Optional[Job], Optional[str]]:
    application = db.query(Application).filter(Application.id == application_id).first()
    if application is None:
        return None, None, None, "application_not_found"
    user = db.query(User).filter(User.id == application.user_id).first()
    job = db.query(Job).filter(Job.id == application.job_id).first()
    if user is None or job is None:
        return application, user, job, "application_owner_or_job_missing"
    return application, user, job, None


def _target_identity(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    employer = str(snapshot.get("employer") or "").strip()
    role = str(snapshot.get("role") or "").strip()
    url = str(snapshot.get("application_url") or "").strip()
    parsed = urlparse(url)
    board, job_id = parse_greenhouse_job_url(url)
    if snapshot.get("platform") != "greenhouse":
        return _fail("target_not_greenhouse", platform=snapshot.get("platform"))
    if not employer or not role:
        return _fail("employer_or_role_missing")
    if not board or not job_id:
        return _fail("greenhouse_url_not_exact", url=url)
    host = (parsed.hostname or "").lower()
    if "greenhouse" not in host and "gh_jid" not in url:
        return _fail("greenhouse_host_unverified", host=host)
    return _pass(employer=employer, role=role, url=url, board_token=board, job_id=job_id)


def _dossier(snapshot: Mapping[str, Any], user: User) -> Dict[str, Any]:
    if not str(user.full_name or "").strip() or not str(user.email or "").strip():
        return _fail("applicant_identity_incomplete")
    if not snapshot.get("profile_snapshot_hash"):
        return _fail("profile_hash_missing")
    if int(snapshot.get("user_id") or 0) != int(user.id):
        return _fail("dossier_user_mismatch")
    return _pass(applicant=user.full_name, email=user.email, profile_hash=snapshot.get("profile_snapshot_hash"))


def _resume_binding(snapshot: Mapping[str, Any], application: Application, user: User) -> Dict[str, Any]:
    resume_hash = snapshot.get("resume_hash")
    if not user.resume_path or not resume_hash:
        return _fail("resume_hash_missing")
    path = Path(str(user.resume_path))
    if not path.is_file():
        return _fail("resume_file_missing")
    cover_hash = snapshot.get("cover_letter_hash")
    if not cover_hash:
        return _fail("cover_letter_hash_missing")
    if bool(application.cover_letter) != bool(snapshot.get("cover_letter_present")):
        return _fail("cover_letter_binding_mismatch")
    return _pass(
        resume_hash=resume_hash,
        cover_letter_hash=cover_hash,
        cover_letter_present=bool(snapshot.get("cover_letter_present")),
    )


def _answer_policies(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    snapshot: Mapping[str, Any],
    schema_probe: Optional[Callable[[str], Mapping[str, Any]]],
    policy_override: Optional[list[Mapping[str, Any]]],
) -> Dict[str, Any]:
    if not snapshot.get("answer_payload_hash"):
        return _fail("answer_payload_hash_missing")
    policies = list(policy_override) if policy_override is not None else list(
        load_runtime_policies(
            db,
            user.id,
            target_url=str(snapshot.get("application_url") or ""),
            company=str(job.company or ""),
        )
    )
    probe = schema_probe or default_schema_probe
    schema = dict(probe(str(snapshot.get("application_url") or "")))
    if schema.get("verified") is not True:
        return _fail(str(schema.get("blocker") or "answer_policy_schema_unverified"), schema=schema)
    questions = list(schema.get("questions") or [])
    required = [item for item in questions if isinstance(item, Mapping) and item.get("required")]
    missing: list[str] = []
    prohibited_autofill: list[str] = []
    for question in required:
        text = _question_text(question)
        if not text:
            return _fail("required_question_unlabeled")
        matched = [policy for policy in policies if _policy_matches(policy, text)]
        if _is_prohibited(text):
            if any(policy.get("allow_autofill") and _explicit_policy(policy) and _normalize(policy.get("mode")) == "answer" for policy in matched):
                prohibited_autofill.append(text)
            continue
        if not any(_explicit_policy(policy) for policy in matched):
            missing.append(text)
    if prohibited_autofill:
        return _fail("prohibited_question_would_be_autofilled", questions=prohibited_autofill)
    if missing:
        return _fail("required_answer_policy_missing", questions=missing)
    return _pass(policy_count=len(policies), required_question_count=len(required), schema_verified=True)


def _duplicate_check(db: Session, application: Application, job: Job, snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    key = str(snapshot.get("submission_idempotency_key") or "").strip()
    if not key:
        return _fail("missing_submission_idempotency_key")
    reused = (
        db.query(Application.id)
        .filter(Application.submission_idempotency_key == key, Application.id != application.id)
        .first()
    )
    if reused:
        return _fail("idempotency_key_reused", other_application_id=reused[0])
    board, job_id = parse_greenhouse_job_url(str(snapshot.get("application_url") or ""))
    siblings = (
        db.query(Application, Job)
        .join(Job, Job.id == Application.job_id)
        .filter(Application.user_id == application.user_id, Application.id != application.id)
        .all()
    )
    for other, other_job in siblings:
        other_board, other_job_id = parse_greenhouse_job_url(str(other_job.url or ""))
        same_target = other_job_id and other_job_id == job_id and other_board == board
        same_employer_role = (
            _normalize(other_job.company) == _normalize(job.company)
            and _normalize(other_job.title) == _normalize(job.title)
            and same_target
        )
        inflight = (other.automation_state in IN_FLIGHT_STATES) or (other.status in DUPLICATE_STATUSES)
        if same_employer_role and inflight:
            return _fail("duplicate_application_blocked", other_application_id=other.id)
    if application.automation_state in {
        ApplicationAutomationState.submitted.value,
        ApplicationAutomationState.confirmed.value,
    }:
        return _fail("application_already_submitted", state=application.automation_state)
    return _pass(idempotency_key=key)


def _approval_binding(db: Session, application: Application, snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    approvals = (
        db.query(SubmissionApproval)
        .filter(SubmissionApproval.application_id == application.id)
        .all()
    )
    active = [item for item in approvals if item.status == SubmissionApprovalStatus.active.value]
    mismatched = [
        item.reference
        for item in active
        if item.combined_payload_hash != snapshot.get("combined_payload_hash")
        or _normalize(item.employer) != _normalize(snapshot.get("employer"))
        or _normalize(item.role) != _normalize(snapshot.get("role"))
        or str(item.application_url or "").strip() != str(snapshot.get("application_url") or "").strip()
    ]
    if mismatched:
        return _fail("approval_binding_mismatch", references=mismatched)
    return _pass(active_approval_count=len(active), grants_submit=False)


def _authority(settings: Any) -> Dict[str, Any]:
    live = bool(getattr(settings, "allow_real_application_submit", False))
    pilot = bool(getattr(settings, "greenhouse_supervised_pilot_enabled", False))
    if live or pilot:
        return {
            "status": "OPEN",
            "reason": "final_submit_authority_unexpectedly_open",
            "global_live_submit_enabled": live,
            "platform_pilot_enabled": pilot,
        }
    return {
        "status": "CLOSED",
        "global_live_submit_enabled": False,
        "platform_pilot_enabled": False,
        "grants_submit": False,
    }


def run_gh_oh1_preflight(
    db: Session,
    application_id: int,
    *,
    schema_probe: Optional[Callable[[str], Mapping[str, Any]]] = None,
    onehost_probe: Optional[Probe] = None,
    browser_probe: Optional[Probe] = None,
    evidence_probe: Optional[Probe] = None,
    policy_override: Optional[list[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return a read-only GH-OH1 preflight report. This function does not submit."""

    application, user, job, load_error = _load_application(db, application_id)
    if load_error or application is None or user is None or job is None:
        report = {
            "kind": "gh-oh1-preflight",
            "ready": False,
            "submit_attempted": False,
            "application_id": application_id,
            "checks": {name: _fail(load_error or "application_not_found") for name in CHECK_ORDER},
            "approval_binding": _fail(load_error or "application_not_found"),
            "final_submit_authority": {"status": "CLOSED", "grants_submit": False},
            "verdict": "NOT READY",
        }
        return report

    snapshot = build_submission_snapshot(db, application, user, job)
    checks = {
        "target_identity": _target_identity(snapshot),
        "applicant_dossier": _dossier(snapshot, user),
        "resume_binding": _resume_binding(snapshot, application, user),
        "answer_policies": _answer_policies(
            db, application, user, job, snapshot, schema_probe, policy_override
        ),
        "duplicate_check": _duplicate_check(db, application, job, snapshot),
        "onehost_health": _external_check(onehost_probe or default_onehost_probe, "onehost_unhealthy"),
        "browser_affinity": _external_check(browser_probe or default_browser_probe, "browser_affinity_unverified"),
        "evidence_storage": _external_check(evidence_probe or default_evidence_probe, "evidence_storage_unverified"),
        "kill_switch": _kill_switch(),
    }
    approval = _approval_binding(db, application, snapshot)
    authority = _authority(get_settings())
    ready = all(item.get("status") == "PASS" for item in checks.values()) and approval.get("status") == "PASS" and authority.get("status") == "CLOSED"
    return {
        "kind": "gh-oh1-preflight",
        "ready": ready,
        "submit_attempted": False,
        "application_id": application.id,
        "employer": snapshot.get("employer"),
        "role": snapshot.get("role"),
        "application_url": snapshot.get("application_url"),
        "combined_payload_hash": snapshot.get("combined_payload_hash"),
        "checks": checks,
        "approval_binding": approval,
        "final_submit_authority": authority,
        "verdict": "READY FOR SUPERVISED EXECUTION" if ready else "NOT READY",
    }


def _external_check(probe: Probe, fallback: str) -> Dict[str, Any]:
    try:
        result = dict(probe())
    except Exception as exc:  # noqa: BLE001
        return _fail(f"{fallback}:{exc.__class__.__name__}")
    if result.get("ok") is True:
        return _pass(**{key: value for key, value in result.items() if key != "ok"})
    return _fail(str(result.get("reason") or fallback), **{key: value for key, value in result.items() if key not in {"ok", "reason"}})


def _kill_switch() -> Dict[str, Any]:
    operations = get_operations_settings()
    if operations.global_kill_switch is not True:
        return _fail("kill_switch_not_armed")
    return _pass(armed=True, flag="AUTOMATION_GLOBAL_KILL_SWITCH")


def render_preflight_report(report: Mapping[str, Any]) -> str:
    lines = ["GH-OH1 PREFLIGHT"]
    checks = dict(report.get("checks") or {})
    for name in CHECK_ORDER:
        label = CHECK_LABELS[name]
        status = str((checks.get(name) or {}).get("status") or "FAIL")
        lines.append(f"{label:<24}{status}")
    authority = str((report.get("final_submit_authority") or {}).get("status") or "CLOSED")
    lines.append(f"{'Final submit authority':<24}{authority}")
    lines.append("")
    lines.append(str(report.get("verdict") or "NOT READY"))
    if report.get("ready") is not True:
        reasons = []
        for name, item in checks.items():
            if item.get("status") != "PASS" and item.get("reason"):
                reasons.append(f"{name}: {item.get('reason')}")
        approval = report.get("approval_binding") or {}
        if approval.get("status") != "PASS" and approval.get("reason"):
            reasons.append(f"approval_binding: {approval.get('reason')}")
        authority_reason = (report.get("final_submit_authority") or {}).get("reason")
        if authority_reason:
            reasons.append(f"final_submit_authority: {authority_reason}")
        if reasons:
            lines.append("Blockers: " + "; ".join(reasons))
    return "\n".join(lines) + "\n"


def report_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
