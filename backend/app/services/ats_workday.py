"""Workday Candidate Experience ATS adapter.

The implementation is ported from JobSniffing's Workday v1 doorway and adapted to
JobTomatik's async ATS contract. Workday owns only strict target recognition,
query-free tenant/site/requisition evidence, public CXS metadata inspection, one
bounded Apply transition, active application-surface discovery, validation, and
confirmation selectors. The shared flow owns filling, dynamic rescans, verified
uploads, navigation limits, human handoffs, and final-submit separation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse, urlunparse

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

WORKDAY_SUFFIX = ".myworkdayjobs.com"
WORKDAY_ADAPTER_VERSION = "1.0.0"
_LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$", re.IGNORECASE)
_JOB_ID_RE = re.compile(
    r"^(?:R|JR|REQ|JOB|J)[-_]?[A-Z0-9][A-Z0-9._-]*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WorkdayTarget:
    host: str
    tenant: str
    cluster: str
    site: str
    job_id: str
    safe_url: str
    surface_kind: str = "candidate_experience_job"

    def as_dict(self) -> Dict[str, str]:
        return {
            "host": self.host,
            "tenant": self.tenant,
            "cluster": self.cluster,
            "site": self.site,
            "job_id": self.job_id,
            "safe_url": self.safe_url,
            "surface_kind": self.surface_kind,
        }


def _safe_url(url: str) -> str:
    parsed = urlparse(url or "")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def is_workday_host(host: str) -> bool:
    value = (host or "").lower().split(":", 1)[0]
    return value.endswith(WORKDAY_SUFFIX) and value != WORKDAY_SUFFIX.lstrip(".")


def parse_workday_target(url: str) -> Optional[WorkdayTarget]:
    """Parse a strict Workday Candidate Experience job URL.

    Tenant home pages, Candidate Home/login routes, and generic corporate pages are
    rejected because they do not identify a requisition. Query strings and fragments
    are removed from retained evidence.
    """

    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if not is_workday_host(host):
        return None

    host_labels = host[: -len(WORKDAY_SUFFIX)].strip(".").split(".")
    tenant = host_labels[0] if host_labels else ""
    cluster = host_labels[1] if len(host_labels) > 1 else ""
    if not tenant:
        return None

    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments and _LOCALE_RE.fullmatch(segments[0]):
        segments = segments[1:]
    lowered = [segment.casefold() for segment in segments]
    try:
        job_index = lowered.index("job")
    except ValueError:
        return None

    site = segments[job_index - 1] if job_index > 0 else ""
    tail = segments[job_index + 1 :]
    if tail and tail[-1].casefold() in {"apply", "application"}:
        tail = tail[:-1]
    if not site or not tail:
        return None

    final_slug = tail[-1]
    match = re.search(
        r"(?:^|_)((?:R|JR|REQ|JOB|J)[-_]?\d[A-Z0-9._-]*)$",
        final_slug,
        re.IGNORECASE,
    )
    job_id = match.group(1) if match else final_slug
    if not job_id.strip():
        return None
    if len(tail) == 1 and not _JOB_ID_RE.fullmatch(job_id):
        return None

    return WorkdayTarget(
        host=host,
        tenant=re.sub(r"[^a-zA-Z0-9_-]", "", tenant),
        cluster=re.sub(r"[^a-zA-Z0-9_-]", "", cluster),
        site=re.sub(r"[^a-zA-Z0-9_-]", "", site),
        job_id=re.sub(r"[^a-zA-Z0-9._-]", "", job_id),
        safe_url=_safe_url(url),
    )


def workday_cxs_job_url(target: WorkdayTarget) -> str:
    return (
        f"https://{target.host}/wday/cxs/{quote(target.tenant)}/"
        f"{quote(target.site)}/job/{quote(target.job_id)}"
    )


async def fetch_workday_job_metadata(
    target: WorkdayTarget,
    *,
    timeout: float = 25.0,
) -> Dict[str, Any]:
    """Fetch the public Candidate Experience job payload for a parsed target."""

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(
            workday_cxs_job_url(target),
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Workday CXS job metadata did not return an object.")
    return payload


def inspect_workday_job_metadata(
    payload: Dict[str, Any],
    target: WorkdayTarget,
) -> Dict[str, Any]:
    """Normalize and validate a Workday public job payload without guessing fields."""

    info = payload.get("jobPostingInfo")
    if not isinstance(info, dict):
        info = payload
    requisition = str(
        info.get("jobRequisitionId")
        or info.get("jobReqId")
        or info.get("requisitionId")
        or ""
    )
    external_path = str(info.get("externalUrl") or info.get("jobPath") or "")
    title = info.get("title") or info.get("jobTitle")
    description = info.get("jobDescription") or info.get("description")
    location = info.get("location") or info.get("primaryLocation")
    requisition_matches = bool(
        requisition
        and normalize_text(requisition) == normalize_text(target.job_id)
    )
    path_matches = bool(
        not external_path
        or target.job_id.casefold() in external_path.casefold()
        or target.safe_url.casefold().endswith(external_path.casefold())
    )
    return {
        "target": target.as_dict(),
        "cxs_url": workday_cxs_job_url(target),
        "title": title,
        "description_present": bool(description),
        "location": location,
        "job_requisition_id": requisition or None,
        "external_path": external_path or None,
        "start_date": info.get("startDate"),
        "end_date": info.get("endDate"),
        "time_type": info.get("timeType"),
        "worker_type": info.get("workerType"),
        "remote_type": info.get("remoteType"),
        "requisition_matches_target": requisition_matches,
        "external_path_matches_target": path_matches,
        "public_metadata_certified": bool(
            title
            and requisition_matches
            and path_matches
        ),
    }


class WorkdayAdapter(ATSAdapter):
    name = "workday"
    version = WORKDAY_ADAPTER_VERSION
    certification_level = "fixture_pending_live_certification"
    supported_hosts = ()

    async def matches(self, page: Any, url: str) -> bool:
        if parse_workday_target(url):
            return True
        try:
            if parse_workday_target(getattr(page, "url", "") or ""):
                return True
        except Exception:
            pass
        selectors = (
            'iframe[src*="myworkdayjobs.com" i][src*="/job/" i]',
            'form[action*="myworkdayjobs.com" i][action*="/job/" i]',
            'a[href*="myworkdayjobs.com" i][href*="/job/" i]',
            '[data-automation-id="jobPostingApplyButton"]',
            '[data-automation-id="bottom-navigation-next-button"]',
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
                frame_url = str(getattr(frame, "url", "") or "")
                if frame is not page.main_frame and (
                    parse_workday_target(frame_url)
                    or is_workday_host(urlparse(frame_url).hostname or "")
                ):
                    return frame
            except Exception:
                continue
        try:
            iframe = await page.query_selector('iframe[src*="myworkdayjobs.com" i]')
            if iframe:
                frame = await iframe.content_frame()
                if frame:
                    return frame
        except Exception:
            pass
        return page

    async def prepare(self, surface: Any, log: List[Dict[str, Any]]) -> None:
        current_url = str(getattr(surface, "url", "") or "")
        target = parse_workday_target(current_url)
        if target:
            log.append({
                "action": "workday_target_detected",
                "target": target.as_dict(),
            })

        # Do not click Apply when an application step is already visible.
        for selector in (
            '[data-automation-id="bottom-navigation-next-button"]',
            'input[type="file"]',
            'button:has-text("Submit Application")',
        ):
            try:
                control = await surface.query_selector(selector)
                if control and await control.is_visible():
                    return
            except Exception:
                continue

        for selector in (
            '[data-automation-id="jobPostingApplyButton"]',
            'button[data-automation-id*="apply" i]',
            'a[data-automation-id*="apply" i]',
            'button:has-text("Apply Now")',
            'a:has-text("Apply Now")',
            'button:has-text("Apply")',
            'a:has-text("Apply")',
        ):
            try:
                control = await surface.query_selector(selector)
                if control and await control.is_visible() and await control.is_enabled():
                    await control.click()
                    try:
                        await surface.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        await surface.wait_for_timeout(900)
                    log.append({
                        "action": "workday_application_revealed",
                        "selector": selector,
                        "bounded_apply_transition": True,
                    })
                    return
            except Exception:
                continue

    async def find_next_button(self, surface: Any) -> Any:
        return await find_first_action(
            surface,
            (
                'button[data-automation-id="bottom-navigation-next-button"]',
                'button[data-automation-id="pageFooterNextButton"]',
                'button[data-automation-id*="next" i]',
                'button:has-text("Continue to Next Step")',
                'button:has-text("Save and Continue")',
                'button:has-text("Save & Continue")',
                'button:has-text("Next")',
                'button:has-text("Continue")',
                '[data-testid*="next" i]',
                '[data-qa*="next" i]',
            ),
            reject_terms=("submit", "review", "apply", "finish", "sign in", "create account"),
        )

    async def find_submit_button(self, surface: Any) -> Any:
        return await find_first_action(
            surface,
            (
                'button[data-automation-id*="submit" i]',
                'button:has-text("Submit Application")',
                'button:has-text("Submit application")',
                'button:has-text("Finish Application")',
                'button:has-text("Submit")',
                '[data-testid*="submit" i]',
                '[data-qa*="submit" i]',
                'button[type="submit"]',
                'input[type="submit"]',
            ),
            reject_terms=("sign in", "login", "create account", "next", "continue", "review"),
        )

    async def extract_validation_errors(self, surface: Any) -> List[ValidationIssue]:
        return await collect_validation_issues(
            surface,
            (
                '[data-automation-id="errorMessage"]',
                '[data-automation-id*="error" i]',
                '[data-automation-id*="validation" i]',
                '[aria-invalid="true"]',
                '[role="alert"]',
                '.error',
                '.validation-error',
                '.field-error',
            ),
        )

    async def detect_confirmation(
        self,
        surface: Any,
        *,
        before_url: str,
        before_fingerprint: str,
    ) -> List[ConfirmationEvidence]:
        current_url = str(getattr(surface, "url", "") or "")
        normalized = normalize_text(await safe_body_text(surface))
        for selector in (
            '[data-automation-id*="confirmation" i]',
            '[data-automation-id*="thank" i]',
            '[data-automation-id*="success" i]',
            '[role="status"]',
        ):
            try:
                element = await surface.query_selector(selector)
                if element and await element.is_visible():
                    text = normalize_text(await element.inner_text())
                    if any(term in text for term in (
                        "thank you", "application received", "application submitted",
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
        matched = next((phrase for phrase in (
            "thank you for applying",
            "thank you for your application",
            "application submitted",
            "application received",
            "we have received your application",
            "we've received your application",
        ) if phrase in normalized), "")
        if matched:
            return [ConfirmationEvidence(
                evidence_type="success_banner",
                is_sufficient=True,
                final_url=current_url,
                confirmation_text=matched,
                metadata={"adapter": self.name, "adapter_version": self.version},
            )]
        return []

    def manifest(self) -> Dict[str, Any]:
        return {
            **super().manifest(),
            "public_metadata_endpoint": (
                "GET /wday/cxs/{tenant}/{site}/job/{requisitionId}"
            ),
            "capabilities": {
                "strict_candidate_experience_job_recognition": True,
                "query_free_target_evidence": True,
                "public_cxs_metadata_inspection": True,
                "bounded_apply_transition": True,
                "embedded_application_surface": True,
                "bounded_multi_step": True,
                "dynamic_conditional_fields": True,
                "searchable_comboboxes": True,
                "verified_uploads": True,
                "validation_extraction": True,
                "confirmation_detection": True,
                "manual_login_handoff": True,
                "manual_account_creation_handoff": True,
                "manual_captcha_handoff": True,
                "manual_mfa_handoff": True,
            },
            "live_certification": {
                "mode": "not_yet_certified",
                "public_metadata_inspection": "pending",
                "hosted_form_inspection": "pending",
                "synthetic_full_form_exercise": "pending",
                "resumable_handoff": "pending",
                "final_submit_clicked": False,
            },
        }
