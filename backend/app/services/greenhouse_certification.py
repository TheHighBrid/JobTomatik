"""Synthetic-only helpers for supervised Greenhouse live certification.

The generated identity and answers exist solely to exercise public application forms in
``dry_run`` mode. They must never be used for a real application submission.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw

from app.services.ats_greenhouse import (
    fetch_greenhouse_job_schema,
    parse_greenhouse_job_url,
)

SYNTHETIC_CONFIRMATION_TIMESTAMP = "2026-07-15T00:00:00Z"
SYNTHETIC_TEXT_RESPONSE = (
    "Synthetic certification response. This public form is being tested in dry-run "
    "mode and will not be submitted."
)

_PROFILE_LABELS = {
    "first name",
    "last name",
    "full name",
    "email",
    "email address",
    "phone",
    "phone number",
    "mobile phone",
    "resume",
    "resume cv",
    "cv",
    "cover letter",
    "linkedin profile",
    "linkedin url",
    "portfolio",
    "portfolio url",
    "website",
}
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


def _demographic_questions(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        values = payload.get("questions") or []
        return [item for item in values if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def iter_schema_questions(schema: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    groups = (
        ("questions", schema.get("questions") or []),
        ("location_questions", schema.get("location_questions") or []),
        ("demographic_questions", _demographic_questions(schema.get("demographic_questions"))),
    )
    for source, values in groups:
        for question in values:
            if isinstance(question, dict):
                yield source, question


def _question_fields(source: str, question: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields = question.get("fields")
    if isinstance(fields, list):
        return [field for field in fields if isinstance(field, dict)]
    if source == "demographic_questions":
        return [{
            "name": f"demographic_{question.get('id')}",
            "type": question.get("type"),
            "values": question.get("answer_options") or [],
        }]
    return []


def _option_labels(source: str, question: Dict[str, Any]) -> List[str]:
    labels: List[str] = []
    for field in _question_fields(source, question):
        values = field.get("values") or field.get("answer_options") or []
        if not isinstance(values, list):
            continue
        for option in values:
            if isinstance(option, dict):
                value = option.get("label")
                if value in (None, ""):
                    value = option.get("name")
                if value in (None, ""):
                    value = option.get("value")
            else:
                value = option
            label = str(value or "").strip()
            if label and _normalize(label) not in _PLACEHOLDER_OPTIONS:
                labels.append(label)
    return list(dict.fromkeys(labels))


def _find_option(options: List[str], phrases: Iterable[str]) -> Optional[str]:
    normalized = [(_normalize(option), option) for option in options]
    for phrase in phrases:
        target = _normalize(phrase)
        for candidate, original in normalized:
            if target and (candidate == target or target in candidate):
                return original
    return None


def choose_synthetic_answer(label: str, options: List[str], *, multiple: bool) -> str:
    """Choose an explicit fictional answer for certification, never a runtime fallback."""
    question = _normalize(label)
    selected: Optional[str] = None

    if any(term in question for term in (
        "gender", "race", "ethnicity", "veteran", "disability", "demographic",
        "sexual orientation", "gender identity",
    )):
        selected = _find_option(options, (
            "prefer not to say", "decline to self identify", "decline", "do not wish",
        ))
    elif "country" in question or "country of residence" in question:
        selected = _find_option(options, ("Canada",))
    elif any(term in question for term in (
        "authorized to work", "legally authorized", "work authorization",
    )):
        selected = _find_option(options, ("Yes",))
    elif any(term in question for term in (
        "sponsorship", "employment agreement", "restriction", "non compete",
        "previously worked", "consulted for", "conflict of interest",
    )):
        selected = _find_option(options, ("No",))
    elif any(term in question for term in (
        "consent", "certify", "agree to", "privacy", "terms",
    )):
        selected = _find_option(options, ("Yes", "I agree", "Agree"))
    elif any(term in question for term in ("hear about", "referral source", "source")):
        selected = _find_option(options, ("LinkedIn", "Other"))

    if selected is None:
        selected = _find_option(options, (
            "No", "Not applicable", "Prefer not to say", "Other", "Yes",
        ))
    if selected is None and options:
        selected = options[0]
    if selected is None:
        selected = SYNTHETIC_TEXT_RESPONSE

    return json.dumps([selected]) if multiple else selected


def _is_profile_or_upload_question(label: str, field_types: List[str]) -> bool:
    normalized = _normalize(label)
    if normalized in _PROFILE_LABELS:
        return True
    return "input_file" in field_types and not any(
        field_type in {"multi_value_single_select", "multi_value_multi_select"}
        for field_type in field_types
    )


def build_synthetic_profile(schema: Dict[str, Any]) -> Dict[str, Any]:
    policies: List[Dict[str, Any]] = []
    policy_id = 1

    for source, question in iter_schema_questions(schema):
        label = str(question.get("label") or "").strip()
        if not label:
            continue
        fields = _question_fields(source, question)
        field_types = [str(field.get("type") or "") for field in fields]
        if _is_profile_or_upload_question(label, field_types):
            continue

        multiple = "multi_value_multi_select" in field_types
        options = _option_labels(source, question)
        answer = choose_synthetic_answer(label, options, multiple=multiple)
        policies.append({
            "id": policy_id,
            "canonical_key": f"custom.synthetic_{policy_id}",
            "category": "synthetic_certification",
            "sensitivity": "synthetic",
            "mode": "answer",
            "answer_value": answer,
            "answer_label": answer,
            "match_phrases": [label],
            "scope": "platform",
            "scope_value": "greenhouse",
            "allow_autofill": True,
            "is_active": True,
            "confirmed_at": SYNTHETIC_CONFIRMATION_TIMESTAMP,
        })
        policy_id += 1

    return {
        "full_name": "Avery Certification",
        "first_name": "Avery",
        "last_name": "Certification",
        "email": "avery.certification@example.test",
        "phone": "+1 613 555 0199",
        "address": "123 Test Street, Ottawa, ON K1A 0B1",
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
        "Synthetic Greenhouse ATS Certification Candidate\n\n"
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


async def build_synthetic_profile_for_url(url: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    board_token, job_id = parse_greenhouse_job_url(url)
    if not board_token or not job_id:
        raise RuntimeError("Could not extract Greenhouse board token and job id.")
    schema = await fetch_greenhouse_job_schema(board_token, job_id)
    profile = build_synthetic_profile(schema)
    metadata = {
        "board_token": board_token,
        "job_id": job_id,
        "job_title": schema.get("title"),
        "company_name": schema.get("company_name"),
        "policy_count": len(profile["answer_policies"]),
    }
    return profile, metadata
