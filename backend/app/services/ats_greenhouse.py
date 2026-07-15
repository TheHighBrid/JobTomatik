"""Greenhouse ATS adapter with schema inspection and fail-closed browser behavior."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

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

GREENHOUSE_HOST_SUFFIXES = (
    "greenhouse.io",
    "greenhouse.com",
)
GREENHOUSE_FIELD_TYPES = {
    "input_file",
    "input_text",
    "input_hidden",
    "textarea",
    "multi_value_single_select",
    "multi_value_multi_select",
}
GREENHOUSE_ADAPTER_VERSION = "1.0.0"


def is_greenhouse_host(host: str) -> bool:
    normalized = (host or "").lower().split(":", 1)[0]
    return any(
        normalized == suffix or normalized.endswith("." + suffix)
        for suffix in GREENHOUSE_HOST_SUFFIXES
    )


def parse_greenhouse_job_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract board token and public job-post id from common Greenhouse URLs."""
    parsed = urlparse(url or "")
    query = parse_qs(parsed.query)
    job_id = (
        (query.get("gh_jid") or query.get("token") or query.get("job_id") or [None])[0]
    )
    parts = [part for part in parsed.path.split("/") if part]
    board_token: Optional[str] = None

    if is_greenhouse_host(parsed.hostname or ""):
        if parts:
            if parts[0] in {"embed", "v1"}:
                pass
            else:
                board_token = parts[0]
        for index, part in enumerate(parts):
            if part == "jobs" and index + 1 < len(parts):
                job_id = parts[index + 1]
                if index >= 1:
                    board_token = parts[index - 1]
            elif part == "job_app" and query.get("token"):
                job_id = query["token"][0]
    else:
        match = re.search(r"(?:gh_jid|greenhouse_job_id)[=/](\d+)", url or "")
        if match:
            job_id = match.group(1)

    if job_id:
        match = re.search(r"\d+", str(job_id))
        job_id = match.group(0) if match else None
    if board_token:
        board_token = re.sub(r"[^a-zA-Z0-9_-]", "", board_token)
    return board_token or None, job_id or None


async def fetch_greenhouse_job_schema(
    board_token: str,
    job_id: str,
    *,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, params={"questions": "true"})
        response.raise_for_status()
        return response.json()


def inspect_greenhouse_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    questions: List[Dict[str, Any]] = []
    unsupported: List[Dict[str, str]] = []
    required_uploads: List[str] = []

    groups = [
        ("questions", schema.get("questions") or []),
        ("location_questions", schema.get("location_questions") or []),
        ("compliance", schema.get("compliance") or []),
        (
            "demographic_questions",
            (schema.get("demographic_questions") or {}).get("questions") or [],
        ),
    ]
    for source, items in groups:
        for question in items:
            label = str(question.get("label") or "")
            fields = question.get("fields")
            if fields is None and source == "demographic_questions":
                fields = [{
                    "name": f"demographic_{question.get('id')}",
                    "type": question.get("type"),
                    "values": question.get("answer_options") or [],
                }]
            field_types = [str(field.get("type") or "") for field in fields or []]
            unknown = [field_type for field_type in field_types if field_type not in GREENHOUSE_FIELD_TYPES]
            for field_type in unknown:
                unsupported.append({"label": label, "field_type": field_type, "source": source})
            if question.get("required") and "input_file" in field_types:
                required_uploads.append(label)
            questions.append({
                "source": source,
                "label": label,
                "required": bool(question.get("required")),
                "field_types": field_types,
                "aggregate_field_count": len(fields or []),
            })

    compliance = schema.get("data_compliance") or []
    return {
        "job_id": schema.get("id"),
        "title": schema.get("title"),
        "company_name": schema.get("company_name"),
        "questions": questions,
        "question_count": len(questions),
        "unsupported_fields": unsupported,
        "required_uploads": required_uploads,
        "data_compliance": compliance,
        "schema_certified": not unsupported,
    }


