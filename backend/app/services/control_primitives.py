"""Shared primitives for the standards-oriented application control engine."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.answer_policy import review_reason_for_question

CONTROL_ENGINE_VERSION = "2.0.0"

_YES = {
    "yes", "y", "true", "1", "agree", "i agree", "accepted", "accept",
    "authorized", "eligible", "willing", "available", "oui", "vrai", "j accepte",
}
_NO = {
    "no", "n", "false", "0", "decline", "declined", "do not agree",
    "not authorized", "not eligible", "not willing", "non", "faux", "je refuse",
}
_PLACEHOLDERS = {
    "", "select", "select one", "choose", "choose one", "please select",
    "make a selection", "--", "none selected",
}


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold()
    text = re.sub(r"[\u2018\u2019\u201c\u201d]", "'", text)
    text = re.sub(r"[^a-z0-9+#./' -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def boolean_value(value: Any) -> Optional[bool]:
    normalized = normalize_text(value)
    if normalized in _YES:
        return True
    if normalized in _NO:
        return False
    return None


def parse_policy_answers(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            decoded = json.loads(text)
            if isinstance(decoded, list):
                return [str(item).strip() for item in decoded if str(item).strip()]
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    if any(separator in text for separator in (";", "\n", "|")):
        return [part.strip() for part in re.split(r"[;\n|]+", text) if part.strip()]
    return [text]


@dataclass(frozen=True)
class OptionRecord:
    key: str
    label: str
    value: str
    disabled: bool = False
    selected: bool = False

    @property
    def normalized_label(self) -> str:
        return normalize_text(self.label)

    @property
    def normalized_value(self) -> str:
        return normalize_text(self.value)


@dataclass
class MatchResult:
    matched: List[OptionRecord] = field(default_factory=list)
    missing_answers: List[str] = field(default_factory=list)
    ambiguous_answers: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.missing_answers and not self.ambiguous_answers


@dataclass
class ControlEngineOutcome:
    filled_count: int = 0
    review_items: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    passes: int = 0


def _score(answer: str, option: OptionRecord) -> int:
    normalized_answer = normalize_text(answer)
    label = option.normalized_label
    value = option.normalized_value
    if not normalized_answer or option.disabled:
        return 0
    if normalized_answer == label or normalized_answer == value:
        return 100

    answer_bool = boolean_value(normalized_answer)
    if answer_bool is not None and (
        answer_bool == boolean_value(label) or answer_bool == boolean_value(value)
    ):
        return 92

    answer_tokens = set(normalized_answer.split())
    label_tokens = set(label.split())
    if answer_tokens and label_tokens:
        union = answer_tokens | label_tokens
        if union and len(answer_tokens & label_tokens) / len(union) >= 0.85:
            return 84

    if len(normalized_answer) >= 3 and (
        normalized_answer in label or label in normalized_answer
        or normalized_answer in value or value in normalized_answer
    ):
        return 70
    return 0


def match_answers_to_options(
    answers: Sequence[str],
    options: Sequence[OptionRecord],
    *,
    allow_multiple: bool,
) -> MatchResult:
    result = MatchResult()
    usable = [
        option for option in options
        if not option.disabled
        and option.normalized_label not in _PLACEHOLDERS
        and option.normalized_value not in _PLACEHOLDERS
    ]
    if not allow_multiple and len(answers) != 1:
        result.missing_answers.extend(answers or ["exactly one answer required"])
        return result

    used: set[str] = set()
    for answer in answers:
        scored: List[Tuple[int, OptionRecord]] = [
            (_score(answer, option), option)
            for option in usable
            if option.key not in used
        ]
        top = max((score for score, _ in scored), default=0)
        if top <= 0:
            result.missing_answers.append(answer)
            continue
        candidates = [option for score, option in scored if score == top]
        unique = {(item.normalized_label, item.normalized_value) for item in candidates}
        if len(unique) > 1:
            result.ambiguous_answers[answer] = [item.label or item.value for item in candidates]
            continue
        selected = candidates[0]
        result.matched.append(selected)
        used.add(selected.key)
    return result


def options_fingerprint(options: Sequence[OptionRecord]) -> str:
    payload = [
        {
            "key": item.key,
            "label": item.normalized_label,
            "value": item.normalized_value,
            "disabled": item.disabled,
        }
        for item in options
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


async def element_text(element) -> str:
    try:
        return re.sub(r"\s+", " ", await element.inner_text()).strip()
    except Exception:
        return ""


async def element_descriptor(page, element) -> str:
    descriptor = await element.evaluate(
        """(el) => {
          const pieces = [];
          const push = (value) => {
            const clean = String(value || '').replace(/\s+/g, ' ').trim();
            if (clean && !pieces.includes(clean)) pieces.push(clean);
          };
          ['name','id','placeholder','aria-label','autocomplete',
           'data-testid','data-qa','data-automation-id'].forEach(
            (name) => push(el.getAttribute(name))
          );
          if (el.labels) Array.from(el.labels).forEach((label) => push(label.innerText));
          (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)
            .forEach((id) => push(document.getElementById(id)?.innerText));
          (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean)
            .forEach((id) => push(document.getElementById(id)?.innerText));
          const group = el.closest('fieldset,[role="radiogroup"],[role="group"]');
          if (group) {
            push(group.getAttribute('aria-label'));
            push(group.querySelector(':scope > legend')?.innerText);
          }
          push(el.closest('label')?.innerText);
          if (pieces.join(' ').length < 40) push(el.parentElement?.innerText);
          return pieces.join(' | ');
        }"""
    )
    return re.sub(r"\s+", " ", descriptor or "").strip()


async def is_actionable(element) -> bool:
    try:
        if not await element.is_visible():
            return False
    except Exception:
        pass
    if await element.get_attribute("disabled") is not None:
        return False
    if await element.get_attribute("readonly") is not None:
        return False
    if normalize_text(await element.get_attribute("aria-disabled")) == "true":
        return False
    try:
        return await element.is_enabled()
    except Exception:
        return True


async def is_required(element, group=None) -> bool:
    for target in (element, group):
        if target is None:
            continue
        if await target.get_attribute("required") is not None:
            return True
        if normalize_text(await target.get_attribute("aria-required")) == "true":
            return True
        if normalize_text(await target.get_attribute("data-required")) == "true":
            return True
    return False


def make_review(
    *,
    descriptor: str,
    control_type: str,
    policy_result: Dict[str, Any],
    required: bool,
    options: Sequence[OptionRecord] = (),
    reason_code: Optional[str] = None,
    summary: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    reason = reason_code or review_reason_for_question(policy_result)
    payload = {
        "canonical_key": policy_result.get("canonical_key", "custom.unclassified"),
        "category": policy_result.get("category"),
        "sensitivity": policy_result.get("sensitivity"),
        "descriptor": descriptor,
        "control_type": control_type,
        "required": required,
        "policy_reason": policy_result.get("reason"),
        "available_options": [
            {"label": item.label, "value": item.value, "disabled": item.disabled}
            for item in options
        ],
        "control_engine_version": CONTROL_ENGINE_VERSION,
    }
    payload.update(details or {})
    return {
        "reason_code": reason,
        "summary": summary or f"Approved answer required for: {descriptor}",
        "details": payload,
    }


def append_review(items: List[Dict[str, Any]], item: Dict[str, Any]) -> None:
    signature = (
        item.get("reason_code"),
        item.get("details", {}).get("descriptor"),
        item.get("details", {}).get("control_type"),
    )
    for existing in items:
        if signature == (
            existing.get("reason_code"),
            existing.get("details", {}).get("descriptor"),
            existing.get("details", {}).get("control_type"),
        ):
            return
    items.append(item)


def make_evidence(
    *,
    control_id: str,
    control_type: str,
    descriptor: str,
    policy_result: Dict[str, Any],
    options: Sequence[OptionRecord],
    selected: Sequence[OptionRecord],
    pass_number: int,
) -> Dict[str, Any]:
    return {
        "action": "control_verified",
        "control_engine_version": CONTROL_ENGINE_VERSION,
        "control_id": control_id,
        "control_type": control_type,
        "descriptor": descriptor,
        "canonical_key": policy_result.get("canonical_key"),
        "policy_id": (policy_result.get("policy") or {}).get("id"),
        "selected": [{"label": item.label, "value": item.value} for item in selected],
        "options_fingerprint": options_fingerprint(options),
        "verification": "passed",
        "pass": pass_number,
    }
