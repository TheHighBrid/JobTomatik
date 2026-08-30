"""Lever ATS adapter with official posting metadata and fail-closed browser behavior."""

from __future__ import annotations

import re
from contextvars import ContextVar
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
LEVER_ADAPTER_VERSION = "1.1.0"
LEVER_POSTING_FIELDS = {
    "id",
    "text",
    "categories",
    "description",
    "descriptionPlain",
    "hostedUrl",
    "applyUrl",
}
LEVER_SUBMIT_SELECTORS = (
    'button[type="submit"]:has-text("Submit application")',
    'button[type="submit"]:has-text("Submit your application")',
    '.application-submit button[type="submit"]',
    '.postings-btn[type="submit"]',
    'button[type="submit"]',
    'input[type="submit"]',
    '[data-qa*="submit" i]',
    '[data-testid*="submit" i]',
)
LEVER_CONFIRMATION_SELECTORS = (
    '.application-confirmation',
    '#application-confirmation',
    '.posting-confirmation',
    '.confirmation',
    '[class*="application-confirmation" i]',
    '[class*="posting-confirmation" i]',
    '[data-qa*="confirmation" i]',
    '[data-testid*="confirmation" i]',
)
_LEVER_PRE_SUBMIT_CONFIRMATION_STATE: ContextVar[Optional[Dict[str, str]]] = ContextVar(
    "lever_pre_submit_confirmation_state",
    default=None,
)


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

    async def confirmation_container_snapshot(self, surface: Any) -> Dict[str, str]:
        """Capture visible confirmation-container text before the submit action."""
        snapshot: Dict[str, str] = {}
        for selector in LEVER_CONFIRMATION_SELECTORS:
            try:
                element = await surface.query_selector(selector)
                if not element or not await element.is_visible():
                    continue
                text = normalize_text(await element.inner_text())
                if text:
                    snapshot[selector] = text
            except Exception:
                continue
        return snapshot

    async def capture_pre_submit_confirmation_state(self, surface: Any) -> Dict[str, str]:
        """Store a flow-local pre-submit snapshot without mutating the singleton adapter."""
        snapshot = await self.confirmation_container_snapshot(surface)
        _LEVER_PRE_SUBMIT_CONFIRMATION_STATE.set(snapshot)
        return snapshot

    async def find_submit_button(self, surface: Any) -> Any:
        submit = await find_first_action(
            surface,
            LEVER_SUBMIT_SELECTORS,
            reject_terms=("linkedin",),
        )
        if submit:
            await self.capture_pre_submit_confirmation_state(surface)
        else:
            _LEVER_PRE_SUBMIT_CONFIRMATION_STATE.set(None)
        return submit

    async def visible_submit_control_present(self, surface: Any) -> bool:
        """Detect a visible submit control even while it is temporarily disabled."""
        for selector in LEVER_SUBMIT_SELECTORS:
            try:
                control = await surface.query_selector(selector)
                if not control or not await control.is_visible():
                    continue
                label = ""
                try:
                    label = normalize_text(await control.inner_text())
                except Exception:
                    pass
                if not label:
                    try:
                        label = normalize_text(await control.get_attribute("value") or "")
                    except Exception:
                        pass
                if "linkedin" in label:
                    continue
                return True
            except Exception:
                continue
        return False

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
        before_confirmation_state = _LEVER_PRE_SUBMIT_CONFIRMATION_STATE.get()
        _LEVER_PRE_SUBMIT_CONFIRMATION_STATE.set(None)

        try:
            after_fingerprint = await self.step_fingerprint(surface)
        except Exception:
            after_fingerprint = ""
        try:
            submit_control_present = await self.visible_submit_control_present(surface)
        except Exception:
            submit_control_present = True

        url_changed = bool(current_url and current_url != before_url)
        fingerprint_changed = bool(
            before_fingerprint
            and after_fingerprint
            and after_fingerprint != before_fingerprint
        )

        strong_phrases = (
            "thank you for applying",
            "thank you for your application",
            "thanks for applying",
            "thanks for your application",
            "application submitted",
            "application received",
            "your application has been submitted",
            "your application was submitted",
            "your application was already submitted",
            "application successfully submitted",
            "successfully submitted your application",
            "we have received your application",
            "we've received your application",
        )
        weak_phrases = (
            "we'll be in touch",
            "we will be in touch",
            "thanks for your interest",
            "thank you for your interest",
        )
        negative_confirmation_terms = (
            "error",
            "failed",
            "failure",
            "invalid",
            "not submitted",
            "could not submit",
            "unable to submit",
            "please correct",
            "try again",
            "problem processing",
            "problem submitting",
        )
        body_has_negative_confirmation = any(
            term in normalized for term in negative_confirmation_terms
        )
        current_path = urlparse(current_url).path
        confirmation_url = bool(
            re.search(
                r"/(?:thanks|thank-you|confirmation|application-submitted)(?:/|$)",
                current_path,
                re.I,
            )
        )
        common_metadata = {
            "adapter": self.name,
            "adapter_version": self.version,
            "confirmation_url": confirmation_url,
            "url_changed": url_changed,
            "fingerprint_changed": fingerprint_changed,
            "submit_control_present": submit_control_present,
            "negative_confirmation_copy": body_has_negative_confirmation,
            "pre_submit_confirmation_state_captured": before_confirmation_state is not None,
        }

        for selector in LEVER_CONFIRMATION_SELECTORS:
            try:
                element = await surface.query_selector(selector)
                if not element or not await element.is_visible():
                    continue
                text = normalize_text(await element.inner_text())
                if not text or any(term in text for term in negative_confirmation_terms):
                    continue
                strong_container_match = next(
                    (phrase for phrase in strong_phrases if phrase in text),
                    "",
                )
                weak_container_match = next(
                    (phrase for phrase in weak_phrases if phrase in text),
                    "",
                )
                route_transition = bool(confirmation_url and url_changed)
                observed_container_transition = bool(
                    before_confirmation_state is not None
                    and before_confirmation_state.get(selector) != text
                )
                same_page_transition = bool(
                    not url_changed
                    and fingerprint_changed
                    and observed_container_transition
                )
                sufficient_container = bool(
                    not body_has_negative_confirmation
                    and not submit_control_present
                    and (
                        (strong_container_match and (route_transition or same_page_transition))
                        or (weak_container_match and route_transition)
                    )
                )
                if sufficient_container:
                    confirmation_phrase = strong_container_match or weak_container_match
                    return [ConfirmationEvidence(
                        evidence_type="confirmation_page",
                        is_sufficient=True,
                        final_url=current_url,
                        confirmation_text=text[:500],
                        selector=selector,
                        metadata={
                            **common_metadata,
                            "confirmation_basis": (
                                "observed_same_page_confirmation_transition"
                                if same_page_transition
                                else "validated_confirmation_container"
                            ),
                            "confirmation_phrase": confirmation_phrase,
                            "confirmation_container_changed": observed_container_transition,
                        },
                    )]
            except Exception:
                continue

        strong_match = next(
            (phrase for phrase in strong_phrases if phrase in normalized),
            "",
        )
        weak_match = next(
            (phrase for phrase in weak_phrases if phrase in normalized),
            "",
        )
        if (
            strong_match
            and confirmation_url
            and url_changed
            and not submit_control_present
            and not body_has_negative_confirmation
        ):
            return [ConfirmationEvidence(
                evidence_type="success_banner",
                is_sufficient=True,
                final_url=current_url,
                confirmation_text=strong_match,
                metadata={
                    **common_metadata,
                    "confirmation_basis": "strong_phrase_plus_confirmation_route",
                },
            )]
        if (
            weak_match
            and confirmation_url
            and url_changed
            and not submit_control_present
            and not body_has_negative_confirmation
        ):
            return [ConfirmationEvidence(
                evidence_type="success_banner",
                is_sufficient=True,
                final_url=current_url,
                confirmation_text=weak_match,
                metadata={
                    **common_metadata,
                    "confirmation_basis": "weak_phrase_plus_confirmation_route",
                },
            )]

        return [ConfirmationEvidence(
            evidence_type="post_submit_diagnostic",
            is_sufficient=False,
            final_url=current_url,
            confirmation_text=(
                "Submit action occurred; explicit confirmation was not detected."
            ),
            metadata={
                **common_metadata,
                "post_submit_diagnostic": True,
                "submit_clicked": True,
                "before_url": before_url,
                "before_fingerprint": before_fingerprint,
                "after_fingerprint": after_fingerprint,
                "strong_confirmation_phrase": strong_match or None,
                "weak_confirmation_phrase": weak_match or None,
            },
        )]

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
