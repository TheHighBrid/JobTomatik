import asyncio
import base64
import logging
import os
from datetime import datetime
from typing import Any, Coroutine, Dict, Iterable, List

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewReason,
    SubmissionEvidenceType,
)
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.answer_policy import load_runtime_policies
from app.services.application_state import (
    create_manual_review_task,
    has_sufficient_submission_evidence,
    normalize_state,
    record_submission_evidence,
    transition_application_state,
)
from app.services.apply_resolver import resolve_application_method
from app.services.cover_letter import generate_cover_letter
from app.services.form_filler import fill_and_submit_application
from app.services.handoff_integration import _attach_handoff_session
from app.services.handoff_session import HandoffSessionError

logger = logging.getLogger(__name__)
settings = get_settings()

LIVE_SUBMIT_BLOCKED_REASON = (
    "Real application submission is disabled. Set "
    "ALLOW_REAL_APPLICATION_SUBMIT=true only after supervised adapter certification."
)


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


def _now() -> str:
    return datetime.utcnow().isoformat()


def _profile_dict(user: User, db=None, job: Job | None = None) -> Dict[str, Any]:
    profile_data = dict(user.profile_data or {})
    runtime_policies: List[Dict[str, Any]] = []
    if db is not None:
        runtime_policies = load_runtime_policies(
            db,
            user.id,
            target_url=(job.url if job else "") or "",
            company=(job.company if job else "") or "",
        )
    return {
        **profile_data,
        "profile_data": profile_data,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "address": user.address,
        "linkedin_url": user.linkedin_url,
        "github_url": user.github_url,
        "portfolio_url": user.portfolio_url,
        "answer_policies": runtime_policies,
    }


def _job_dict(job: Job) -> Dict[str, Any]:
    return {
        "title": job.title,
        "company": job.company,
        "description": job.description,
        "requirements": job.requirements,
        "skills": job.skills,
    }


def _manual_result(job: Job, dry_run: bool, reason: str, action: str = "manual_review") -> Dict[str, Any]:
    return {
        "success": False,
        "dry_run": dry_run,
        "url": job.url,
        "log": [{"action": action, "reason": reason, "ts": _now()}],
        "submitted_at": None,
        "error": reason,
        "fields_filled": 0,
        "requires_manual_review": True,
        "review_items": [],
    }


def _sendgrid_email(to_email: str, subject: str, body: str, resume_path: str = "") -> Dict[str, Any]:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Attachment, Disposition, FileContent, FileName, FileType, Mail

    message = Mail(
        from_email=settings.from_email,
        to_emails=to_email,
        subject=subject,
        plain_text_content=body,
    )

    if resume_path and os.path.exists(resume_path):
        with open(resume_path, "rb") as file_handle:
            encoded = base64.b64encode(file_handle.read()).decode()
        filename = os.path.basename(resume_path)
        message.attachment = Attachment(
            FileContent(encoded),
            FileName(filename),
            FileType("application/octet-stream"),
            Disposition("attachment"),
        )

    response = SendGridAPIClient(settings.sendgrid_api_key).send(message)
    headers = dict(getattr(response, "headers", {}) or {})
    return {
        "status_code": int(getattr(response, "status_code", 0) or 0),
        "message_id": headers.get("X-Message-Id") or headers.get("x-message-id"),
    }


