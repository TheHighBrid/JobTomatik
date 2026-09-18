"""SmartRecruiters ATS adapter with public posting and optional screening-schema validation."""

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

SMARTRECRUITERS_JOBS_HOST = "jobs.smartrecruiters.com"
SMARTRECRUITERS_CAREERS_HOST = "careers.smartrecruiters.com"
SMARTRECRUITERS_API_HOST = "api.smartrecruiters.com"
SMARTRECRUITERS_ADAPTER_VERSION = "1.0.0"

SMARTRECRUITERS_POSTING_FIELDS = {
    "id",
    "uuid",
    "name",
    "company",
    "releasedDate",
    "location",
    "ref",
    "applyUrl",
    "active",
}

# The field glossary lists INPUT_TEXT, while the official conditional-question
# example also uses TEXT. Both are retained and validated explicitly.
SMARTRECRUITERS_SCREENING_FIELD_TYPES = {
    "INPUT_TEXT",
    "TEXT",
    "SINGLE_SELECT",
    "MULTI_SELECT",
    "RADIO",
    "CHECKBOX",
    "TEXTAREA",
    "INFORMATION",
}


def is_smartrecruiters_host(host: str) -> bool:
    normalized = (host or "").lower().split(":", 1)[0]
    return normalized in {
        SMARTRECRUITERS_JOBS_HOST,
        SMARTRECRUITERS_CAREERS_HOST,
        SMARTRECRUITERS_API_HOST,
    }


