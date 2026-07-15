"""Ashby ATS adapter with public-board metadata and official form-definition validation."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from app.services.ats_base import (
    ATSAdapter,
    ConfirmationEvidence,
    ValidationIssue,
    collect_validation_issues,
    find_first_action,
    normalize_text,
    safe_body_text,
)

ASHBY_JOBS_HOST = "jobs.ashbyhq.com"
ASHBY_API_HOST = "api.ashbyhq.com"
ASHBY_ADAPTER_VERSION = "1.0.0"

ASHBY_PUBLIC_JOB_FIELDS = {
    "id",
    "title",
    "department",
    "team",
    "employmentType",
    "location",
    "publishedAt",
    "isListed",
    "jobUrl",
    "applyUrl",
}

ASHBY_FORM_FIELD_TYPES = {
    "String",
    "Email",
    "File",
    "Date",
    "Number",
    "Boolean",
    "LongText",
    "ValueSelect",
    "MultiValueSelect",
    "Phone",
    "Score",
    "SocialLink",
}


def is_ashby_host(host: str) -> bool:
    normalized = (host or "").lower().split(":", 1)[0]
    return normalized in {ASHBY_JOBS_HOST, ASHBY_API_HOST}


def parse_ashby_job_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract public job-board name and posting id from hosted Ashby URLs."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]

    board: Optional[str] = None
    posting_id: Optional[str] = None

    if host == ASHBY_JOBS_HOST:
        board = parts[0] if parts else None
        posting_id = parts[1] if len(parts) > 1 else None
    elif host == ASHBY_API_HOST and len(parts) >= 4 and parts[:3] == ["posting-api", "job-board", parts[2]]:
        board = parts[2]
    else:
        match = re.search(
            r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-fA-F-]{36})",
            url or "",
        )
        if match:
            board, posting_id = match.group(1), match.group(2)

    if board:
        board = re.sub(r"[^a-zA-Z0-9_-]", "", board)
    if posting_id:
        uuid_match = re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-"
            r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
            posting_id,
        )
        posting_id = posting_id if uuid_match else None
    return board or None, posting_id or None


async def fetch_ashby_public_board(
    board: str,
    *,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    url = f"https://{ASHBY_API_HOST}/posting-api/job-board/{board}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Ashby public job-board response did not return an object.")
    return payload


async def fetch_ashby_job_posting_info(
    api_key: str,
    posting_id: str,
    *,
    job_board_id: Optional[str] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """Fetch the credentialed official jobPosting.info payload when configured."""
    if not api_key:
        raise ValueError("Ashby API key is required for jobPosting.info.")
    body: Dict[str, Any] = {"jobPostingId": posting_id}
    if job_board_id:
        body["jobBoardId"] = job_board_id
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(
            f"https://{ASHBY_API_HOST}/jobPosting.info",
            auth=httpx.BasicAuth(api_key, ""),
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Ashby jobPosting.info response did not return an object.")
    return payload


def inspect_ashby_public_job(job: Dict[str, Any]) -> Dict[str, Any]:
    present_fields = sorted(field for field in ASHBY_PUBLIC_JOB_FIELDS if field in job)
    missing_fields = sorted(ASHBY_PUBLIC_JOB_FIELDS.difference(present_fields))
    job_url = str(job.get("jobUrl") or "")
    apply_url = str(job.get("applyUrl") or "")
    board, posting_id = parse_ashby_job_url(apply_url or job_url)
    record_id = str(job.get("id") or "")

    return {
        "posting_id": record_id or None,
        "title": job.get("title"),
        "department": job.get("department"),
        "team": job.get("team"),
        "employment_type": job.get("employmentType"),
        "location": job.get("location"),
        "published_at": job.get("publishedAt"),
        "is_listed": bool(job.get("isListed")),
        "job_url": job_url or None,
        "apply_url": apply_url or None,
        "board": board,
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "apply_url_matches_posting": bool(
            record_id and posting_id and record_id == posting_id
        ),
        "public_board_metadata_certified": bool(
            record_id
            and board
            and job_url
            and apply_url
            and not missing_fields
            and record_id == posting_id
        ),
        "application_form_definition_exposed_by_public_feed": False,
        "official_form_definition_requires_jobs_read_permission": True,
    }


def _unwrap_api_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    value = payload.get("results")
    return value if isinstance(value, dict) else payload


def inspect_ashby_form_definition(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate Ashby's official application and survey form definitions."""
    result = _unwrap_api_result(payload)
    application = result.get("applicationFormDefinition") or {}
    application_fields = application.get("fields") or []
    surveys = result.get("surveyFormDefinitions") or []

    records: List[Dict[str, Any]] = []
    unsupported: List[Dict[str, str]] = []
    required_uploads: List[str] = []

    def add_fields(source: str, fields: Any) -> None:
        if not isinstance(fields, list):
            return
        for item in fields:
            if not isinstance(item, dict):
                continue
            field = item.get("field") if isinstance(item.get("field"), dict) else item
            field_type = str(field.get("type") or "")
            title = str(
                field.get("title")
                or field.get("humanReadablePath")
                or field.get("path")
                or ""
            )
            required = bool(
                item.get("isRequired")
                or field.get("isNullable") is False
            )
            if field_type and field_type not in ASHBY_FORM_FIELD_TYPES:
                unsupported.append({
                    "source": source,
                    "title": title,
                    "field_type": field_type,
                })
            if required and field_type == "File":
                required_uploads.append(title)
            records.append({
                "source": source,
                "id": field.get("id"),
                "path": field.get("path"),
                "title": title,
                "field_type": field_type,
                "required": required,
            })

    add_fields("application", application_fields)
    if isinstance(surveys, list):
        for survey in surveys:
            if not isinstance(survey, dict):
                continue
            definition = survey.get("formDefinition") or survey.get("surveyFormDefinition") or survey
            add_fields(
                f"survey:{survey.get('id') or survey.get('title') or 'unknown'}",
                definition.get("fields") if isinstance(definition, dict) else [],
            )

    return {
        "job_posting_id": result.get("id") or result.get("jobPostingId"),
        "application_field_count": len(application_fields) if isinstance(application_fields, list) else 0,
        "survey_form_count": len(surveys) if isinstance(surveys, list) else 0,
        "fields": records,
        "field_count": len(records),
        "required_uploads": required_uploads,
        "unsupported_fields": unsupported,
        "official_field_types": sorted(ASHBY_FORM_FIELD_TYPES),
        "form_definition_certified": bool(records) and not unsupported,
    }


