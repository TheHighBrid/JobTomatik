"""Synthetic-only helpers for supervised Workday certification."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from PIL import Image, ImageDraw

from app.services.lever_certification import (
    build_synthetic_profile as _build_dom_profile,
    inspect_lever_application_dom as _inspect_application_dom,
)

SYNTHETIC_CONFIRMATION_TIMESTAMP = "2026-07-16T00:00:00Z"
SYNTHETIC_TEXT_RESPONSE = (
    "Synthetic Workday certification response. This form is being tested in "
    "dry-run mode and will not be submitted."
)


async def _workday_shell_diagnostics(surface: Any) -> Dict[str, Any]:
    """Inventory current public controls without retaining URL queries or fragments."""

    try:
        return await surface.evaluate(
            """() => {
              const visible = (el) => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' &&
                  rect.width > 0 && rect.height > 0;
              };
              const safeHref = (value) => {
                if (!value) return '';
                try {
                  const url = new URL(value, location.href);
                  return `${url.origin}${url.pathname}`;
                } catch (_) {
                  return '';
                }
              };
              const records = Array.from(document.querySelectorAll(
                'a[href],button,[role="button"],[data-automation-id],input'
              )).filter(visible).slice(0, 80).map((el) => ({
                tag: el.tagName.toLowerCase(),
                text: (el.innerText || el.value || el.getAttribute('aria-label') || '')
                  .replace(/\\s+/g, ' ').trim().slice(0, 180),
                automation_id: el.getAttribute('data-automation-id') || '',
                role: el.getAttribute('role') || '',
                type: el.getAttribute('type') || '',
                href: safeHref(el.getAttribute('href') || ''),
                target: el.getAttribute('target') || '',
                aria_controls: el.getAttribute('aria-controls') || '',
                aria_expanded: el.getAttribute('aria-expanded') || '',
              }));
              const dialogs = Array.from(document.querySelectorAll('[role="dialog"]'))
                .filter(visible).slice(0, 10).map((el) =>
                  (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 500)
                );
              return {
                safe_url: `${location.origin}${location.pathname}`,
                title: document.title || '',
                body_excerpt: (document.body?.innerText || '')
                  .replace(/\\s+/g, ' ').trim().slice(0, 3000),
                visible_action_count: records.length,
                visible_actions: records,
                visible_dialogs: dialogs,
              };
            }"""
        )
    except Exception as exc:
        return {"diagnostic_error": f"{type(exc).__name__}: {str(exc)[:300]}"}


async def inspect_workday_application_dom(surface: Any) -> Dict[str, Any]:
    inventory = await _inspect_application_dom(surface)
    inventory["platform"] = "workday"
    inventory["custom_questions_source"] = "hosted_dom"
    inventory["final_submit_clicked"] = False
    inventory["workday_shell"] = await _workday_shell_diagnostics(surface)
    return inventory


def build_synthetic_profile(dom_inventory: Dict[str, Any]) -> Dict[str, Any]:
    profile = _build_dom_profile(dom_inventory)
    policies = []
    for index, policy in enumerate(profile.get("answer_policies") or [], start=1):
        value = dict(policy)
        value["id"] = index
        value["scope"] = "platform"
        value["scope_value"] = "myworkdayjobs.com"
        value["confirmed_at"] = SYNTHETIC_CONFIRMATION_TIMESTAMP
        canonical = str(value.get("canonical_key") or "")
        if canonical.startswith("custom.lever_synthetic_"):
            value["canonical_key"] = canonical.replace(
                "custom.lever_synthetic_", "custom.workday_synthetic_", 1
            )
        for key in ("answer_value", "answer_label"):
            answer = str(value.get(key) or "")
            if "Synthetic Lever certification response" in answer:
                value[key] = SYNTHETIC_TEXT_RESPONSE
        policies.append(value)

    profile["answer_policies"] = policies
    profile["synthetic_certification_only"] = True
    profile["synthetic_platform"] = "workday"
    return profile


async def build_synthetic_profile_for_page(
    surface: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    inventory = await inspect_workday_application_dom(surface)
    profile = build_synthetic_profile(inventory)
    metadata = {
        "visible_control_count": inventory["visible_control_count"],
        "required_control_count": inventory["required_control_count"],
        "required_custom_control_count": len(inventory["required_custom_controls"]),
        "policy_count": len(profile["answer_policies"]),
        "custom_questions_source": "hosted_dom",
        "public_cxs_metadata_exposes_application_questions": False,
        "account_creation_automated": False,
        "credentials_entered": False,
        "workday_shell": inventory.get("workday_shell") or {},
    }
    return profile, metadata


def write_synthetic_resume(path: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (612, 792), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text(
        (48, 48),
        "AVERY CERTIFICATION\n\n"
        "Synthetic Workday ATS Certification Candidate\n\n"
        "This document contains no real applicant information.\n"
        "It exists only to verify upload and form-handling behavior.\n\n"
        "Final submission is disabled.",
        fill="black",
        spacing=10,
    )
    image.save(target, "PDF", resolution=72.0)
    if not target.exists() or target.stat().st_size < 100:
        raise RuntimeError("Synthetic Workday certification resume could not be generated.")
    return str(target)
