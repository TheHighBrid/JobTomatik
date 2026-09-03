"""Retain unresolved employer-question pages only for operator-assisted preparation.

This module deliberately does not make ``ambiguous_question`` a globally resumable
handoff reason. Normal dry runs keep their historical cleanup behavior. The dedicated
operator-assisted preparation task already binds an exact verified target and forbids
both automated submission and the final Submit click; within that context only, an
unresolved employer-question stop may keep the controlled browser page open long
enough for the owner to inspect the exact questions and approve answer policies.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from app.models.application import ManualReviewReason
from app.services.operator_assisted_handoff_integration import (
    current_operator_prepare_target,
)


QUESTION_REASON = ManualReviewReason.ambiguous_question.value
_INSTALLED = False
_ORIGINAL_RESUMABLE_BOUNDARY = None


def _review_reasons(result: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("reason_code") or "")
        for item in result.get("review_items") or []
        if isinstance(item, Mapping)
    }


def is_operator_question_review_result(result: Mapping[str, Any] | None) -> bool:
    """Return whether the result stopped on an unresolved employer question."""

    if not isinstance(result, Mapping):
        return False
    return bool(
        result.get("requires_manual_review")
        and QUESTION_REASON in _review_reasons(result)
    )


def _operator_question_review_boundary(result: Mapping[str, Any]) -> bool:
    """Allow page retention only while the exact operator prepare scope is active."""

    target = current_operator_prepare_target()
    return bool(target) and is_operator_question_review_result(result)


def install_operator_assisted_question_retention() -> None:
    """Install one context-gated extension around the handoff retention predicate."""

    global _INSTALLED, _ORIGINAL_RESUMABLE_BOUNDARY
    if _INSTALLED:
        return

    from app.services import form_filler_handoff as handoff_filler

    _ORIGINAL_RESUMABLE_BOUNDARY = handoff_filler._resumable_boundary

    def scoped_resumable_boundary(result: Dict[str, Any]) -> bool:
        if _ORIGINAL_RESUMABLE_BOUNDARY(result):
            return True
        return _operator_question_review_boundary(result)

    handoff_filler._resumable_boundary = scoped_resumable_boundary
    _INSTALLED = True


def summarize_operator_question_retention_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Strip raw snapshot data while reporting that the live page was intentionally kept.

    ``fill_and_submit_application_with_handoff`` captures a browser snapshot before
    releasing its Playwright attachment. For ambiguous questions the normal handoff
    database layer still rejects the reason as non-resumable, by design. We therefore
    remove the raw snapshot from the Celery result while keeping a small, non-secret
    receipt that tells the operator the exact browser page was left open for inspection.
    """

    normalized = dict(result or {})
    if not is_operator_question_review_result(normalized):
        return normalized

    snapshot = normalized.pop("handoff_snapshot", None)
    if not isinstance(snapshot, Mapping):
        return normalized

    normalized["operator_question_review_page_retained"] = True
    normalized["operator_question_review_url"] = (
        snapshot.get("current_url")
        or normalized.get("application_url")
        or normalized.get("url")
    )
    normalized["operator_question_review_browser_provider"] = snapshot.get(
        "browser_provider"
    )
    normalized["operator_question_review_handoff_created"] = False
    normalized["requires_answer_policy_review"] = True
    normalized["requires_fresh_reprepare_after_answer_policy"] = True
    normalized["automated_submission_authorized"] = False
    normalized["final_submit_clicked_by_jobtomatik"] = False
    return normalized


__all__ = [
    "install_operator_assisted_question_retention",
    "is_operator_question_review_result",
    "summarize_operator_question_retention_result",
]
