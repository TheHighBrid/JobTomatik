"""Specificity-aware policy resolution for browser controls."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from app.models.answer_policy import AnswerPolicyMode
from app.services.answer_policy import (
    QUESTION_CATALOG,
    conflicting_top_policies,
    normalize_question_text,
    policy_answer_candidates,
    policy_autofill_blockers,
    scope_priority,
)

_EXTRA_PATTERNS = {
    "data_processing_consent": [
        r"(?:consent|agree).{0,50}(?:processing|retaining).{0,30}(?:applicant )?data",
        r"(?:processing|retaining).{0,30}(?:applicant )?data",
    ],
}

# ``privacy_consent`` existed in early policy payloads before consent was split into
# application terms and applicant-data processing. It remains an explicit user-approved
# yes/no decision, so map it only to those two consent classifications rather than
# treating it as a fuzzy custom-question fallback.
_CANONICAL_POLICY_ALIASES = {
    "privacy_consent": {"terms_consent", "data_processing_consent"},
}

_REASON_BY_CODE = {
    "policy_inactive": "The answer policy is inactive.",
    "policy_expired": "The stored answer policy has expired and must be reviewed.",
    "policy_encryption_invalid": "The encrypted answer could not be verified.",
    "policy_provenance_unknown": "The answer provenance is unknown.",
    "policy_confidence_low": "The answer confidence is below the automatic-use threshold.",
    "policy_not_confirmed": "The stored answer has not been confirmed by the user.",
    "policy_consent_missing": "The stored consent record does not authorize automatic use.",
    "policy_autofill_not_authorized": "The user has not authorized automatic use of this answer.",
    "policy_answer_missing": "The approved policy has no usable answer value.",
}


def _custom_phrase_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _custom_phrase_matches(phrase: str, question_text: str) -> bool:
    """Ignore punctuation while matching whole normalized phrase tokens."""
    target = _custom_phrase_text(phrase)
    question = _custom_phrase_text(question_text)
    if not target:
        return False
    return target == question or f" {target} " in f" {question} "


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


def _interactive_reason(mode: str) -> str:
    if mode == AnswerPolicyMode.ask_each_time.value:
        return "The answer policy requires a fresh user decision."
    return "The answer policy explicitly forbids answering this question."


def resolve_control_policy(
    question_text: str,
    policies: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Resolve one control using precise matching and the shared Vault safety gates."""

    classification = classify_control_question(question_text)
    candidates: List[tuple[int, int, Dict[str, Any]]] = []

    for index, policy in enumerate(policies):
        canonical_key = policy.get("canonical_key", "")
        classified_key = classification["canonical_key"]
        score = 0
        if canonical_key == classified_key:
            score = 200
        elif classified_key in _CANONICAL_POLICY_ALIASES.get(canonical_key, set()):
            score = 150

        matching_phrases = [
            phrase
            for phrase in policy.get("match_phrases", [])
            if phrase and _custom_phrase_matches(phrase, question_text)
        ]
        if canonical_key.startswith("custom.") and matching_phrases:
            score = 300 + max(
                len(_custom_phrase_text(phrase)) for phrase in matching_phrases
            )

        if score:
            candidates.append((score, -index, policy))

    if not candidates:
        return {
            **classification,
            "matched": False,
            "can_autofill": False,
            "reason": "No approved answer policy exists for this question.",
        }

    highest_match_score = max(item[0] for item in candidates)
    matched = [item for item in candidates if item[0] == highest_match_score]
    highest_scope = max(scope_priority(item[2].get("scope")) for item in matched)
    top = [item for item in matched if scope_priority(item[2].get("scope")) == highest_scope]
    conflicts = conflicting_top_policies(item[2] for item in top)
    if conflicts:
        return {
            **classification,
            "matched": True,
            "can_autofill": False,
            "reason": "Conflicting answer policies exist at the same scope priority.",
            "blocker_codes": ["policy_scope_conflict"],
            "conflict_policy_ids": [item.get("id") for item in conflicts],
        }

    policy = max(top, key=lambda item: item[1])[2]
    mode = policy.get("mode", AnswerPolicyMode.ask_each_time.value)
    answer_candidates = policy_answer_candidates(policy)
    answer = answer_candidates[0] if answer_candidates else None
    blocker_codes = list(policy_autofill_blockers(policy))

    # Missing consent is unsafe, not a legacy opt-in. The Vault's automatic-use path
    # requires an affirmative consent record even when allow_autofill is true.
    consent_metadata = dict(policy.get("consent_metadata") or {})
    if consent_metadata.get("autofill_authorized") is not True:
        if "policy_consent_missing" not in blocker_codes:
            blocker_codes.append("policy_consent_missing")

    can_autofill = not blocker_codes
    if blocker_codes and blocker_codes[0] == "policy_interactive_mode":
        reason = _interactive_reason(mode)
    else:
        reason = _REASON_BY_CODE.get(blocker_codes[0]) if blocker_codes else None

    return {
        **classification,
        "matched": True,
        "can_autofill": can_autofill,
        "reason": reason,
        "blocker_codes": blocker_codes,
        "policy": policy,
        "answer": answer,
        "answer_candidates": answer_candidates,
    }
