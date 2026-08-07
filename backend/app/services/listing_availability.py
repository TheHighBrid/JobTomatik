"""High-confidence job-listing availability checks.

The detector is intentionally narrow. It only classifies a listing as closed when a
visible status, alert, or prominent page message explicitly says applications are no
longer accepted. It never infers closure merely because an Apply control is absent.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


_CLOSED_LISTING_PATTERNS = (
    re.compile(r"\bno longer accepting applications\b", re.IGNORECASE),
    re.compile(r"\bnot accepting applications\b", re.IGNORECASE),
    re.compile(r"\bapplications? (?:are|is) closed\b", re.IGNORECASE),
    re.compile(r"\bapplication period (?:has )?(?:ended|closed)\b", re.IGNORECASE),
    re.compile(r"\bthis (?:job|position|role|posting) (?:is|has been) (?:closed|expired|filled|no longer available)\b", re.IGNORECASE),
    re.compile(r"\bjob (?:is )?no longer available\b", re.IGNORECASE),
    re.compile(r"\bposition has been filled\b", re.IGNORECASE),
    re.compile(r"\bn['’]accepte plus (?:les )?candidatures\b", re.IGNORECASE),
    re.compile(r"\bne reçoit plus (?:de |les )?candidatures\b", re.IGNORECASE),
    re.compile(r"\b(?:cette )?offre (?:d['’]emploi )?n['’]est plus disponible\b", re.IGNORECASE),
    re.compile(r"\b(?:ce )?poste n['’]est plus disponible\b", re.IGNORECASE),
    re.compile(r"\bla période de candidature est terminée\b", re.IGNORECASE),
)


def classify_closed_listing_text(text: str) -> Optional[str]:
    """Return the matched visible closure phrase, or ``None``."""
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return None
    for pattern in _CLOSED_LISTING_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(0)
    return None


async def detect_closed_listing(page: Any) -> Optional[Dict[str, Any]]:
    """Detect an explicitly closed listing from visible, high-signal page regions."""
    try:
        payload = await page.evaluate(
            """() => {
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return !el.hidden
                  && el.getAttribute('aria-hidden') !== 'true'
                  && style.display !== 'none'
                  && style.visibility !== 'hidden'
                  && Number.parseFloat(style.opacity || '1') > 0.05
                  && rect.width > 0
                  && rect.height > 0;
              };
              const collect = (selector, limit) => Array.from(document.querySelectorAll(selector))
                .filter(visible)
                .slice(0, limit)
                .map((el) => (el.innerText || el.textContent || '').trim())
                .filter(Boolean);
              const statusSelectors = [
                '[role=alert]',
                '[aria-live=assertive]',
                '[aria-live=polite]',
                '[data-test*="closed" i]',
                '[data-testid*="closed" i]',
                '[class*="closed" i]',
                '[class*="expired" i]',
                '[class*="apply" i]'
              ].join(',');
              return {
                url: location.href,
                title: document.title || '',
                statuses: collect(statusSelectors, 30),
                headings: collect('h1,h2,h3,[role=heading]', 20),
                buttons: collect('button,a[role=button]', 30),
              };
            }"""
        )
    except Exception:
        return None

    candidates = [
        *[str(value) for value in payload.get("statuses") or []],
        *[str(value) for value in payload.get("headings") or []],
        str(payload.get("title") or ""),
    ]
    for candidate in candidates:
        matched = classify_closed_listing_text(candidate)
        if matched:
            return {
                "reason_code": "listing_closed",
                "summary": "This job is no longer accepting applications.",
                "matched_text": matched,
                "url": str(payload.get("url") or getattr(page, "url", "") or ""),
                "terminal": True,
                "retryable": False,
            }
    return None


__all__ = ["classify_closed_listing_text", "detect_closed_listing"]