def _email_application_result(app: Application, job: Job, user: User, dry_run: bool) -> Dict[str, Any]:
    raw = job.raw_data or {}
    to_email = raw.get("selected_apply_email") or (raw.get("apply_email_candidates") or [None])[0]
    if not to_email:
        return _manual_result(
            job,
            dry_run,
            "Email application method selected but no employer email was found",
            "email_missing",
        )

    subject = f"Application for {job.title} - {user.full_name or user.email}"
    body = (app.cover_letter or "").strip()
    if not body:
        body = (
            f"Dear Hiring Manager,\n\nPlease accept my application for the {job.title} "
            f"position at {job.company}.\n\nBest regards,\n{user.full_name or user.email}"
        )

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "url": job.url,
            "log": [{"action": "email_dry_run_ready", "to": to_email, "subject": subject, "ts": _now()}],
            "submitted_at": None,
            "error": None,
            "fields_filled": 0,
            "requires_manual_review": False,
            "application_method": "email",
            "review_items": [],
        }

    if not settings.sendgrid_api_key:
        return _manual_result(
            job,
            dry_run,
            "SENDGRID_API_KEY is missing, so email application was prepared but not sent",
            "email_provider_missing",
        )

    try:
        provider_receipt = _sendgrid_email(to_email, subject, body, user.resume_path or "")
        accepted = 200 <= provider_receipt["status_code"] < 300
        return {
            "success": accepted,
            "dry_run": False,
            "url": job.url,
            "log": [{
                "action": "email_sent" if accepted else "email_provider_rejected",
                "to": to_email,
                "subject": subject,
                "provider_status": provider_receipt["status_code"],
                "ts": _now(),
            }],
            "submitted_at": _now() if accepted else None,
            "error": None if accepted else f"Email provider returned status {provider_receipt['status_code']}",
            "fields_filled": 0,
            "requires_manual_review": not accepted,
            "application_method": "email",
            "review_items": [],
            "confirmation_evidence": [{
                "evidence_type": SubmissionEvidenceType.email_provider_receipt.value,
                "is_sufficient": accepted,
                "confirmation_text": f"Provider accepted email with status {provider_receipt['status_code']}",
                "external_application_id": provider_receipt.get("message_id"),
                "metadata": {
                    "recipient": to_email,
                    "subject": subject,
                    "provider_status": provider_receipt["status_code"],
                },
            }],
        }
    except Exception as exc:
        return _manual_result(job, dry_run, f"Email send failed: {str(exc)[:200]}", "email_failed")


_LISTING_HOSTS = frozenset([
    "jobbank.gc.ca", "www.jobbank.gc.ca",
    "guichetemplois.gc.ca", "www.guichetemplois.gc.ca",
])
_LISTING_PATH_FRAGS = ("/jobsearch/jobposting/", "/rechercheemplois/offredemploi/")


def _is_listing_page_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url or "")
        return parsed.hostname in _LISTING_HOSTS and any(fragment in parsed.path for fragment in _LISTING_PATH_FRAGS)
    except Exception:
        return False


def _ensure_application_method(job: Job) -> Dict[str, Any]:
    raw = dict(job.raw_data or {})
    method = raw.get("application_method")
    selected_url = raw.get("selected_apply_url", "")

    if method == "external_url" and _is_listing_page_url(selected_url):
        logger.info("Re-resolving %s - stored apply URL is a listing page", job.url)
        method = None

    if method:
        return raw

    resolved = _run_async(resolve_application_method(job.url or ""))
    raw.update(resolved)
    if resolved.get("application_method") == "external_url" and resolved.get("selected_apply_url"):
        job.url = resolved["selected_apply_url"]
    job.raw_data = raw
    return raw


def _manual_reason_code(result: Dict[str, Any], method: str) -> ManualReviewReason:
    review_items = result.get("review_items") or []
    if review_items:
        try:
            return ManualReviewReason(review_items[0].get("reason_code"))
        except (ValueError, TypeError):
            pass

    actions = " ".join(str(item.get("action", "")) for item in result.get("log", []))
    text = f"{actions} {result.get('error') or ''}".lower()
    if "captcha" in text:
        return ManualReviewReason.captcha_detected
    if "anti-bot" in text or "anti_bot" in text or "challenge" in text:
        return ManualReviewReason.anti_bot_challenge
    if "assessment" in text or "test required" in text:
        return ManualReviewReason.assessment_required
    if "mfa" in text or "verification code" in text:
        return ManualReviewReason.mfa_required
    if "login" in text or "sign in" in text:
        return ManualReviewReason.login_required
    if "legal" in text or "authorization" in text or "sponsorship" in text:
        return ManualReviewReason.legal_answer_missing
    if "demographic" in text or "gender" in text or "ethnicity" in text or "disability" in text:
        return ManualReviewReason.sensitive_answer_missing
    if "confirmation" in text or "submit clicked" in text:
        return ManualReviewReason.submission_confirmation_uncertain
    if "no submit button" in text or "unsupported control" in text:
        return ManualReviewReason.unsupported_control
    if "email_missing" in actions or "email provider" in text:
        return ManualReviewReason.employer_contact_missing
    if method in {"manual", "unsupported_job_board"}:
        return ManualReviewReason.unsupported_platform
    return ManualReviewReason.automation_error


