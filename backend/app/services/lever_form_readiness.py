"""Fail-closed public Lever application-form readiness inspection.

Lever's official postings API does not expose custom application questions. For a
supervised live submission, approval therefore cannot rely on posting metadata alone:
the exact public ``/apply`` form must be inspected before a one-time approval exists.

This module parses only public form structure. It never stores applicant answers.
Readiness is evaluated with the same profile mapping, answer-policy resolver, and
upload classification used by the runtime form filler so preflight cannot claim a
required field is safe when the worker would later pause on it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from app.services.control_policy import resolve_control_policy
from app.services.form_filler_v2 import _profile_values, _safe_field
from app.services.upload_handler import _classify_upload, _path_matches_accept


LEVER_FORM_SCHEMA_FINGERPRINT_VERSION = 1
LEVER_FORM_SCHEMA_TIMEOUT_SECONDS = 8.0
_ALLOWED_LEVER_HOSTS = {"jobs.lever.co", "jobs.eu.lever.co"}
_IGNORED_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}
_TEXT_INPUT_TYPES = {"", "text", "email", "tel", "url", "number", "date"}
_REQUIRED_MARKERS = ("✱",)


def _clean_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for marker in _REQUIRED_MARKERS:
        text = text.replace(marker, " ")
    text = re.sub(r"\s+", " ", text).strip(" :*-\t\r\n")
    return text


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _lever_host(value: str) -> str:
    try:
        return (urlparse(str(value or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _class_tokens(tag: Optional[Tag]) -> List[str]:
    if tag is None:
        return []
    raw = tag.get("class") or []
    if isinstance(raw, str):
        raw = raw.split()
    return [str(item).lower() for item in raw]


def _question_container(control: Tag) -> Optional[Tag]:
    """Find the nearest local container without accidentally using the whole form."""

    node = control.parent
    for _ in range(6):
        if not isinstance(node, Tag) or node.name == "form":
            break
        classes = " ".join(_class_tokens(node))
        if (
            node.name == "fieldset"
            or "application-field" in classes
            or "application-question" in classes
            or "custom-question" in classes
            or "application-additional" in classes
        ):
            return node
        node = node.parent
    return control.parent if isinstance(control.parent, Tag) and control.parent.name != "form" else None


def _label_for_control(form: Tag, control: Tag) -> str:
    aria = _clean_text(control.get("aria-label"))
    if aria:
        return aria

    control_id = str(control.get("id") or "").strip()
    if control_id:
        label = form.find("label", attrs={"for": control_id})
        if isinstance(label, Tag):
            text = _clean_text(label.get_text(" ", strip=True))
            if text:
                return text

    parent_label = control.find_parent("label")
    if isinstance(parent_label, Tag):
        text = _clean_text(parent_label.get_text(" ", strip=True))
        if text:
            return text

    fieldset = control.find_parent("fieldset")
    if isinstance(fieldset, Tag):
        legend = fieldset.find("legend")
        if isinstance(legend, Tag):
            text = _clean_text(legend.get_text(" ", strip=True))
            if text:
                return text

    container = _question_container(control)
    if isinstance(container, Tag):
        for selector in (
            "legend",
            ".application-label",
            ".application-field-label",
            ".application-question-label",
            "label",
            "h4",
            "h3",
        ):
            candidate = container.select_one(selector)
            if isinstance(candidate, Tag):
                text = _clean_text(candidate.get_text(" ", strip=True))
                if text:
                    return text

    placeholder = _clean_text(control.get("placeholder"))
    if placeholder and placeholder.lower() not in {"type your response", "select...", "select"}:
        return placeholder
    return _clean_text(control.get("name"))


def _raw_local_label(form: Tag, control: Tag) -> str:
    """Return nearby unstripped text so visual required markers can be detected."""

    pieces: List[str] = []
    control_id = str(control.get("id") or "").strip()
    if control_id:
        label = form.find("label", attrs={"for": control_id})
        if isinstance(label, Tag):
            pieces.append(label.get_text(" ", strip=True))
    parent_label = control.find_parent("label")
    if isinstance(parent_label, Tag):
        pieces.append(parent_label.get_text(" ", strip=True))
    fieldset = control.find_parent("fieldset")
    if isinstance(fieldset, Tag):
        legend = fieldset.find("legend")
        if isinstance(legend, Tag):
            pieces.append(legend.get_text(" ", strip=True))
    container = _question_container(control)
    if isinstance(container, Tag):
        for selector in (
            "legend",
            ".application-label",
            ".application-field-label",
            ".application-question-label",
            "label",
        ):
            candidate = container.select_one(selector)
            if isinstance(candidate, Tag):
                pieces.append(candidate.get_text(" ", strip=True))
    return " ".join(pieces)


def _is_required(form: Tag, control: Tag) -> bool:
    if control.has_attr("required"):
        return True
    if str(control.get("aria-required") or "").strip().lower() == "true":
        return True
    if str(control.get("data-required") or "").strip().lower() == "true":
        return True
    if "required" in _class_tokens(control):
        return True

    container = _question_container(control)
    if "required" in _class_tokens(container):
        return True
    local_text = _raw_local_label(form, control)
    return any(marker in local_text for marker in _REQUIRED_MARKERS)


def _control_kind(control: Tag) -> str:
    if control.name == "textarea":
        return "text"
    if control.name == "select":
        return "select"
    input_type = str(control.get("type") or "text").strip().lower()
    if input_type == "file":
        return "file"
    if input_type == "radio":
        return "radio"
    if input_type == "checkbox":
        return "checkbox"
    if str(control.get("role") or "").strip().lower() == "combobox":
        return "combobox"
    return "text"


def _label_for_option(form: Tag, option: Tag) -> str:
    option_id = str(option.get("id") or "").strip()
    if option_id:
        label = form.find("label", attrs={"for": option_id})
        if isinstance(label, Tag):
            text = _clean_text(label.get_text(" ", strip=True))
            if text:
                return text
    parent = option.find_parent("label")
    if isinstance(parent, Tag):
        text = _clean_text(parent.get_text(" ", strip=True))
        if text:
            return text
    return _clean_text(option.get("value"))


def _options_for_control(form: Tag, control: Tag) -> List[str]:
    values: List[str] = []
    if control.name == "select":
        for option in control.find_all("option"):
            text = _clean_text(option.get_text(" ", strip=True) or option.get("value"))
            if text and text.lower() not in {"select", "select...", "choose", "choose one"}:
                values.append(text)
    elif _control_kind(control) in {"radio", "checkbox"}:
        name = str(control.get("name") or "").strip()
        if name:
            siblings = form.find_all("input", attrs={"name": name})
        else:
            siblings = [control]
        for item in siblings:
            if isinstance(item, Tag):
                text = _label_for_option(form, item)
                if text:
                    values.append(text)
    return list(dict.fromkeys(values))


def _stable_required_controls(form: Tag) -> List[Dict[str, Any]]:
    required: List[Dict[str, Any]] = []
    seen_groups: set[tuple[str, str]] = set()

    for control in form.find_all(["input", "select", "textarea"]):
        if not isinstance(control, Tag):
            continue
        input_type = str(control.get("type") or "text").strip().lower()
        if control.name == "input" and input_type in _IGNORED_INPUT_TYPES:
            continue
        if not _is_required(form, control):
            continue

        kind = _control_kind(control)
        name = _clean_text(control.get("name"))
        if kind in {"radio", "checkbox"} and name:
            group_key = (kind, name)
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)

        descriptor = _label_for_control(form, control)
        if not descriptor:
            # A required control that cannot be described cannot be certified safely.
            descriptor = "<unlabeled-required-control>"

        item: Dict[str, Any] = {
            "descriptor": descriptor,
            "control_type": kind,
            "required": True,
            "options": _options_for_control(form, control),
        }
        if kind == "file":
            item["accept"] = _clean_text(control.get("accept"))
        required.append(item)

    required.sort(
        key=lambda item: (
            str(item.get("descriptor") or "").casefold(),
            str(item.get("control_type") or ""),
            _canonical_json(item.get("options") or []),
        )
    )
    return required


def _schema_hash(required_controls: List[Dict[str, Any]]) -> str:
    public_controls = [
        {
            "descriptor": item.get("descriptor"),
            "control_type": item.get("control_type"),
            "required": True,
            "options": list(item.get("options") or []),
            "accept": item.get("accept") or "",
        }
        for item in required_controls
    ]
    return _hash_value({
        "version": LEVER_FORM_SCHEMA_FINGERPRINT_VERSION,
        "required_controls": public_controls,
    })


def _readiness_for_control(
    item: Mapping[str, Any],
    *,
    profile: Mapping[str, Any],
    profile_values: Mapping[str, str],
    policies: Iterable[Dict[str, Any]],
    resume_path: str,
    cover_letter_path: str,
    portfolio_path: str,
) -> Dict[str, Any]:
    descriptor = str(item.get("descriptor") or "").strip()
    kind = str(item.get("control_type") or "text")

    if descriptor == "<unlabeled-required-control>":
        return {
            "ready": False,
            "descriptor": descriptor,
            "control_type": kind,
            "canonical_key": "custom.unclassified",
            "sensitivity": "standard",
            "reason": "Required control could not be described safely.",
            "blocker_codes": ["required_control_unlabeled"],
        }

    if kind == "file":
        upload_type = _classify_upload(f" {descriptor} ")
        paths = {
            "resume": resume_path,
            "cover_letter": cover_letter_path,
            "portfolio": portfolio_path,
        }
        path = paths.get(upload_type or "", "")
        accept = str(item.get("accept") or "")
        ready = bool(
            upload_type
            and path
            and os.path.isfile(path)
            and _path_matches_accept(path, accept)
        )
        return {
            "ready": ready,
            "descriptor": descriptor,
            "control_type": kind,
            "upload_type": upload_type,
            "reason": None if ready else "Required upload is missing, unrecognized, or has an unsupported file type.",
            "blocker_codes": [] if ready else ["required_upload_unresolved"],
        }

    # Plain text-like controls can use deterministic profile fields. Comboboxes,
    # selects, radios, and checkboxes intentionally require an approved policy because
    # option matching is semantic and the runtime control engine is policy-gated.
    if kind == "text":
        safe_field = _safe_field(descriptor)
        if safe_field and str(profile_values.get(safe_field) or "").strip():
            return {
                "ready": True,
                "descriptor": descriptor,
                "control_type": kind,
                "profile_field": safe_field,
                "canonical_key": None,
                "sensitivity": "standard",
                "reason": None,
                "blocker_codes": [],
            }

    policy = resolve_control_policy(descriptor, policies)
    return {
        "ready": bool(policy.get("can_autofill")),
        "descriptor": descriptor,
        "control_type": kind,
        "canonical_key": policy.get("canonical_key"),
        "category": policy.get("category"),
        "sensitivity": policy.get("sensitivity"),
        "policy_id": (policy.get("policy") or {}).get("id") if policy.get("matched") else None,
        "reason": policy.get("reason"),
        "blocker_codes": list(policy.get("blocker_codes") or (["approved_answer_policy_missing"] if not policy.get("matched") else [])),
    }


def inspect_lever_form_html(
    html: str,
    *,
    profile: Mapping[str, Any],
    cover_letter: str,
    policies: Iterable[Dict[str, Any]],
    resume_path: str = "",
    cover_letter_path: str = "",
    portfolio_path: str = "",
) -> Dict[str, Any]:
    """Inspect one public Lever apply page and prove every required control is resolvable."""

    result: Dict[str, Any] = {
        "checked": True,
        "verified": False,
        "ready": False,
        "status_code": None,
        "schema_hash": None,
        "fingerprint_version": LEVER_FORM_SCHEMA_FINGERPRINT_VERSION,
        "question_count": None,
        "required_question_count": None,
        "required_uploads": [],
        "unsupported_fields": [],
        "unresolved_required_questions": [],
        "resolved_required_count": 0,
        "blocker": "application_form_schema_unverified",
    }

    try:
        soup = BeautifulSoup(str(html or ""), "lxml")
    except Exception:
        return result

    form = soup.select_one("form.application-form") or soup.select_one(
        'form[action*="lever.co"]'
    )
    if not isinstance(form, Tag):
        return result

    required_controls = _stable_required_controls(form)
    # Every real Lever apply form has at least the system name/email surface. Zero
    # required controls means the parser cannot prove it is looking at the form.
    if not required_controls:
        return result

    profile_values = _profile_values(dict(profile), cover_letter)
    resolutions = [
        _readiness_for_control(
            item,
            profile=profile,
            profile_values=profile_values,
            policies=policies,
            resume_path=resume_path,
            cover_letter_path=cover_letter_path,
            portfolio_path=portfolio_path,
        )
        for item in required_controls
    ]
    unresolved = [item for item in resolutions if not item.get("ready")]
    required_uploads = [
        item.get("upload_type") or "unclassified"
        for item in resolutions
        if item.get("control_type") == "file"
    ]

    result.update({
        "verified": True,
        "ready": not unresolved,
        "schema_hash": _schema_hash(required_controls),
        "question_count": len(required_controls),
        "required_question_count": len(required_controls),
        "required_uploads": list(dict.fromkeys(required_uploads)),
        "unsupported_fields": [
            item["descriptor"]
            for item in unresolved
            if "required_control_unlabeled" in (item.get("blocker_codes") or [])
        ],
        "unresolved_required_questions": unresolved,
        "resolved_required_count": len(required_controls) - len(unresolved),
        "blocker": None if not unresolved else "application_form_required_questions_unresolved",
    })
    return result


def lever_form_readiness_status(
    application_url: str,
    *,
    profile: Mapping[str, Any],
    cover_letter: str,
    policies: Iterable[Dict[str, Any]],
    resume_path: str = "",
    cover_letter_path: str = "",
    portfolio_path: str = "",
) -> Dict[str, Any]:
    """Fetch the exact public Lever form, certify structure, and evaluate readiness."""

    result: Dict[str, Any] = {
        "checked": True,
        "verified": False,
        "ready": False,
        "status_code": None,
        "schema_hash": None,
        "fingerprint_version": LEVER_FORM_SCHEMA_FINGERPRINT_VERSION,
        "question_count": None,
        "required_question_count": None,
        "required_uploads": [],
        "unsupported_fields": [],
        "unresolved_required_questions": [],
        "resolved_required_count": 0,
        "blocker": "application_form_schema_unverified",
    }
    original_url = str(application_url or "").strip()
    if _lever_host(original_url) not in _ALLOWED_LEVER_HOSTS:
        return result

    try:
        response = httpx.get(
            original_url,
            follow_redirects=True,
            timeout=LEVER_FORM_SCHEMA_TIMEOUT_SECONDS,
            headers={
                "User-Agent": "JobTomatik/1.0 supervised-lever-form-readiness",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
    except (httpx.HTTPError, ValueError):
        return result

    result["status_code"] = int(response.status_code)
    if response.status_code in {404, 410}:
        result["blocker"] = "application_target_closed_or_expired"
        return result
    if response.status_code >= 400:
        return result
    if _lever_host(str(response.url)) not in _ALLOWED_LEVER_HOSTS:
        return result

    inspected = inspect_lever_form_html(
        response.text,
        profile=profile,
        cover_letter=cover_letter,
        policies=policies,
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
        portfolio_path=portfolio_path,
    )
    inspected["status_code"] = int(response.status_code)
    return inspected


__all__ = [
    "LEVER_FORM_SCHEMA_FINGERPRINT_VERSION",
    "inspect_lever_form_html",
    "lever_form_readiness_status",
]
