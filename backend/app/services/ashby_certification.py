"""Synthetic-only helpers for supervised Ashby live certification.

The hosted-form DOM inventory intentionally reuses the same evidence model already
certified for Lever. Platform-specific policy scope, labels, and synthetic artifacts
are rewritten for Ashby before any dry-run exercise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from PIL import Image, ImageDraw

from app.services.lever_certification import (
    build_synthetic_profile as _build_dom_profile,
    inspect_lever_application_dom as _inspect_application_dom,
)

SYNTHETIC_CONFIRMATION_TIMESTAMP = "2026-07-15T00:00:00Z"
SYNTHETIC_TEXT_RESPONSE = (
    "Synthetic Ashby certification response. This public form is being tested in "
    "dry-run mode and will not be submitted."
)


async def inspect_ashby_application_dom(surface: Any) -> Dict[str, Any]:
    """Inventory the hosted form without selecting answers or clicking Submit."""
    inventory = await _inspect_application_dom(surface)
    inventory["platform"] = "ashby"
    inventory["custom_questions_source"] = "hosted_dom"
    inventory["final_submit_clicked"] = False
    return inventory


def build_synthetic_profile(dom_inventory: Dict[str, Any]) -> Dict[str, Any]:
    profile = _build_dom_profile(dom_inventory)
    policies = []
    for index, policy in enumerate(profile.get("answer_policies") or [], start=1):
        value = dict(policy)
        value["id"] = index
        value["scope"] = "platform"
        value["scope_value"] = "ashbyhq.com"
        value["confirmed_at"] = SYNTHETIC_CONFIRMATION_TIMESTAMP
        canonical = str(value.get("canonical_key") or "")
        if canonical.startswith("custom.lever_synthetic_"):
            value["canonical_key"] = canonical.replace(
                "custom.lever_synthetic_", "custom.ashby_synthetic_", 1
            )
        for key in ("answer_value", "answer_label"):
            answer = str(value.get(key) or "")
            if "Synthetic Lever certification response" in answer:
                value[key] = SYNTHETIC_TEXT_RESPONSE
        policies.append(value)

    profile["answer_policies"] = policies
    profile["synthetic_certification_only"] = True
    profile["synthetic_platform"] = "ashby"
    return profile


async def build_synthetic_profile_for_page(surface: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    inventory = await inspect_ashby_application_dom(surface)
    profile = build_synthetic_profile(inventory)
    metadata = {
        "visible_control_count": inventory["visible_control_count"],
        "required_control_count": inventory["required_control_count"],
        "required_custom_control_count": len(inventory["required_custom_controls"]),
        "policy_count": len(profile["answer_policies"]),
        "custom_questions_source": "hosted_dom",
        "public_feed_exposes_form_definition": False,
        "credentialed_job_posting_info_supported": True,
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
        "Synthetic Ashby ATS Certification Candidate\n\n"
        "This document contains no real applicant information.\n"
        "It exists only to verify upload and form-handling behavior.\n\n"
        "Final submission is disabled.",
        fill="black",
        spacing=10,
    )
    image.save(target, "PDF", resolution=72.0)
    if not target.exists() or target.stat().st_size < 100:
        raise RuntimeError("Synthetic Ashby certification resume could not be generated.")
    return str(target)
