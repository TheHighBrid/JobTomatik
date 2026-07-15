import asyncio
import base64
import logging
import os
from datetime import datetime
from typing import Any, Coroutine, Dict

from app.celery_app import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.application import Application, ApplicationStatus
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.apply_resolver import resolve_application_method
from app.services.cover_letter import generate_cover_letter
from app.services.form_filler import fill_and_submit_application

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


def _profile_dict(user: User) -> Dict[str, Any]:
    return {
        **(user.profile_data or {}),
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "address": user.address,
        "linkedin_url": user.linkedin_url,
        "github_url": user.github_url,
        "portfolio_url": user.portfolio_url,
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
    }


def _sendgrid_email(to_email: str, subject: str, body: str, resume_path: str = "") -> None:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Attachment, Disposition, FileContent, FileName, FileType, Mail

    message = Mail(
        from_email=settings.from_email,
        to_emails=to_email,
        subject=subject,
        plain_text_content=body,
    )

    if resume_path and os.path.exists(resume_path):
        with open(resume_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        filename = os.path.basename(resume_path)
        message.attachment = Attachment(
            FileContent(encoded),
            FileName(filename),
            FileType("application/octet-stream"),
            Disposition("attachment"),
        )

    client = SendGridAPIClient(settings.sendgrid_api_key)
    client.send(message)


def _email_application_result(app: Application, job: Job, user: User, dry_run: bool) -> Dict[str, Any]:
    raw = job.raw_data or {}
    to_email = raw.get("selected_apply_email") or (raw.get("apply_email_candidates") or [None])[0]
    if not to_email:
        return _manual_result(job, dry_run, "Email application method selected but no employer email was found", "email_missing")

    subject = f"Application for {job.title} - {user.full_name or user.email}"
    body = (app.cover_letter or "").strip()
    if not body:
        body = f"Dear Hiring Manager,\n\nPlease accept my application for the {job.title} position at {job.company}.\n\nBest regards,\n{user.full_name or user.email}"

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
        }

    if not settings.sendgrid_api_key:
        return _manual_result(job, dry_run, "SENDGRID_API_KEY is missing, so email application was prepared but not sent", "email_provider_missing")

    try:
        _sendgrid_email(to_email, subject, body, user.resume_path or "")
        return {
            "success": True,
            "dry_run": False,
            "url": job.url,
            "log": [{"action": "email_sent", "to": to_email, "subject": subject, "ts": _now()}],
            "submitted_at": _now(),
            "error": None,
            "fields_filled": 0,
            "requires_manual_review": False,
            "application_method": "email",
        }
    except Exception as exc:
        return _manual_result(job, dry_run, f"Email send failed: {str(exc)[:200]}", "email_failed")


_LISTING_HOSTS = frozenset([
    "jobbank.gc.ca", "www.jobbank.gc.ca",
    "guichetemplois.gc.ca", "www.guichetemplois.gc.ca",
])

_LISTING_PATH_FRAGS = ("/jobsearch/jobposting/", "/rechercheemplois/offredemploi/")


def _is_listing_page_url(url: str) -> bool:
    """True when the URL is a Job Bank listing page, not an actual application form."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url or "")
        return parsed.hostname in _LISTING_HOSTS and any(f in parsed.path for f in _LISTING_PATH_FRAGS)
    except Exception:
        return False


def _ensure_application_method(job: Job) -> Dict[str, Any]:
    raw = dict(job.raw_data or {})
    method = raw.get("application_method")
    selected_url = raw.get("selected_apply_url", "")

    # If the stored apply URL is still a job-listing page the resolver mis-classified it,
    # re-resolve so we can find the real employer ATS or email.
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
        db.commit()
        return {"application_id": application_id, "generated": True}
    except Exception as e:
        logger.exception("generate_cover_letter_task failed")
        db.rollback()
        raise self.retry(exc=e, countdown=30, max_retries=2)
    finally:
        db.close()


@celery_app.task(bind=True, name="app.tasks.applications.submit_application_task", queue="applications")
def submit_application_task(self, application_id: int, dry_run: bool = True):
    db = SessionLocal()
    try:
        app = db.query(Application).filter(Application.id == application_id).first()
        if not app:
            return {"error": "Application not found"}
        job = db.query(Job).filter(Job.id == app.job_id).first()
        user = db.query(User).filter(User.id == app.user_id).first()
        if not job or not user:
            return {"error": "Missing job or user"}

        if not dry_run and not settings.allow_real_application_submit:
            result = _manual_result(job, False, LIVE_SUBMIT_BLOCKED_REASON, "live_submit_blocked")
            app.status = ApplicationStatus.pending
            app.automation_log = result["log"]
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
            db.commit()
            return result

        app.status = ApplicationStatus.applying
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
                    user_profile=_profile_dict(user),
                    cover_letter=app.cover_letter or "",
                    resume_path=user.resume_path or "",
                    dry_run=dry_run,
                )
            )
        else:
            result = _manual_result(job, dry_run, f"Unknown application method: {method}", "unknown_method")

        app.automation_log = result.get("log", [])

        if result.get("success") and not dry_run:
            app.status = ApplicationStatus.applied
            app.applied_at = datetime.utcnow()
            db.add(Notification(
                user_id=user.id,
                type=NotificationType.application_submitted,
                title=f"Applied to {job.title} at {job.company}",
                message="Your application was submitted automatically.",
                data={"job_id": job.id, "application_id": app.id, "method": method},
            ))
            db.commit()
            from app.tasks.followup import schedule_auto_followup
            auto_settings = user.automation_settings or {}
            if auto_settings.get("auto_followup", True):
                days = int(auto_settings.get("auto_followup_days", 7))
                schedule_auto_followup.apply_async(args=[application_id, days], countdown=5)
        elif result.get("success") and dry_run:
            app.status = ApplicationStatus.pending
        elif result.get("requires_manual_review"):
            app.status = ApplicationStatus.pending
            db.add(Notification(
                user_id=user.id,
                type=NotificationType.system,
                title=f"Manual review needed: {job.title}",
                message=result.get("error") or "No safe automatic application method was found.",
                data={"job_id": job.id, "application_id": app.id, "method": method},
            ))
            logger.info(f"Application {application_id} requires manual review: {result.get('error')}")
        else:
            app.status = ApplicationStatus.pending
            logger.warning(f"Application {application_id} failed: {result.get('error')}")

        db.commit()
        return result
    except Exception as e:
        logger.exception("submit_application_task failed")
        db.rollback()
        raise self.retry(exc=e, countdown=60, max_retries=2)
    finally:
        db.close()
