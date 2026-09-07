from __future__ import annotations

from typing import Any, Dict, Iterable, List

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.services.answer_policy import load_runtime_policies
from app.services.application_state import (
    normalize_state,
    resolve_manual_review_task,
    transition_application_state,
)
from app.services.control_policy import resolve_control_policy
from app.services.control_primitives import (
    OptionRecord,
    match_answer_candidates_to_options,
)

POLICY_REVIEW_REASONS = {
    ManualReviewReason.ambiguous_question.value,
    ManualReviewReason.legal_answer_missing.value,
    ManualReviewReason.sensitive_answer_missing.value,
}

_OPTION_CONTROL_TYPES = {
    "radio",
    "checkbox",
    "checkbox_group",
    "select",
    "combobox",
    "listbox",
}


class ManualReviewPolicyRevalidationError(ValueError):
    pass


def _retained_questions(review: ManualReviewTask) -> List[Dict[str, Any]]:
    details = dict(review.details or {})
    questions = details.get("questions") or []
    if not isinstance(questions, list):
        return []
    return [item for item in questions if isinstance(item, dict)]


def _option_records(raw_options: Iterable[Dict[str, Any]]) -> List[OptionRecord]:
    options: List[OptionRecord] = []
    for index, raw in enumerate(raw_options or []):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        value = str(raw.get("value") or label).strip()
        if not label and not value:
            continue
        options.append(
            OptionRecord(
                key=f"retained:{index}",
                label=label or value,
                value=value or label,
                disabled=bool(raw.get("disabled", False)),
            )
        )
    return options


def _question_result(
    question: Dict[str, Any],
    policies: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    details = dict(question.get("details") or {})
    descriptor = str(details.get("descriptor") or "").strip()
    control_type = str(details.get("control_type") or "").strip().lower()
    retained_key = str(details.get("canonical_key") or "custom.unclassified")

    if not descriptor:
        return {
            "descriptor": "",
            "canonical_key": retained_key,
            "ready": False,
            "reason": "The retained review does not contain the employer question text.",
            "blocker_codes": ["retained_question_descriptor_missing"],
        }

    resolution = resolve_control_policy(descriptor, policies)
    result = {
        "descriptor": descriptor,
        "canonical_key": resolution.get("canonical_key", retained_key),
        "matched": bool(resolution.get("matched")),
        "can_autofill": bool(resolution.get("can_autofill")),
        "policy_id": (resolution.get("policy") or {}).get("id"),
        "ready": False,
        "reason": resolution.get("reason"),
        "blocker_codes": list(resolution.get("blocker_codes") or []),
    }

    if not resolution.get("matched") or not resolution.get("can_autofill"):
        return result

    raw_options = details.get("available_options") or []
    options = _option_records(raw_options)
    if control_type in _OPTION_CONTROL_TYPES and not options:
        result.update({
            "reason": "The retained review does not contain enough option evidence to verify this answer safely.",
            "blocker_codes": ["retained_options_missing"],
        })
        return result

    if options:
        match = match_answer_candidates_to_options(
            resolution.get("answer_candidates") or [],
            options,
            allow_multiple=control_type == "checkbox_group",
        )
        if not match.ok:
            result.update({
                "reason": "The approved answer does not map unambiguously to the retained employer options.",
                "blocker_codes": ["retained_option_mismatch"],
                "missing_answers": list(match.missing_answers),
                "ambiguous_answers": dict(match.ambiguous_answers),
            })
            return result
        result["matched_options"] = [
            {"label": item.label, "value": item.value}
            for item in match.matched
        ]

    result.update({"ready": True, "reason": None, "blocker_codes": []})
    return result


def revalidate_answer_policy_manual_review(
    db: Session,
    application: Application,
    review: ManualReviewTask,
    *,
    user_id: int,
) -> Dict[str, Any]:
    """Revalidate a retained answer-policy review without touching the browser.

    This is intentionally a bookkeeping-only operation. It never fills a live form,
    creates submission authority, queues a worker, or clicks Submit. A review is
    retired only when every retained question now resolves to a current approved
    policy and every retained option set still accepts that answer unambiguously.
    """

    if review.reason_code not in POLICY_REVIEW_REASONS:
        raise ManualReviewPolicyRevalidationError(
            "This manual review is not an answer-policy review and cannot be revalidated here."
        )

    if review.status == ManualReviewStatus.resolved.value:
        return {
            "review_id": review.id,
            "ready": True,
            "resolved": True,
            "already_resolved": True,
            "total_questions": len(_retained_questions(review)),
            "satisfied_questions": len(_retained_questions(review)),
            "remaining": [],
            "application_state": normalize_state(application.automation_state),
        }

    questions = _retained_questions(review)
    if not questions:
        return {
            "review_id": review.id,
            "ready": False,
            "resolved": False,
            "already_resolved": False,
            "total_questions": 0,
            "satisfied_questions": 0,
            "remaining": [{
                "descriptor": "",
                "canonical_key": "custom.unclassified",
                "reason": "No retained questions were found for safe policy revalidation.",
                "blocker_codes": ["retained_questions_missing"],
            }],
            "application_state": normalize_state(application.automation_state),
        }

    job = application.job
    target_url = (
        application.application_target_url
        or review.blocking_url
        or (job.url if job else "")
        or ""
    )
    company = (job.company if job else "") or ""
    policies = load_runtime_policies(
        db,
        user_id,
        target_url=target_url,
        company=company,
    )

    results = [_question_result(question, policies) for question in questions]
    remaining = [item for item in results if not item.get("ready")]
    satisfied = len(results) - len(remaining)

    if remaining:
        return {
            "review_id": review.id,
            "ready": False,
            "resolved": False,
            "already_resolved": False,
            "total_questions": len(results),
            "satisfied_questions": satisfied,
            "remaining": remaining,
            "application_state": normalize_state(application.automation_state),
        }

    resolve_manual_review_task(
        db,
        application,
        review,
        "Retained employer questions revalidated against current approved Answer Policy Vault entries.",
    )

    other_open = (
        db.query(ManualReviewTask.id)
        .filter(
            ManualReviewTask.application_id == application.id,
            ManualReviewTask.id != review.id,
            ManualReviewTask.status.in_([
                ManualReviewStatus.open.value,
                ManualReviewStatus.in_progress.value,
            ]),
        )
        .first()
    )
    if other_open and normalize_state(application.automation_state) == ApplicationAutomationState.ready_to_apply.value:
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.needs_review,
            "manual_review_remaining_after_policy_revalidation",
            {"resolved_review_id": review.id, "remaining_review_id": other_open[0]},
        )

    return {
        "review_id": review.id,
        "ready": True,
        "resolved": True,
        "already_resolved": False,
        "total_questions": len(results),
        "satisfied_questions": len(results),
        "remaining": [],
        "application_state": normalize_state(application.automation_state),
    }
