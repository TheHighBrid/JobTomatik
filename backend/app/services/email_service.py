"""
Email service using SendGrid. Falls back to a console logger when no key is set.
"""
import logging
from typing import Optional
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


async def send_email(
    to: str,
    subject: str,
    body: str,
    from_email: Optional[str] = None,
    html_body: Optional[str] = None,
) -> bool:
    sender = from_email or settings.from_email

    if not settings.sendgrid_api_key:
        logger.info(f"[EMAIL MOCK] To: {to} | Subject: {subject}\n{body}")
        return True

    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Email, To, Content

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
        return response.status_code in (200, 202)
    except Exception as e:
        logger.error(f"SendGrid error: {e}")
        return False


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
        f"— The JobTomatik Team"
    )
    return await send_email(to=to, subject=subject, body=body)


async def send_welcome_email(to: str, name: str) -> bool:
    subject = "Welcome to JobTomatik!"
    body = (
        f"Hi {name},\n\n"
        f"Welcome to JobTomatik — your automated job application assistant.\n\n"
        f"Get started by:\n"
        f"1. Completing your profile\n"
        f"2. Uploading your resume\n"
        f"3. Setting your job preferences\n"
        f"4. Running your first job search\n\n"
        f"Happy job hunting!\n— The JobTomatik Team"
    )
    return await send_email(to=to, subject=subject, body=body)
