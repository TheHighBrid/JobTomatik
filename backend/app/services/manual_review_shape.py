from __future__ import annotations

import re
from typing import Any, Mapping, MutableMapping

POLICY_REVIEW_REASONS = frozenset({
    "ambiguous_question",
    "legal_answer_missing",
    "sensitive_answer_missing",
})
FINAL_SUBMIT_REASON = "operator_final_submit_required"
_POLICY_QUESTION_SUMMARY_RE = re.compile(
    r"^\d+ application question\(s\) require an approved answer policy\.$"
)


def retained_questions(details: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    raw = dict(details or {}).get("questions") or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _looks_like_retained_question_item(item: Mapping[str, Any] | None) -> bool:
    if not isinstance(item, Mapping):
        return False
    details = item.get("details")
    if not isinstance(details, Mapping):
        return False
    descriptor = str(details.get("descriptor") or "").strip()
    control_type = str(details.get("control_type") or "").strip()
    return bool(descriptor and control_type and "required" in details)


def normalize_misclassified_question_review_items(result: MutableMapping[str, Any]) -> int:
    """Repair malformed question items before manual-review grouping persists them.

    A genuine operator final-submit item has final-action metadata and no employer
    question descriptor. If a descriptor-bearing required control somehow arrives with
    the final-submit reason, normalize only that item back to the fail-closed ambiguous
    question reason. This prevents the contradictory persisted review shape observed on
    Caseware while leaving the real final-submit boundary untouched.
    """

    changed = 0
    raw_items = result.get("review_items") or []
    if not isinstance(raw_items, list):
        return 0
    for item in raw_items:
        if not isinstance(item, MutableMapping):
            continue
        if str(item.get("reason_code") or "") != FINAL_SUBMIT_REASON:
            continue
        if not _looks_like_retained_question_item(item):
            continue
        item["reason_code"] = "ambiguous_question"
        changed += 1
    return changed


def is_misclassified_answer_policy_review_shape(
    *,
    reason_code: str | None,
    summary: str | None,
    details: Mapping[str, Any] | None,
) -> bool:
    """Recognize the exact corrupted review shape seen in operator-assisted Lever prep.

    A genuine final-submit review has final-action metadata and a final-action summary.
    The corrupted state instead carries the system-generated answer-policy summary plus
    retained employer question records. Keep this deliberately narrow so normal final
    submit reviews can never be reinterpreted as policy reviews.
    """

    if str(reason_code or "") != FINAL_SUBMIT_REASON:
        return False
    if not _POLICY_QUESTION_SUMMARY_RE.fullmatch(str(summary or "").strip()):
        return False
    return bool(retained_questions(details))


def effective_answer_policy_reason(
    *,
    reason_code: str | None,
    summary: str | None,
    details: Mapping[str, Any] | None,
) -> str:
    reason = str(reason_code or "")
    if reason in POLICY_REVIEW_REASONS:
        return reason
    if not is_misclassified_answer_policy_review_shape(
        reason_code=reason,
        summary=summary,
        details=details,
    ):
        return reason

    nested = {
        str(item.get("reason_code") or "")
        for item in retained_questions(details)
        if str(item.get("reason_code") or "") in POLICY_REVIEW_REASONS
    }
    if len(nested) == 1:
        return next(iter(nested))
    return "ambiguous_question"


__all__ = [
    "FINAL_SUBMIT_REASON",
    "POLICY_REVIEW_REASONS",
    "effective_answer_policy_reason",
    "is_misclassified_answer_policy_review_shape",
    "normalize_misclassified_question_review_items",
    "retained_questions",
]