def parse_smartrecruiters_job_url(
    url: str,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return company identifier, posting id/uuid, and URL surface kind."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    company: Optional[str] = None
    posting: Optional[str] = None
    kind: Optional[str] = None

    if host == SMARTRECRUITERS_API_HOST:
        try:
            index = parts.index("companies")
        except ValueError:
            index = -1
        if index >= 0 and len(parts) > index + 2 and parts[index + 2] == "postings":
            company = parts[index + 1]
            posting = parts[index + 3] if len(parts) > index + 3 else None
            kind = "api_posting" if posting else "api_listing"
    elif host == SMARTRECRUITERS_CAREERS_HOST:
        company = parts[0] if parts else None
        kind = "career_site"
    elif host == SMARTRECRUITERS_JOBS_HOST:
        if len(parts) >= 5 and parts[:2] == ["oneclick-ui", "company"]:
            company = parts[2]
            if parts[3] == "publication":
                posting = parts[4]
                kind = "oneclick_application"
        else:
            company = parts[0] if parts else None
            raw = parts[1] if len(parts) > 1 else None
            if raw:
                match = re.match(r"([0-9]+|[0-9a-fA-F-]{36})(?:-|$)", raw)
                posting = match.group(1) if match else None
            kind = "hosted_job"
    else:
        oneclick = re.search(
            r"jobs\.smartrecruiters\.com/oneclick-ui/company/([^/?#]+)/publication/([^/?#]+)",
            url or "",
            flags=re.I,
        )
        hosted = re.search(
            r"jobs\.smartrecruiters\.com/([^/?#]+)/([0-9]+|[0-9a-fA-F-]{36})(?:-|[/?#]|$)",
            url or "",
            flags=re.I,
        )
        if oneclick:
            company, posting, kind = oneclick.group(1), oneclick.group(2), "oneclick_application"
        elif hosted:
            company, posting, kind = hosted.group(1), hosted.group(2), "hosted_job"

    if company:
        company = re.sub(r"[^a-zA-Z0-9_-]", "", company)
    if posting:
        posting = re.sub(r"[^a-zA-Z0-9-]", "", posting)
    return company or None, posting or None, kind


async def fetch_smartrecruiters_postings(
    company: str,
    *,
    limit: int = 100,
    offset: int = 0,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    url = f"https://{SMARTRECRUITERS_API_HOST}/v1/companies/{company}/postings"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, params={"limit": limit, "offset": offset})
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("SmartRecruiters public posting list did not return an object.")
    return payload


async def fetch_smartrecruiters_posting(
    company: str,
    posting_id: str,
    *,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    url = f"https://{SMARTRECRUITERS_API_HOST}/v1/companies/{company}/postings/{posting_id}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("SmartRecruiters posting details did not return an object.")
    return payload


async def fetch_smartrecruiters_configuration(
    smart_token: str,
    posting_uuid: str,
    *,
    language: str = "en",
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """Fetch screening questions and privacy policies when a token is configured."""
    if not smart_token:
        raise ValueError("SmartRecruiters X-SmartToken is required for configuration.")
    url = f"https://{SMARTRECRUITERS_API_HOST}/postings/{posting_uuid}/configuration"
    headers = {
        "X-SmartToken": smart_token,
        "Accept-Language": language or "en",
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(
            url,
            params={"conditionalsIncluded": "true"},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("SmartRecruiters application configuration did not return an object.")
    return payload


def inspect_smartrecruiters_posting(posting: Dict[str, Any]) -> Dict[str, Any]:
    present_fields = sorted(
        field for field in SMARTRECRUITERS_POSTING_FIELDS if field in posting
    )
    missing_fields = sorted(SMARTRECRUITERS_POSTING_FIELDS.difference(present_fields))
    company = posting.get("company") if isinstance(posting.get("company"), dict) else {}
    company_identifier = str(company.get("identifier") or "")
    posting_id = str(posting.get("id") or "")
    posting_uuid = str(posting.get("uuid") or "")
    apply_url = str(posting.get("applyUrl") or "")
    parsed_company, parsed_posting, surface_kind = parse_smartrecruiters_job_url(apply_url)
    matches_posting = bool(
        parsed_posting
        and parsed_posting in {posting_id, posting_uuid}
    )
    return {
        "posting_id": posting_id or None,
        "posting_uuid": posting_uuid or None,
        "title": posting.get("name"),
        "company_identifier": company_identifier or None,
        "company_name": company.get("name"),
        "released_at": posting.get("releasedDate"),
        "location": posting.get("location") or {},
        "reference_url": posting.get("ref"),
        "apply_url": apply_url or None,
        "active": bool(posting.get("active")),
        "surface_kind": surface_kind,
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "apply_url_matches_company": bool(
            parsed_company and company_identifier and parsed_company.lower() == company_identifier.lower()
        ),
        "apply_url_matches_posting": matches_posting,
        "screening_configuration_public": False,
        "screening_configuration_requires_smart_token": True,
        "posting_metadata_certified": bool(
            posting_id
            and posting_uuid
            and company_identifier
            and apply_url
            and posting.get("active") is True
            and not missing_fields
            and parsed_company
            and parsed_company.lower() == company_identifier.lower()
            and matches_posting
        ),
    }


def inspect_smartrecruiters_configuration(payload: Dict[str, Any]) -> Dict[str, Any]:
    questions = payload.get("questions") or []
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    privacy_policies = payload.get("privacyPolicies") or []
    conditionals = settings.get("conditionals") or []

    records: List[Dict[str, Any]] = []
    unsupported: List[Dict[str, str]] = []
    diversity_fields: List[str] = []
    required_fields: List[str] = []
    question_ids = {
        str(item.get("id") or "")
        for item in questions
        if isinstance(item, dict) and item.get("id")
    }

    for question in questions if isinstance(questions, list) else []:
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("id") or "")
        question_label = str(question.get("label") or "")
        for field in question.get("fields") or []:
            if not isinstance(field, dict):
                continue
            field_id = str(field.get("id") or "")
            field_type = str(field.get("type") or "")
            required = bool(field.get("required"))
            compliance = str(field.get("complianceType") or "")
            label = str(field.get("label") or question_label)
            values = field.get("values") if isinstance(field.get("values"), list) else []
            if field_type and field_type not in SMARTRECRUITERS_SCREENING_FIELD_TYPES:
                unsupported.append({
                    "question_id": question_id,
                    "field_id": field_id,
                    "label": label,
                    "field_type": field_type,
                })
            if required and field_type != "INFORMATION":
                required_fields.append(f"{question_id}:{field_id}")
            if compliance == "DIVERSITY":
                diversity_fields.append(f"{question_id}:{field_id}")
            records.append({
                "question_id": question_id,
                "question_label": question_label,
                "repeatable": bool(question.get("repeatable")),
                "field_id": field_id,
                "field_label": label,
                "field_type": field_type,
                "required": required,
                "compliance_type": compliance or None,
                "value_count": len(values),
            })

    invalid_conditionals: List[Dict[str, Any]] = []
    for rule in conditionals if isinstance(conditionals, list) else []:
        if not isinstance(rule, dict):
            continue
        parent = str(rule.get("parentQuestionId") or "")
        children = [str(value) for value in rule.get("conditionalQuestions") or []]
        if not parent or parent not in question_ids or any(child not in question_ids for child in children):
            invalid_conditionals.append(rule)

    privacy_records = []
    for item in privacy_policies if isinstance(privacy_policies, list) else []:
        if isinstance(item, dict):
            privacy_records.append({
                "url": item.get("url"),
                "org_name": item.get("orgName"),
            })

    return {
        "question_count": len(questions) if isinstance(questions, list) else 0,
        "field_count": len(records),
        "fields": records,
        "required_fields": required_fields,
        "diversity_fields": diversity_fields,
        "privacy_policies": privacy_records,
        "privacy_policy_count": len(privacy_records),
        "conditionals": conditionals if isinstance(conditionals, list) else [],
        "conditional_count": len(conditionals) if isinstance(conditionals, list) else 0,
        "invalid_conditionals": invalid_conditionals,
        "avatar_upload_available": bool(settings.get("avatarUploadAvailable")),
        "unsupported_fields": unsupported,
        "official_field_types": sorted(SMARTRECRUITERS_SCREENING_FIELD_TYPES),
        "configuration_certified": bool(records or privacy_records)
        and not unsupported
        and not invalid_conditionals,
    }


class SmartRecruitersAdapter(ATSAdapter):
    name = "smartrecruiters"
    version = SMARTRECRUITERS_ADAPTER_VERSION
    certification_level = "fixture_pending_live_certification"
    supported_hosts = (SMARTRECRUITERS_JOBS_HOST,)

    async def matches(self, page: Any, url: str) -> bool:
        host = (urlparse(url or "").hostname or "").lower()
        if host == SMARTRECRUITERS_JOBS_HOST:
            return True
        selectors = (
            'iframe[src*="jobs.smartrecruiters.com" i]',
            'form[action*="smartrecruiters.com" i]',
            'a[href*="jobs.smartrecruiters.com" i]',
            '[data-company-identifier][data-publication-id]',
        )
        for selector in selectors:
            try:
                if await page.query_selector(selector):
                    return True
            except Exception:
                continue
        return False

    async def resolve_surface(self, page: Any) -> Any:
        for frame in getattr(page, "frames", []):
            try:
                frame_host = (urlparse(frame.url or "").hostname or "").lower()
                if frame is not page.main_frame and frame_host == SMARTRECRUITERS_JOBS_HOST:
                    return frame
            except Exception:
                continue
        try:
            iframe = await page.query_selector('iframe[src*="jobs.smartrecruiters.com" i]')
            if iframe:
                frame = await iframe.content_frame()
                if frame:
                    return frame
        except Exception:
            pass
        return page

    async def prepare(self, surface: Any, log: List[Dict[str, Any]]) -> None:
        current_url = getattr(surface, "url", "") or ""
        if "/oneclick-ui/" in current_url:
            return
        for selector in (
            'a:has-text("I\'m interested")',
            'button:has-text("I\'m interested")',
            'a:has-text("Apply")',
            'button:has-text("Apply")',
            '[data-testid*="apply" i]',
            '[data-qa*="apply" i]',
        ):
            try:
                control = await surface.query_selector(selector)
                if control and await control.is_visible() and await control.is_enabled():
                    await control.click()
                    try:
                        await surface.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        await surface.wait_for_timeout(700)
                    log.append({
                        "action": "smartrecruiters_application_revealed",
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
            reject_terms=("submit", "apply", "finish", "linkedin", "indeed"),
        )

    async def find_submit_button(self, surface: Any) -> Any:
        return await find_first_action(
            surface,
            (
                'button[type="submit"]:has-text("Submit application")',
                'button[type="submit"]:has-text("Submit Application")',
                'button[type="submit"]:has-text("Apply")',
                'button:has-text("Submit application")',
                '[data-testid*="submit" i]',
                '[data-qa*="submit" i]',
                'button[type="submit"]',
                'input[type="submit"]',
            ),
            reject_terms=("linkedin", "indeed", "facebook", "google"),
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
            '[data-qa*="confirmation" i]',
            '[class*="confirmation" i]',
            '[class*="thank-you" i]',
            '[role="status"]',
        ):
            try:
                element = await surface.query_selector(selector)
                if element and await element.is_visible():
                    text = normalize_text(await element.inner_text())
                    if any(term in text for term in (
                        "thank you", "application received", "application submitted"
                    )):
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
            "your application has been sent",
        )
        matched = next((phrase for phrase in phrases if phrase in normalized), "")
        confirmation_url = bool(
            re.search(
                r"/(?:thanks|thank-you|confirmation|application-submitted|application-success)(?:[/?#]|$)",
                current_url,
                re.I,
            )
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
                confirmation_text=(
                    "SmartRecruiters confirmation route and application text detected after submit."
                ),
                metadata={"adapter": self.name, "adapter_version": self.version},
            )]
        return []

    def manifest(self) -> Dict[str, Any]:
        return {
            **super().manifest(),
            "official_public_posting_endpoints": [
                "GET /v1/companies/{companyIdentifier}/postings",
                "GET /v1/companies/{companyIdentifier}/postings/{postingId}",
            ],
            "official_application_configuration_endpoint": (
                "GET /postings/{postingUuid}/configuration?conditionalsIncluded=true"
            ),
            "official_application_submission_endpoint": (
                "POST /postings/{postingUuid}/candidates"
            ),
            "application_api_requires_x_smart_token": True,
            "capabilities": {
                "hosted_application_page": True,
                "embedded_application_surface": True,
                "bounded_multi_step": True,
                "dynamic_conditional_fields": True,
                "verified_uploads": True,
                "validation_extraction": True,
                "confirmation_detection": True,
                "public_posting_metadata_inspection": True,
                "optional_official_screening_schema_validation": True,
                "privacy_policy_inventory": True,
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
