"""Lever ATS adapter with official posting metadata and fail-closed browser behavior."""

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

LEVER_GLOBAL_JOBS_HOST = "jobs.lever.co"
LEVER_EU_JOBS_HOST = "jobs.eu.lever.co"
LEVER_GLOBAL_API_HOST = "api.lever.co"
LEVER_EU_API_HOST = "api.eu.lever.co"
LEVER_ADAPTER_VERSION = "1.0.0"
LEVER_POSTING_FIELDS = {
    "id",
    "text",
    "categories",
    "description",
    "descriptionPlain",
    "hostedUrl",
    "applyUrl",
}


def is_lever_host(host: str) -> bool:
    normalized = (host or "").lower().split(":", 1)[0]
    return normalized in {
        LEVER_GLOBAL_JOBS_HOST,
        LEVER_EU_JOBS_HOST,
        LEVER_GLOBAL_API_HOST,
        LEVER_EU_API_HOST,
    }


def parse_lever_job_url(url: str) -> Tuple[Optional[str], Optional[str], str]:
    """Extract Lever site, posting id, and region from hosted or API URLs."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    region = "eu" if host in {LEVER_EU_JOBS_HOST, LEVER_EU_API_HOST} else "global"

    if host in {LEVER_GLOBAL_API_HOST, LEVER_EU_API_HOST}:
        try:
            index = parts.index("postings")
        except ValueError:
            return None, None, region
        site = parts[index + 1] if len(parts) > index + 1 else None
        posting_id = parts[index + 2] if len(parts) > index + 2 else None
    elif host in {LEVER_GLOBAL_JOBS_HOST, LEVER_EU_JOBS_HOST}:
        site = parts[0] if parts else None
        posting_id = parts[1] if len(parts) > 1 else None
    else:
        match = re.search(
            r"jobs(?:\.eu)?\.lever\.co/([^/?#]+)/([a-zA-Z0-9-]+)",
            url or "",
        )
        if not match:
            return None, None, region
        site, posting_id = match.group(1), match.group(2)
        if "jobs.eu.lever.co" in (url or "").lower():
            region = "eu"

    if site:
        site = re.sub(r"[^a-zA-Z0-9_-]", "", site)
    if posting_id:
        posting_id = re.sub(r"[^a-zA-Z0-9-]", "", posting_id)
    return site or None, posting_id or None, region


async def fetch_lever_posting(
    site: str,
    posting_id: str,
    *,
    region: str = "global",
    timeout: float = 15.0,
) -> Dict[str, Any]:
    host = LEVER_EU_API_HOST if region == "eu" else LEVER_GLOBAL_API_HOST
    url = f"https://{host}/v0/postings/{site}/{posting_id}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, params={"mode": "json"})
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Lever posting metadata did not return an object.")
    return payload


def inspect_lever_posting(posting: Dict[str, Any]) -> Dict[str, Any]:
    """Inspect official metadata without claiming custom-question coverage."""
    present_fields = sorted(field for field in LEVER_POSTING_FIELDS if field in posting)
    missing_fields = sorted(LEVER_POSTING_FIELDS.difference(present_fields))
    apply_url = str(posting.get("applyUrl") or "")
    hosted_url = str(posting.get("hostedUrl") or "")
    posting_id = str(posting.get("id") or "")
    apply_site, apply_posting_id, apply_region = parse_lever_job_url(apply_url)

    return {
        "posting_id": posting_id or None,
        "title": posting.get("text"),
        "categories": posting.get("categories") or {},
        "hosted_url": hosted_url or None,
        "apply_url": apply_url or None,
        "site": apply_site,
        "region": apply_region,
        "apply_url_matches_posting": bool(
            posting_id and apply_posting_id and posting_id == apply_posting_id
        ),
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "system_required_fields": ["name", "email"],
        "custom_questions_exposed_by_official_api": False,
        "custom_questions_require_dom_inspection": True,
        "posting_metadata_certified": bool(
            posting_id
            and apply_url
            and hosted_url
            and not missing_fields
            and posting_id == apply_posting_id
        ),
    }


class LeverAdapter(ATSAdapter):
    name = "lever"
    version = LEVER_ADAPTER_VERSION
    certification_level = "fixture_pending_live_certification"
    supported_hosts = (
        LEVER_GLOBAL_JOBS_HOST,
        LEVER_EU_JOBS_HOST,
    )

    async def matches(self, page: Any, url: str) -> bool:
        host = (urlparse(url or "").hostname or "").lower()
        if host in self.supported_hosts:
            return True
        selectors = (
            'form[action*="jobs.lever.co" i]',
            'form[action*="jobs.eu.lever.co" i]',
            'a[href*="jobs.lever.co" i][href*="/apply" i]',
            'a[href*="jobs.eu.lever.co" i][href*="/apply" i]',
        )
        for selector in selectors:
            try:
                if await page.query_selector(selector):
                    return True
            except Exception:
                continue
        return False

    async def resolve_surface(self, page: Any) -> Any:
        return page

    async def prepare(self, surface: Any, log: List[Dict[str, Any]]) -> None:
        current_url = getattr(surface, "url", "") or ""
        if current_url.rstrip("/").endswith("/apply"):
            return
        for selector in (
            'a.postings-btn[href$="/apply"]',
            'a[href$="/apply"]:has-text("Apply for this job")',
            'a:has-text("apply for this job")',
            'button:has-text("Apply for this job")',
            '[data-qa="btn-apply"]',
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
                        "action": "lever_application_revealed",
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
            ),
            reject_terms=("submit", "apply", "linkedin", "finish"),
        )

    async def find_submit_button(self, surface: Any) -> Any:
        return await find_first_action(
            surface,
            (
                'button[type="submit"]:has-text("Submit application")',
                'button[type="submit"]:has-text("Submit your application")',
                '.application-submit button[type="submit"]',
                '.postings-btn[type="submit"]',
                'button[type="submit"]',
                'input[type="submit"]',
                '[data-qa*="submit" i]',
                '[data-testid*="submit" i]',
            ),
            reject_terms=("linkedin",),
        )

    async def extract_validation_errors(self, surface: Any) -> List[ValidationIssue]:
        return await collect_validation_issues(
            surface,
            (
                '.application-field-error',
                '.application-form .error',
                '.field-error',
                '.error-message',
                '.validation-error',
                '[data-qa*="error" i]',
                '[data-testid*="error" i]',
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
            '.application-confirmation',
            '.posting-confirmation',
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
            "application submitted",
            "application received",
            "your application has been submitted",
            "we have received your application",
            "we've received your application",
        )
        matched = next((phrase for phrase in phrases if phrase in normalized), "")
        confirmation_url = bool(
            re.search(r"/(?:thanks|thank-you|confirmation|application-submitted)(?:[/?#]|$)", current_url, re.I)
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
                confirmation_text="Lever confirmation route and application text detected after submit.",
                metadata={"adapter": self.name, "adapter_version": self.version},
            )]
        return []

    def manifest(self) -> Dict[str, Any]:
        return {
            **super().manifest(),
            "official_posting_endpoint": "GET /v0/postings/{site}/{posting_id}?mode=json",
            "official_custom_questions_exposed": False,
            "capabilities": {
                "hosted_application_page": True,
                "single_page": True,
                "bounded_multi_step_fallback": True,
                "dynamic_conditional_fields": True,
                "verified_uploads": True,
                "validation_extraction": True,
                "confirmation_detection": True,
                "posting_metadata_inspection": True,
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
