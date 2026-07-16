"""Reusable ATS adapter contract and generic browser primitives."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

from app.services.control_engine import normalize_text


@dataclass
class ValidationIssue:
    message: str
    selector: str = ""
    field_descriptor: str = ""
    severity: str = "error"

    def as_dict(self) -> Dict[str, str]:
        return {
            "message": self.message,
            "selector": self.selector,
            "field_descriptor": self.field_descriptor,
            "severity": self.severity,
        }


@dataclass
class ConfirmationEvidence:
    evidence_type: str
    is_sufficient: bool
    final_url: str = ""
    confirmation_text: str = ""
    selector: str = ""
    external_application_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "is_sufficient": self.is_sufficient,
            "final_url": self.final_url or None,
            "confirmation_text": self.confirmation_text or None,
            "selector": self.selector or None,
            "external_application_id": self.external_application_id or None,
            "metadata": self.metadata,
        }


@dataclass
class ATSFlowResult:
    success: bool = False
    ready_to_submit: bool = False
    requires_manual_review: bool = False
    error: Optional[str] = None
    fields_filled: int = 0
    steps_completed: int = 0
    review_items: List[Dict[str, Any]] = field(default_factory=list)
    control_evidence: List[Dict[str, Any]] = field(default_factory=list)
    upload_evidence: List[Dict[str, Any]] = field(default_factory=list)
    step_evidence: List[Dict[str, Any]] = field(default_factory=list)
    confirmation_evidence: List[Dict[str, Any]] = field(default_factory=list)
    validation_errors: List[Dict[str, Any]] = field(default_factory=list)
    final_url: str = ""
    adapter_name: str = "generic"
    adapter_version: str = "1.0.0"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "ready_to_submit": self.ready_to_submit,
            "requires_manual_review": self.requires_manual_review,
            "error": self.error,
            "fields_filled": self.fields_filled,
            "steps_completed": self.steps_completed,
            "review_items": self.review_items,
            "control_evidence": self.control_evidence,
            "upload_evidence": self.upload_evidence,
            "step_evidence": self.step_evidence,
            "confirmation_evidence": self.confirmation_evidence,
            "validation_errors": self.validation_errors,
            "final_url": self.final_url,
            "adapter_name": self.adapter_name,
            "adapter_version": self.adapter_version,
        }


class ATSAdapter:
    """Base contract for platform-specific application flows."""

    name = "generic"
    version = "1.0.0"
    certification_level = "generic_fail_closed"
    supported_hosts: Sequence[str] = ()

    async def matches(self, page: Any, url: str) -> bool:
        host = (urlparse(url or "").hostname or "").lower()
        return bool(host and host in self.supported_hosts)

    async def resolve_surface(self, page: Any) -> Any:
        """Return the page or embedded frame containing the actual application form."""
        return page

    async def prepare(self, surface: Any, log: List[Dict[str, Any]]) -> None:
        return None

    async def find_next_button(self, surface: Any) -> Any:
        return await find_first_action(
            surface,
            (
                'button:has-text("Continue")',
                'button:has-text("Next")',
                'button:has-text("Save and continue")',
                'button:has-text("Proceed")',
                'input[type="button"][value*="continue" i]',
                'input[type="button"][value*="next" i]',
            ),
            reject_terms=("submit", "apply", "finish", "complete application"),
        )

    async def find_submit_button(self, surface: Any) -> Any:
        return await find_first_action(
            surface,
            (
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Submit Application")',
                'button:has-text("Submit my application")',
                'button:has-text("Apply")',
                'button:has-text("Finish")',
                '[data-testid*="submit" i]',
                '[aria-label*="submit" i]',
            ),
        )

    async def extract_validation_errors(self, surface: Any) -> List[ValidationIssue]:
        selectors = (
            '[role="alert"]',
            '[aria-live="assertive"]',
            '.field-error',
            '.error-message',
            '.validation-error',
            '[class*="error" i]',
            '[aria-invalid="true"]',
        )
        return await collect_validation_issues(surface, selectors)

    async def detect_confirmation(
        self,
        surface: Any,
        *,
        before_url: str,
        before_fingerprint: str,
    ) -> List[ConfirmationEvidence]:
        current_url = getattr(surface, "url", "") or ""
        text = await safe_body_text(surface)
        normalized = normalize_text(text)
        phrases = (
            "thank you for applying",
            "application received",
            "application submitted",
            "we have received your application",
            "we've received your application",
        )
        matched = next((phrase for phrase in phrases if phrase in normalized), "")
        changed_url = bool(current_url and current_url != before_url)
        evidence: List[ConfirmationEvidence] = []
        if matched:
            evidence.append(ConfirmationEvidence(
                evidence_type="success_banner",
                is_sufficient=True,
                final_url=current_url,
                confirmation_text=matched,
                metadata={"url_changed": changed_url},
            ))
        elif changed_url and await page_fingerprint(surface) != before_fingerprint:
            evidence.append(ConfirmationEvidence(
                evidence_type="confirmation_page",
                is_sufficient=False,
                final_url=current_url,
                confirmation_text="Page changed after submit, but no explicit confirmation text was found.",
                metadata={"url_changed": True},
            ))
        return evidence

    async def step_fingerprint(self, surface: Any) -> str:
        return await page_fingerprint(surface)

    def manifest(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "certification_level": self.certification_level,
            "supported_hosts": list(self.supported_hosts),
        }


async def safe_body_text(surface: Any, limit: int = 30000) -> str:
    try:
        return (await surface.locator("body").inner_text())[:limit]
    except Exception:
        try:
            return (await surface.inner_text("body"))[:limit]
        except Exception:
            return ""


async def page_fingerprint(surface: Any) -> str:
    try:
        payload = await surface.evaluate(
            """() => {
              const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
              const controls = Array.from(document.querySelectorAll(
                'input:not([type=hidden]),textarea,select,button,[role=combobox],[role=radio],[role=checkbox]'
              )).filter(visible).map((el) => ({
                tag: el.tagName,
                type: el.getAttribute('type') || '',
                name: el.getAttribute('name') || '',
                id: el.id || '',
                text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 120),
                required: el.required || el.getAttribute('aria-required') === 'true',
                checked: el.checked || el.getAttribute('aria-checked') || '',
                disabled: el.disabled || el.getAttribute('aria-disabled') || '',
              }));
              return {
                url: location.href,
                title: document.title,
                heading: document.querySelector('h1,h2,[role=heading]')?.innerText || '',
                controls,
              };
            }"""
        )
    except Exception:
        payload = {"url": getattr(surface, "url", ""), "body": await safe_body_text(surface, 5000)}
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


async def action_text(element: Any) -> str:
    pieces: List[str] = []
    for attr in ("value", "aria-label", "title", "data-testid"):
        try:
            value = await element.get_attribute(attr)
            if value:
                pieces.append(value)
        except Exception:
            pass
    try:
        text = await element.inner_text()
        if text:
            pieces.append(text)
    except Exception:
        pass
    return normalize_text(" ".join(pieces))


async def find_first_action(
    surface: Any,
    selectors: Sequence[str],
    *,
    reject_terms: Sequence[str] = (),
) -> Any:
    for selector in selectors:
        try:
            for element in await surface.query_selector_all(selector):
                if not await element.is_visible() or not await element.is_enabled():
                    continue
                text = await action_text(element)
                if any(term in text for term in reject_terms):
                    continue
                return element
        except Exception:
            continue
    return None


async def collect_validation_issues(
    surface: Any,
    selectors: Sequence[str],
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    seen: set[str] = set()
    for selector in selectors:
        try:
            elements = await surface.query_selector_all(selector)
        except Exception:
            continue
        for element in elements:
            try:
                if not await element.is_visible():
                    continue
            except Exception:
                pass
            try:
                text = normalize_text(await element.inner_text())
            except Exception:
                text = ""
            if not text and selector == '[aria-invalid="true"]':
                try:
                    element_id = await element.get_attribute("id")
                    label = (
                        await surface.query_selector(f'label[for="{element_id}"]')
                        if element_id else None
                    )
                    text = normalize_text(await label.inner_text()) if label else "Invalid required field"
                except Exception:
                    text = "Invalid required field"
            if not text or text in seen:
                continue
            if len(text) > 500:
                text = text[:500]
            seen.add(text)
            issues.append(ValidationIssue(message=text, selector=selector))
    return issues