class GreenhouseAdapter(ATSAdapter):
    name = "greenhouse"
    version = GREENHOUSE_ADAPTER_VERSION
    certification_level = "standards_fixture_certified_live_dry_run_required"
    supported_hosts = (
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "boards.eu.greenhouse.io",
    )

    async def matches(self, page: Any, url: str) -> bool:
        host = (urlparse(url or "").hostname or "").lower()
        if is_greenhouse_host(host) or "gh_jid=" in (url or ""):
            return True
        for selector in (
            'form[action*="greenhouse" i]',
            'iframe[src*="greenhouse" i]',
            '[data-greenhouse-job-id]',
            '[data-qa="job-application"]',
            '#application_form',
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
                if frame is not page.main_frame and is_greenhouse_host(
                    urlparse(frame.url or "").hostname or ""
                ):
                    return frame
            except Exception:
                continue
        for selector in (
            'iframe[src*="greenhouse" i]',
            'iframe[title*="application" i]',
            'iframe[id*="greenhouse" i]',
        ):
            try:
                iframe = await page.query_selector(selector)
                if iframe:
                    frame = await iframe.content_frame()
                    if frame:
                        return frame
            except Exception:
                continue
        return page

    async def prepare(self, surface: Any, log: List[Dict[str, Any]]) -> None:
        for selector in (
            '#apply_button',
            'button:has-text("Apply for this job")',
            'a:has-text("Apply for this job")',
            '[data-qa="btn-apply"]',
        ):
            try:
                button = await surface.query_selector(selector)
                if button and await button.is_visible() and await button.is_enabled():
                    await button.click()
                    await surface.wait_for_timeout(400)
                    log.append({
                        "action": "greenhouse_application_revealed",
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
                '[data-qa*="next" i]',
                '[data-testid*="next" i]',
                'input[type="button"][value*="continue" i]',
                'input[type="button"][value*="next" i]',
            ),
            reject_terms=("submit", "apply", "finish"),
        )

    async def find_submit_button(self, surface: Any) -> Any:
        return await find_first_action(
            surface,
            (
                '#submit_app',
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Submit Application")',
                'button:has-text("Submit my application")',
                'button:has-text("Apply")',
                '[data-qa*="submit" i]',
                '[data-testid*="submit" i]',
            ),
        )

    async def extract_validation_errors(self, surface: Any) -> List[ValidationIssue]:
        return await collect_validation_issues(
            surface,
            (
                '#error_message',
                '.field-error',
                '.error-message',
                '.validation-error',
                '.application--error',
                '[data-qa*="error" i]',
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
        body = await safe_body_text(surface)
        normalized = normalize_text(body)
        selectors = (
            '#application_confirmation',
            '.application-confirmation',
            '.confirmation',
            '[data-qa*="confirmation" i]',
            '[data-testid*="confirmation" i]',
        )
        for selector in selectors:
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
            "application received",
            "application submitted",
            "we have received your application",
            "we've received your application",
            "your application has been received",
        )
        matched = next((phrase for phrase in phrases if phrase in normalized), "")
        confirmation_url = bool(
            re.search(r"thank|confirm|application[_-]?submitted|application[_-]?complete", current_url, re.I)
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
        if confirmation_url and current_url != before_url:
            return [ConfirmationEvidence(
                evidence_type="confirmation_page",
                is_sufficient=True,
                final_url=current_url,
                confirmation_text="Greenhouse confirmation URL detected after submit.",
                metadata={"adapter": self.name, "adapter_version": self.version},
            )]
        return []

    def manifest(self) -> Dict[str, Any]:
        return {
            **super().manifest(),
            "official_schema_endpoint": (
                "GET /v1/boards/{board_token}/jobs/{job_id}?questions=true"
            ),
            "official_field_types": sorted(GREENHOUSE_FIELD_TYPES),
            "capabilities": {
                "embedded_iframe": True,
                "multi_step": True,
                "dynamic_conditional_fields": True,
                "verified_uploads": True,
                "validation_extraction": True,
                "confirmation_detection": True,
                "schema_inspection": True,
            },
            "live_certification": {
                "mode": "supervised_dry_run",
                "final_submit_clicked": False,
                "status": "requires_manually_supplied_live_urls",
            },
        }