class AshbyAdapter(ATSAdapter):
    name = "ashby"
    version = ASHBY_ADAPTER_VERSION
    certification_level = "fixture_pending_live_certification"
    supported_hosts = (ASHBY_JOBS_HOST,)

    async def matches(self, page: Any, url: str) -> bool:
        host = (urlparse(url or "").hostname or "").lower()
        if host == ASHBY_JOBS_HOST:
            return True
        for selector in (
            'iframe[src*="jobs.ashbyhq.com" i]',
            'form[action*="ashbyhq.com" i]',
            'a[href*="jobs.ashbyhq.com" i][href*="/application" i]',
        ):
            try:
                if await page.query_selector(selector):
                    return True
            except Exception:
                continue
        return False

    async def resolve_surface(self, page: Any) -> Any:
        for frame in getattr(page, "frames", []):
            try:
                if frame is not page.main_frame and (
                    urlparse(frame.url or "").hostname or ""
                ).lower() == ASHBY_JOBS_HOST:
                    return frame
            except Exception:
                continue
        try:
            iframe = await page.query_selector('iframe[src*="jobs.ashbyhq.com" i]')
            if iframe:
                frame = await iframe.content_frame()
                if frame:
                    return frame
        except Exception:
            pass
        return page

    async def prepare(self, surface: Any, log: List[Dict[str, Any]]) -> None:
        current_url = getattr(surface, "url", "") or ""
        if current_url.rstrip("/").endswith("/application"):
            return
        for selector in (
            'a[href$="/application"]',
            'a:has-text("Apply for this Job")',
            'a:has-text("Apply for this job")',
            'button:has-text("Apply for this Job")',
            'button:has-text("Apply for this job")',
            '[data-testid*="apply" i]',
        ):
            try:
                control = await surface.query_selector(selector)
                if control and await control.is_visible() and await control.is_enabled():
                    await control.click()
                    try:
                        await surface.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        await surface.wait_for_timeout(500)
                    log.append({
                        "action": "ashby_application_revealed",
                        "selector": selector,
                    })
                    return
            except Exception:
                continue

    async def find_next_button(self, surface: Any) -> Any:
        return await find_first_action(
            surface,
            (
                'button:has-text("Continue")',
                'button:has-text("Next")',
                'button:has-text("Save and continue")',
                '[data-testid*="next" i]',
                '[data-qa*="next" i]',
            ),
            reject_terms=("submit", "apply", "finish", "linkedin"),
        )

    async def find_submit_button(self, surface: Any) -> Any:
        return await find_first_action(
            surface,
            (
                'button[type="submit"]:has-text("Submit Application")',
                'button[type="submit"]:has-text("Submit application")',
                'button:has-text("Submit Application")',
                '[data-testid*="submit" i]',
                '[data-qa*="submit" i]',
                'button[type="submit"]',
                'input[type="submit"]',
            ),
            reject_terms=("linkedin",),
        )

    async def extract_validation_errors(self, surface: Any) -> List[ValidationIssue]:
        return await collect_validation_issues(
            surface,
            (
                '[data-testid*="error" i]',
                '[data-qa*="error" i]',
                '[class*="error" i]',
                '.field-error',
                '.error-message',
                '.validation-error',
                '[role="alert"]',
                '[aria-invalid="true"]',
            ),
        )

    async def detect_confirmation(
        self,
        surface: Any,
        *,
        before_url: str,
        before_fingerprint: str,
    ) -> List[ConfirmationEvidence]:
        current_url = getattr(surface, "url", "") or ""
        normalized = normalize_text(await safe_body_text(surface))
        for selector in (
            '[data-testid*="confirmation" i]',
            '[data-testid*="success" i]',
            '[data-qa*="confirmation" i]',
            '.application-confirmation',
            '.confirmation',
        ):
            try:
                element = await surface.query_selector(selector)
                if element and await element.is_visible():
                    text = normalize_text(await element.inner_text())
                    if text:
                        return [ConfirmationEvidence(
                            evidence_type="confirmation_page",
                            is_sufficient=True,
                            final_url=current_url,
                            confirmation_text=text[:500],
                            selector=selector,
                            metadata={"adapter": self.name, "adapter_version": self.version},
                        )]
            except Exception:
                continue

        phrases = (
            "thank you for applying",
            "thank you for your application",
            "application submitted",
            "application received",
            "we have received your application",
            "we've received your application",
            "your application has been submitted",
        )
        matched = next((phrase for phrase in phrases if phrase in normalized), "")
        confirmation_url = bool(
            re.search(r"/(?:thanks|thank-you|confirmation|submitted)(?:[/?#]|$)", current_url, re.I)
        )
        if matched:
            return [ConfirmationEvidence(
                evidence_type="success_banner",
                is_sufficient=True,
                final_url=current_url,
                confirmation_text=matched,
                metadata={
                    "adapter": self.name,
                    "adapter_version": self.version,
                    "confirmation_url": confirmation_url,
                },
            )]
        if confirmation_url and current_url != before_url and "application" in normalized:
            return [ConfirmationEvidence(
                evidence_type="confirmation_page",
                is_sufficient=True,
                final_url=current_url,
                confirmation_text="Ashby confirmation route and application text detected after submit.",
                metadata={"adapter": self.name, "adapter_version": self.version},
            )]
        return []

    def manifest(self) -> Dict[str, Any]:
        return {
            **super().manifest(),
            "public_job_board_endpoint": "GET /posting-api/job-board/{board}",
            "official_job_posting_endpoint": "POST /jobPosting.info",
            "official_form_field_types": sorted(ASHBY_FORM_FIELD_TYPES),
            "capabilities": {
                "hosted_application_page": True,
                "embedded_iframe": True,
                "multi_step": True,
                "dynamic_conditional_fields": True,
                "verified_uploads": True,
                "validation_extraction": True,
                "confirmation_detection": True,
                "public_board_metadata_inspection": True,
                "credentialed_form_definition_validation": True,
                "custom_question_dom_inspection": True,
                "searchable_comboboxes": True,
                "manual_captcha_handoff": True,
                "manual_mfa_handoff": True,
            },
            "live_certification": {
                "mode": "not_yet_certified",
                "public_form_smoke": "pending",
                "synthetic_full_form_exercise": "pending",
                "resumable_handoff": "pending",
                "final_submit_clicked": False,
            },
        }
