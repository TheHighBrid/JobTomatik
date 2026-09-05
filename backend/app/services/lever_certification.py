"""Synthetic-only helpers for supervised Lever live certification.

The generated identity and answers exist solely to exercise public Lever forms in
``dry_run`` mode. They must never be used for a real application submission.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw

from app.services.answer_policy import classify_question
from app.services.control_engine import element_descriptor, normalize_text

SYNTHETIC_CONFIRMATION_TIMESTAMP = "2026-07-15T00:00:00Z"
SYNTHETIC_TEXT_RESPONSE = (
    "Synthetic Lever certification response. This public form is being tested in "
    "dry-run mode and will not be submitted."
)
SYNTHETIC_LOCATION = "Ottawa, Ontario, Canada"

_PROFILE_PATTERNS = (
    r"\bfull\s*name\b|\byour\s*name\b|candidate\s*name",
    r"\bemail\b|e-mail",
    r"\bphone\b|\bmobile\b|telephone",
    r"\blinkedin\b",
    r"\bgithub\b",
    r"\bportfolio\b|\bwebsite\b|other\s+website",
    r"\bresume\b|\bcv\b",
    r"cover\s*letter",
)
_PLACEHOLDER_OPTIONS = {
    "",
    "select",
    "select one",
    "choose",
    "choose one",
    "please select",
    "please choose",
    "--",
}


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _is_profile_or_upload(descriptor: str, control_type: str) -> bool:
    normalized = _normalize(descriptor)
    if control_type == "file":
        return True
    return any(
        re.search(pattern, normalized, flags=re.IGNORECASE)
        for pattern in _PROFILE_PATTERNS
    )


def _find_option(options: Iterable[str], phrases: Iterable[str]) -> Optional[str]:
    values = [
        (normalize_text(option), option)
        for option in options
        if normalize_text(option)
    ]
    for phrase in phrases:
        target = normalize_text(phrase)
        for candidate, original in values:
            if target and (candidate == target or target in candidate):
                return original
    return None


def choose_synthetic_answer(
    descriptor: str,
    options: List[str],
    *,
    control_type: str,
) -> str:
    """Choose an explicit fictional answer for certification, never a runtime fallback."""
    question = _normalize(descriptor)
    selected: Optional[str] = None

    if any(
        term in question
        for term in (
            "gender",
            "race",
            "ethnicity",
            "veteran",
            "disability",
            "pronoun",
            "sexual orientation",
            "gender identity",
            "lgbtq",
        )
    ):
        selected = _find_option(
            options,
            (
                "prefer not to disclose",
                "prefer not to say",
                "do not wish",
                "decline",
            ),
        )
    elif any(
        term in question
        for term in (
            "current location",
            "where are you located",
            "where are you based",
            "location",
        )
    ):
        selected = _find_option(options, ("Ottawa", "Canada")) or SYNTHETIC_LOCATION
    elif any(
        term in question
        for term in (
            "authorized to work",
            "legally authorized",
            "work authorization",
        )
    ):
        selected = _find_option(options, ("Yes",))
    elif any(
        term in question
        for term in (
            "sponsorship",
            "restriction",
            "non compete",
            "conflict of interest",
            "previously worked",
            "previously employed",
        )
    ):
        selected = _find_option(options, ("No",))
    elif any(
        term in question
        for term in (
            "consent",
            "certify",
            "agree",
            "privacy",
            "terms",
            "accurate",
        )
    ):
        selected = _find_option(options, ("Yes", "I agree", "Agree")) or "Yes"
    elif any(term in question for term in ("hear about", "source", "referral")):
        selected = _find_option(options, ("LinkedIn", "Other"))

    if selected is None:
        selected = _find_option(
            options,
            (
                "Not applicable",
                "No",
                "Prefer not to disclose",
                "Other",
                "Yes",
            ),
        )
    if selected is None and options:
        # Certification-only policy generated from the exact DOM inventory. Runtime
        # application behavior never uses this fallback.
        selected = options[0]
    if selected is None:
        selected = (
            "Yes"
            if control_type in {"checkbox", "checkbox_group"}
            else SYNTHETIC_TEXT_RESPONSE
        )
    return selected


def _synthetic_policy(
    policy_id: int,
    *,
    canonical_key: str,
    category: str,
    sensitivity: str,
    answer: str,
    descriptor: str,
) -> Dict[str, Any]:
    return {
        "id": policy_id,
        "canonical_key": canonical_key,
        "category": category,
        "sensitivity": sensitivity,
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "fallback_answers": [],
        "match_phrases": [descriptor],
        "scope": "platform",
        "scope_value": "lever.co",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": SYNTHETIC_CONFIRMATION_TIMESTAMP,
        "provenance": "verified_import",
        "confidence": 1.0,
        "consent_metadata": {
            "confirmation_method": "synthetic_certification_fixture",
            "autofill_authorized": True,
            "synthetic_only": True,
            "recorded_at": SYNTHETIC_CONFIRMATION_TIMESTAMP,
        },
        "source_metadata": {
            "source": "lever_hosted_dom",
            "synthetic_certification_only": True,
        },
        "expires_at": None,
        "is_expired": False,
        "encryption_valid": True,
    }


async def _control_options(surface: Any, element: Any, control_type: str) -> List[str]:
    options: List[str] = []
    if control_type == "select":
        for option in await element.query_selector_all("option"):
            label = str((await option.inner_text()) or "").strip()
            if label and _normalize(label) not in _PLACEHOLDER_OPTIONS:
                options.append(label)
    elif control_type in {"radio", "checkbox"}:
        try:
            values = await element.evaluate(
                """(el) => {
                  const root = el.closest('fieldset,[role="radiogroup"],[role="group"],.application-question') || el.parentElement;
                  return Array.from(root?.querySelectorAll('input[type="radio"],input[type="checkbox"],[role="radio"],[role="checkbox"]') || [])
                    .map((choice) => {
                      const id = choice.id || '';
                      const label = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : choice.closest('label');
                      return (label?.innerText || choice.getAttribute('aria-label') || choice.value || '').trim();
                    }).filter(Boolean);
                }"""
            )
            options.extend(
                str(value).strip() for value in values if str(value).strip()
            )
        except Exception:
            pass
    elif control_type == "combobox":
        for option in await surface.query_selector_all('[role="option"]'):
            try:
                if await option.is_visible():
                    label = str((await option.inner_text()) or "").strip()
                    if label:
                        options.append(label)
            except Exception:
                continue
    return list(dict.fromkeys(options))


async def inspect_lever_application_dom(surface: Any) -> Dict[str, Any]:
    """Inventory the current hosted form without clicking Submit or selecting answers."""
    records: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    selector = (
        'input:not([type="hidden"]):not([type="submit"]):not([type="button"]),'
        'textarea,select,[role="combobox"],[role="radio"],[role="checkbox"]'
    )
    for element in await surface.query_selector_all(selector):
        try:
            if not await element.is_visible() or not await element.is_enabled():
                continue
            tag = (await element.evaluate("(el) => el.tagName.toLowerCase()")) or ""
            input_type = normalize_text(await element.get_attribute("type"))
            role = normalize_text(await element.get_attribute("role"))
            if input_type == "file":
                control_type = "file"
            elif tag == "select":
                control_type = "select"
            elif input_type == "radio" or role == "radio":
                control_type = "radio"
            elif input_type == "checkbox" or role == "checkbox":
                control_type = "checkbox"
            elif role == "combobox":
                control_type = "combobox"
            elif tag == "textarea":
                control_type = "textarea"
            else:
                control_type = "text"
            descriptor = (await element_descriptor(surface, element)).strip()
            required = bool(
                await element.get_attribute("required") is not None
                or normalize_text(await element.get_attribute("aria-required")) == "true"
                or normalize_text(await element.get_attribute("data-required")) == "true"
            )
            signature = (normalize_text(descriptor), control_type)
            if signature in seen:
                continue
            seen.add(signature)
            records.append(
                {
                    "descriptor": descriptor,
                    "control_type": control_type,
                    "required": required,
                    "options": await _control_options(surface, element, control_type),
                    "name": await element.get_attribute("name") or "",
                    "id": await element.get_attribute("id") or "",
                }
            )
        except Exception:
            continue

    return {
        "controls": records,
        "visible_control_count": len(records),
        "required_control_count": sum(1 for record in records if record["required"]),
        "required_custom_controls": [
            record
            for record in records
            if record["required"]
            and not _is_profile_or_upload(
                record["descriptor"], record["control_type"]
            )
        ],
        "final_submit_clicked": False,
    }


_APPLICATION_SOURCE_MARKERS = (
    "indeed",
    "glassdoor",
    "referral",
    "employee",
    "career site",
    "company website",
    "job board",
    "monster",
    "career fair",
    "talent acquisition",
    "recruiter",
)


def _application_source_group_plan(
    records: List[Dict[str, Any]],
) -> Tuple[Dict[int, Dict[str, Any]], set[int]]:
    """Identify only unmistakable synthetic application-source choice groups.

    Lever sometimes omits the question legend and exposes each option as a separate
    required record. Grouping is allowed only when the controls share one non-empty
    name, are native choice controls, expose LinkedIn, and contain at least two other
    independent recruitment-source markers. This helper is used only to build the
    fictional certification profile and is never part of real-user answer selection.
    """

    grouped: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]] = {}
    for index, record in enumerate(records):
        name = str(record.get("name") or "").strip()
        control_type = str(record.get("control_type") or "").strip()
        if not name or control_type not in {"radio", "checkbox"}:
            continue
        grouped.setdefault((name, control_type), []).append((index, record))

    plans: Dict[int, Dict[str, Any]] = {}
    member_indices: set[int] = set()
    for (name, control_type), members in grouped.items():
        if len(members) < 2:
            continue
        option_text: List[str] = []
        for _, record in members:
            option_text.extend(str(value) for value in record.get("options") or [])
        normalized = _normalize(" ".join(option_text))
        if "linkedin" not in normalized:
            continue
        markers = {
            marker for marker in _APPLICATION_SOURCE_MARKERS
            if marker in normalized
        }
        if len(markers) < 2:
            continue

        first_index = members[0][0]
        indices = {index for index, _ in members}
        plans[first_index] = {
            "name": name,
            "control_type": control_type,
            "answer": "LinkedIn",
            "indices": indices,
            "markers": sorted(markers),
        }
        member_indices.update(indices)
    return plans, member_indices


def build_synthetic_profile(dom_inventory: Dict[str, Any]) -> Dict[str, Any]:
    policies: List[Dict[str, Any]] = []
    records = list(dom_inventory.get("required_custom_controls") or [])
    source_plans, source_members = _application_source_group_plan(records)
    next_policy_id = 1

    for index, record in enumerate(records):
        source_plan = source_plans.get(index)
        if source_plan is not None:
            policies.append(
                _synthetic_policy(
                    next_policy_id,
                    canonical_key="custom.application_source",
                    category="application_source",
                    sensitivity="standard",
                    answer=str(source_plan["answer"]),
                    descriptor=str(source_plan["name"]),
                )
            )
            next_policy_id += 1
            continue
        if index in source_members:
            continue

        descriptor = str(record.get("descriptor") or "").strip()
        if not descriptor:
            continue
        classification = classify_question(descriptor)
        answer = choose_synthetic_answer(
            descriptor,
            list(record.get("options") or []),
            control_type=str(record.get("control_type") or "text"),
        )
        canonical_key = classification.get("canonical_key")
        if canonical_key == "custom.unclassified":
            canonical_key = f"custom.lever_synthetic_{next_policy_id}"
        policies.append(
            _synthetic_policy(
                next_policy_id,
                canonical_key=str(canonical_key),
                category=str(
                    classification.get("category") or "synthetic_certification"
                ),
                sensitivity=str(
                    classification.get("sensitivity") or "synthetic"
                ),
                answer=answer,
                descriptor=descriptor,
            )
        )
        next_policy_id += 1

    # Lever's current-location widget is commonly a required ARIA combobox. It is
    # included explicitly if the DOM inventory classified it as a profile-like field.
    if not any(
        "location" in normalize_text(policy["match_phrases"][0])
        for policy in policies
    ):
        location_control = next(
            (
                record
                for record in dom_inventory.get("controls") or []
                if record.get("required")
                and record.get("control_type") == "combobox"
                and "location" in normalize_text(record.get("descriptor"))
            ),
            None,
        )
        if location_control:
            policies.append(
                _synthetic_policy(
                    len(policies) + 1,
                    canonical_key="custom.current_location",
                    category="location",
                    sensitivity="standard",
                    answer=SYNTHETIC_LOCATION,
                    descriptor=str(location_control["descriptor"]),
                )
            )

    return {
        "full_name": "Avery Certification",
        "first_name": "Avery",
        "last_name": "Certification",
        "email": "avery.certification@example.test",
        "phone": "+1 613 555 0199",
        "address": "Ottawa, Ontario, Canada",
        "city": "Ottawa",
        "state": "Ontario",
        "province": "Ontario",
        "postal_code": "K1A 0B1",
        "linkedin_url": "https://www.linkedin.com/in/avery-certification-test",
        "github_url": "https://github.com/example",
        "portfolio_url": "https://example.test/portfolio",
        "profile_data": {
            "current_role": "Synthetic Certification Candidate",
            "years_experience": 5,
        },
        "answer_policies": policies,
        "synthetic_certification_only": True,
    }


def write_synthetic_resume(path: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (612, 792), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text(
        (48, 48),
        "AVERY CERTIFICATION\n\n"
        "Synthetic Lever ATS Certification Candidate\n\n"
        "This document contains no real applicant information.\n"
        "It exists only to verify upload and form-handling behavior.\n\n"
        "Final submission is disabled.",
        fill="black",
        spacing=10,
    )
    image.save(target, "PDF", resolution=72.0)
    if not target.exists() or target.stat().st_size < 100:
        raise RuntimeError("Synthetic certification resume could not be generated.")
    return str(target)


async def build_synthetic_profile_for_page(
    surface: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    inventory = await inspect_lever_application_dom(surface)
    profile = build_synthetic_profile(inventory)
    metadata = {
        "visible_control_count": inventory["visible_control_count"],
        "required_control_count": inventory["required_control_count"],
        "required_custom_control_count": len(inventory["required_custom_controls"]),
        "policy_count": len(profile["answer_policies"]),
        "custom_questions_source": "hosted_dom",
        "official_api_custom_questions_exposed": False,
    }
    return profile, metadata
