"""
Email service using SendGrid.

Ordinary product notifications retain the privacy-conscious mock fallback used by
local development. Safety-sensitive outbound recruiter follow-ups can require a
real provider receipt so a missing key is never treated as a successful send.
"""

import asyncio
import logging
from typing import Any, Optional

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _send_with_sendgrid(
    *,
    to: str,
    sender: str,
    subject: str,
    body: str,
    html_body: Optional[str],
) -> dict[str, Any]:
    """Run the synchronous SendGrid SDK outside the FastAPI event loop."""
    import sendgrid
    from sendgrid.helpers.mail import Content, Email, Mail, To

    sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
    mail = Mail(
        from_email=Email(sender),
        to_emails=To(to),
        subject=subject,
    )
    if html_body:
        mail.content = [Content("text/html", html_body), Content("text/plain", body)]
    else:
        mail.content = [Content("text/plain", body)]

    response = sg.client.mail.send.post(request_body=mail.get())
    status_code = int(getattr(response, "status_code", 0) or 0)
    headers = dict(getattr(response, "headers", {}) or {})
    return {
        "accepted": status_code in (200, 202),
        "status_code": status_code,
        "message_id": headers.get("X-Message-Id") or headers.get("x-message-id"),
        "provider": "sendgrid",
        "mode": "provider",
    }


async def send_email_with_receipt(
    to: str,
    subject: str,
    body: str,
    from_email: Optional[str] = None,
    html_body: Optional[str] = None,
    *,
    require_provider: bool = False,
) -> dict[str, Any]:
    sender = from_email or settings.from_email

    if not settings.sendgrid_api_key:
        recipient_domain = to.rsplit("@", 1)[-1] if "@" in to else "unknown"
        logger.info(
            "[EMAIL MOCK] recipient_domain=%s subject=%s body_length=%d require_provider=%s",
            recipient_domain,
            subject,
            len(body),
            require_provider,
        )
        if require_provider:
            return {
                "accepted": False,
                "status_code": None,
                "message_id": None,
                "provider": "sendgrid",
                "mode": "provider_missing",
                "error": "SENDGRID_API_KEY is not configured",
            }
        return {
            "accepted": True,
            "status_code": None,
            "message_id": None,
            "provider": "mock",
            "mode": "mock",
        }

    try:
        return await asyncio.to_thread(
            _send_with_sendgrid,
            to=to,
            sender=sender,
            subject=subject,
            body=body,
            html_body=html_body,
        )
    except Exception as exc:
        logger.exception("SendGrid delivery failed")
        return {
            "accepted": False,
            "status_code": None,
            "message_id": None,
            "provider": "sendgrid",
            "mode": "provider_error",
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }


async def send_email(
    to: str,
    subject: str,
    body: str,
    from_email: Optional[str] = None,
    html_body: Optional[str] = None,
) -> bool:
    receipt = await send_email_with_receipt(
        to=to,
        subject=subject,
        body=body,
        from_email=from_email,
        html_body=html_body,
        require_provider=False,
    )
    return bool(receipt.get("accepted"))


async def send_followup_email(
    to: str,
    applicant_name: str,
    job_title: str,
    company: str,
    applied_days_ago: int,
    custom_message: Optional[str] = None,
) -> bool:
    subject = f"Following up on my {job_title} application at {company}"
    body = custom_message or (
        f"Dear Hiring Manager,\n\n"
        f"I wanted to follow up on my application for the {job_title} position at {company} "
        f"that I submitted {applied_days_ago} days ago. I remain very excited about this "
        f"opportunity and would love to learn about next steps.\n\n"
        f"Please let me know if you need any additional information.\n\n"
        f"Best regards,\n{applicant_name}"
    )
    return await send_email(to=to, subject=subject, body=body)


async def send_status_notification(
    to: str,
    applicant_name: str,
    job_title: str,
    company: str,
    new_status: str,
) -> bool:
    subject = f"Application Update: {job_title} at {company}"
    body = (
        f"Hi {applicant_name},\n\n"
        f"Your application for {job_title} at {company} has been updated to: {new_status.upper()}.\n\n"
        f"Log in to JobTomatik to see full details and take action.\n\n"
        f"The JobTomatik Team"
    )
    return await send_email(to=to, subject=subject, body=body)


async def send_welcome_email(to: str, name: str) -> bool:
    subject = "Welcome to JobTomatik!"
    body = (
        f"Hi {name},\n\n"
        f"Welcome to JobTomatik, your automated job application assistant.\n\n"
        f"Get started by:\n"
        f"1. Completing your profile\n"
        f"2. Uploading your resume\n"
        f"3. Setting your job preferences\n"
        f"4. Running your first job search\n\n"
        f"Happy job hunting!\nThe JobTomatik Team"
    )
    return await send_email(to=to, subject=subject, body=body)
