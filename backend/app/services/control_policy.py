"""Specificity-aware policy resolution for browser controls."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from app.models.answer_policy import AnswerPolicyMode
from app.services.answer_policy import QUESTION_CATALOG, normalize_question_text

_EXTRA_PATTERNS = {
    "data_processing_consent": [
        r"(?:consent|agree).{0,50}(?:processing|retaining).{0,30}(?:applicant )?data",
        r"(?:processing|retaining).{0,30}(?:applicant )?data",
    ],
}


def classify_control_question(question_text: str) -> Dict[str, str]:
    normalized = normalize_question_text(question_text)
    matches = []
    for index, item in enumerate(QUESTION_CATALOG):
        patterns = list(item["patterns"]) + _EXTRA_PATTERNS.get(item["canonical_key"], [])
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                matches.append((len(match.group(0)), -index, item))

    if matches:
        _, _, item = max(matches, key=lambda value: (value[0], value[1]))
        return {
            "canonical_key": item["canonical_key"],
            "category": item["category"],
            "sensitivity": item["sensitivity"],
            "label": item["label"],
        }
    return {
        "canonical_key": "custom.unclassified",
        "category": "custom",
        "sensitivity": "standard",
        "label": "Unclassified application question",
    }


def resolve_control_policy(
    question_text: str,
    policies: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    classification = classify_control_question(question_text)
    normalized = normalize_question_text(question_text)
    candidates: List[Dict[str, Any]] = []

    for policy in policies:
        canonical_key = policy.get("canonical_key", "")
        if canonical_key == classification["canonical_key"]:
            candidates.append(policy)
            continue
        if canonical_key.startswith("custom.") and any(
            normalize_question_text(phrase) in normalized
            for phrase in policy.get("match_phrases", [])
            if phrase
        ):
            candidates.append(policy)

    policy = candidates[0] if candidates else None
    if not policy:
        return {
            **classification,
            "matched": False,
            "can_autofill": False,
            "reason": "No approved answer policy exists for this question.",
        }

    mode = policy.get("mode", AnswerPolicyMode.ask_each_time.value)
    answer = policy.get("answer_label") or policy.get("answer_value")
    confirmed = bool(policy.get("confirmed_at"))
    can_autofill = (
        mode in {AnswerPolicyMode.answer.value, AnswerPolicyMode.decline.value}
        and bool(policy.get("allow_autofill"))
        and confirmed
        and bool(answer)
    )

    reason = None
    if mode == AnswerPolicyMode.ask_each_time.value:
        reason = "The answer policy requires a fresh user decision."
    elif mode == AnswerPolicyMode.skip.value:
        reason = "The answer policy explicitly forbids answering this question."
    elif not confirmed:
        reason = "The stored answer has not been confirmed by the user."
    elif not policy.get("allow_autofill"):
        reason = "The user has not authorized automatic use of this answer."
    elif not answer:
        reason = "The approved policy has no usable answer value."

    return {
        **classification,
        "matched": True,
        "can_autofill": can_autofill,
        "reason": reason,
        "policy": policy,
        "answer": answer,
    }
