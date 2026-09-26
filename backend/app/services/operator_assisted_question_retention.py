"""
Question-boundary policy for operator-assisted preparation.

Unknown employer questions are durable *policy* review boundaries, not durable browser

Unknown employer questions are durable *policy* review boundaries, not durable browser
handoffs. The owner answers them in JobTomatik and the next Prepare performs a fresh,
fill-only pass using the newly approved policy.

Historically this module retained the Android Chrome controlled tab even though no
ManualHandoffSession was created for ambiguous questions. That orphaned a JobTomatik-
owned target after the first pass and could wedge Android Chrome target creation on the
second Prepare, poisoning later applications too. Question boundaries now deliberately
remain non-resumable so normal browser cleanup closes the owned tab before reprepare.
Security boundaries and the final-submit handoff remain resumable elsewhere.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from app.models.application import ManualReviewReason


QUESTION_REASON = ManualReviewReason.ambiguous_question.value
_INSTALLED = False


def _review_reasons(result: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("reason_code") or "")
        for item in result.get("review_items") or []
        if isinstance(item, Mapping)
    }


def is_operator_question_review_result(result: Mapping[str, Any] | None) -> bool:
    """Return whether the result stopped on an unresolved employer question."""

    if not isinstance(result, Mapping):
    """
    Keep question reviews non-resumable so the controlled tab is released.

    This function remains as an idempotent compatibility hook because the operator
    preparation task imports and calls it. No global handoff predicate is patched.
    """
    global _INSTALLED
    _INSTALLED = True


def summarize_operator_question_retention_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Report the safe fresh-reprepare contract without leaking browser snapshots."""

    normalized = dict(result or {})
    if not is_operator_question_review_result(normalized):
        return normalized

    # Defensive cleanup for older/injected runners. The live form runner no longer
    # captures a handoff snapshot for ambiguous questions because they are not a
    # resumable boundary, but never return one if a compatibility path supplied it.
    normalized.pop("handoff_snapshot", None)
    normalized["operator_question_review_page_retained"] = False
    normalized["operator_question_review_handoff_created"] = False
    normalized["requires_answer_policy_review"] = True
    normalized["requires_fresh_reprepare_after_answer_policy"] = True
    normalized["operator_question_reprepare_releases_previous_tab"] = True
    normalized["automated_submission_authorized"] = False
    normalized["final_submit_clicked_by_jobtomatik"] = False
    return normalized


__all__ = [
    "install_operator_assisted_question_retention",
    "is_operator_question_review_result",
    "summarize_operator_question_retention_result",
]