def _iter_confirmation_evidence(result: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    evidence = result.get("confirmation_evidence") or []
    if isinstance(evidence, dict):
        evidence = [evidence]
    return evidence


def _record_result_evidence(db, app: Application, result: Dict[str, Any]) -> None:
    for item in _iter_confirmation_evidence(result):
        record_submission_evidence(
            db,
            app,
            item.get("evidence_type", SubmissionEvidenceType.success_banner.value),
            is_sufficient=bool(item.get("is_sufficient", False)),
            final_url=item.get("final_url") or result.get("application_url") or result.get("url"),
            confirmation_text=item.get("confirmation_text"),
            selector=item.get("selector"),
            external_application_id=item.get("external_application_id"),
            screenshot_path=item.get("screenshot_path"),
            html_snapshot_path=item.get("html_snapshot_path"),
            payload_hash=item.get("payload_hash"),
            metadata=item.get("metadata") or {},
        )


def _group_review_items(result: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in result.get("review_items") or []:
        reason_code = item.get("reason_code") or ManualReviewReason.ambiguous_question.value
        grouped.setdefault(reason_code, []).append(item)
    return grouped


def _create_result_review_tasks(
    db,
    app: Application,
    result: Dict[str, Any],
    method: str,
    blocking_url: str,
) -> ManualReviewReason:
    grouped = _group_review_items(result)
    if grouped:
        first_reason = ManualReviewReason.ambiguous_question
        for index, (reason_value, items) in enumerate(grouped.items()):
            try:
                reason_code = ManualReviewReason(reason_value)
            except ValueError:
                reason_code = ManualReviewReason.ambiguous_question
            if index == 0:
                first_reason = reason_code
            create_manual_review_task(
                db,
                app,
                reason_code,
                f"{len(items)} application question(s) require an approved answer policy.",
                details={
                    "method": method,
                    "questions": items,
                    "log": result.get("log", []),
                },
                blocking_url=blocking_url,
                target_state=ApplicationAutomationState.needs_review,
            )
        return first_reason

    reason_code = _manual_reason_code(result, method)
    target_state = (
        ApplicationAutomationState.submission_uncertain
        if reason_code == ManualReviewReason.submission_confirmation_uncertain
        else ApplicationAutomationState.needs_review
    )
    create_manual_review_task(
        db,
        app,
        reason_code,
        result.get("error") or "No safe automatic application method was found.",
        details={"method": method, "log": result.get("log", [])},
        blocking_url=blocking_url,
        target_state=target_state,
    )
    return reason_code


@celery_app.task(bind=True, name="app.tasks.applications.generate_cover_letter_task", queue="applications")
def generate_cover_letter_task(self, application_id: int):
    db = SessionLocal()
    try:
        app = db.query(Application).filter(Application.id == application_id).first()
        if not app:
            return {"error": "Application not found"}
        job = db.query(Job).filter(Job.id == app.job_id).first()
        user = db.query(User).filter(User.id == app.user_id).first()
        if not job or not user:
            return {"error": "Missing job or user"}

        app.cover_letter = _run_async(generate_cover_letter(_job_dict(job), _profile_dict(user)))
        state = normalize_state(app.automation_state)
        if state == ApplicationAutomationState.preparing.value:
            transition_application_state(
                db,
                app,
                ApplicationAutomationState.ready_to_apply,
                "cover_letter_generated",
            )
        else:
            db.add(ApplicationEvent(
                application_id=app.id,
                event_type="cover_letter_generated",
                from_state=state,
                to_state=state,
                payload={},
            ))
        db.commit()
        return {"application_id": application_id, "generated": True}
    except Exception as exc:
        logger.exception("generate_cover_letter_task failed")
        db.rollback()
        raise self.retry(exc=exc, countdown=30, max_retries=2)
    finally:
        db.close()


@celery_app.task(bind=True, name="app.tasks.applications.submit_application_task", queue="applications")
def submit_application_task(self, application_id: int, dry_run: bool = True):
    db = SessionLocal()
    try:
        app = (
            db.query(Application)
            .filter(Application.id == application_id)
            .with_for_update()
            .first()
        )
        if not app:
            return {"error": "Application not found"}
        job = db.query(Job).filter(Job.id == app.job_id).first()
        user = db.query(User).filter(User.id == app.user_id).first()
        if not job or not user:
            return {"error": "Missing job or user"}

        if not app.submission_idempotency_key:
            app.submission_idempotency_key = f"application:{app.user_id}:job:{app.job_id}"

        state = normalize_state(app.automation_state)
        if not dry_run and state in {
            ApplicationAutomationState.submitted.value,
            ApplicationAutomationState.confirmed.value,
        }:
            return {
                "success": True,
                "idempotent": True,
                "application_id": app.id,
                "state": state,
                "submitted_at": app.applied_at.isoformat() if app.applied_at else None,
            }
        if state == ApplicationAutomationState.applying.value:
            return {
                "success": False,
                "idempotent": True,
                "application_id": app.id,
                "error": "Application attempt already in progress",
                "requires_manual_review": False,
            }
        if state == ApplicationAutomationState.submission_uncertain.value:
            return _manual_result(
                job,
                dry_run,
                "A prior submission attempt is still unconfirmed and must be reviewed before retrying.",
                "submission_confirmation_uncertain",
            )

        if not dry_run and not settings.allow_real_application_submit:
            result = _manual_result(job, False, LIVE_SUBMIT_BLOCKED_REASON, "live_submit_blocked")
            app.status = ApplicationStatus.pending
            app.automation_log = result["log"]
            create_manual_review_task(
                db,
                app,
                ManualReviewReason.safety_gate_blocked,
                LIVE_SUBMIT_BLOCKED_REASON,
                details={"dry_run": False},
                blocking_url=job.url,
            )
            db.add(Notification(
                user_id=user.id,
                type=NotificationType.system,
                title=f"Live submission blocked: {job.title}",
                message=LIVE_SUBMIT_BLOCKED_REASON,
                data={"job_id": job.id, "application_id": app.id, "reason": "live_submit_blocked"},
            ))
            db.commit()
            logger.warning("Blocked live application submission for application %s", application_id)
            return result

        if not job.url:
            result = _manual_result(job, dry_run, "No URL for job", "missing_url")
            app.status = ApplicationStatus.pending
            app.automation_log = result["log"]
            create_manual_review_task(
                db,
                app,
                ManualReviewReason.missing_job_url,
                "The job has no application URL.",
                details={"job_id": job.id},
            )
            db.commit()
            return result

        transition_application_state(
            db,
            app,
            ApplicationAutomationState.applying,
            "application_attempt_started",
            {"dry_run": dry_run, "attempt": app.submission_attempt_count + 1},
        )
        app.status = ApplicationStatus.applying
        app.submission_attempt_count = (app.submission_attempt_count or 0) + 1
        app.last_submission_attempt_at = datetime.utcnow()
        db.commit()

        raw = _ensure_application_method(job)
        method = raw.get("application_method", "manual")
        reason = raw.get("reason", "No safe automation target was found")

        if method in {"manual", "unsupported_job_board"}:
            result = _manual_result(job, dry_run, reason, method)
        elif method == "email":
            result = _email_application_result(app, job, user, dry_run)
        elif method == "external_url":
            target_url = raw.get("selected_apply_url") or job.url
            job.url = target_url
            result = _run_async(
                fill_and_submit_application(
                    job_url=target_url,
                    user_profile=_profile_dict(user, db, job),
                    cover_letter=app.cover_letter or "",
                    resume_path=user.resume_path or "",
                    dry_run=dry_run,
                )
            )
        else:
            result = _manual_result(job, dry_run, f"Unknown application method: {method}", "unknown_method")

        app.automation_log = result.get("log", [])
        _record_result_evidence(db, app, result)
        db.flush()

        if result.get("success") and not dry_run and has_sufficient_submission_evidence(db, app.id):
            app.status = ApplicationStatus.applied
            app.applied_at = datetime.utcnow()
            transition_application_state(
                db,
                app,
                ApplicationAutomationState.submitted,
                "submission_evidence_accepted",
                {"method": method},
            )
            db.add(Notification(
                user_id=user.id,
                type=NotificationType.application_submitted,
                title=f"Applied to {job.title} at {job.company}",
                message="Your application was submitted and concrete confirmation evidence was recorded.",
                data={"job_id": job.id, "application_id": app.id, "method": method},
            ))
            db.commit()
            from app.tasks.followup import schedule_auto_followup
            auto_settings = user.automation_settings or {}
            if auto_settings.get("auto_followup", True):
                days = int(auto_settings.get("auto_followup_days", 7))
                schedule_auto_followup.apply_async(args=[application_id, days], countdown=5)
        elif result.get("success") and not dry_run:
            result["success"] = False
            result["requires_manual_review"] = True
            result["error"] = "Submission action occurred, but no sufficient confirmation evidence was found."
            app.status = ApplicationStatus.pending
            create_manual_review_task(
                db,
                app,
                ManualReviewReason.submission_confirmation_uncertain,
                result["error"],
                details={"method": method, "log": result.get("log", [])},
                blocking_url=result.get("application_url") or result.get("url") or job.url,
                target_state=ApplicationAutomationState.submission_uncertain,
            )
            db.add(Notification(
                user_id=user.id,
                type=NotificationType.system,
                title=f"Submission confirmation uncertain: {job.title}",
                message=result["error"],
                data={"job_id": job.id, "application_id": app.id, "method": method},
            ))
        elif result.get("success") and dry_run and not result.get("requires_manual_review"):
            app.status = ApplicationStatus.pending
            transition_application_state(
                db,
                app,
                ApplicationAutomationState.ready_to_apply,
                "dry_run_completed",
                {"method": method, "fields_filled": result.get("fields_filled", 0)},
            )
        elif result.get("requires_manual_review"):
            app.status = ApplicationStatus.pending
            blocking_url = result.get("application_url") or result.get("url") or job.url
            reason_code = _create_result_review_tasks(db, app, result, method, blocking_url)
            try:
                _attach_handoff_session(db, app, result, reason_code)
            except HandoffSessionError as exc:
                result.setdefault("log", []).append({
                    "action": "handoff_session_not_created",
                    "reason": str(exc)[:300],
                })
                logger.warning(
                    "Application %s retained-browser handoff was not created: %s",
                    application_id,
                    exc,
                )
            db.add(Notification(
                user_id=user.id,
                type=NotificationType.system,
                title=f"Manual review needed: {job.title}",
                message=result.get("error") or "No safe automatic application method was found.",
                data={
                    "job_id": job.id,
                    "application_id": app.id,
                    "method": method,
                    "reason": reason_code.value,
                    "question_count": len(result.get("review_items") or []),
                    "handoff_public_id": result.get("handoff_public_id"),
                },
            ))
            logger.info("Application %s requires manual review: %s", application_id, result.get("error"))
        else:
            app.status = ApplicationStatus.pending
            transition_application_state(
                db,
                app,
                ApplicationAutomationState.failed,
                "application_attempt_failed",
                {"method": method, "error": result.get("error")},
            )
            logger.warning("Application %s failed: %s", application_id, result.get("error"))

        db.commit()
        return result
    except Exception as exc:
        logger.exception("submit_application_task failed")
        db.rollback()
        raise self.retry(exc=exc, countdown=60, max_retries=2)
    finally:
        db.close()
