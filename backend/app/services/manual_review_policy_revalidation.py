from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ApplicationEvent,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
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
_STALE_REPREPARE_BLOCKERS = {
    "legacy_opaque_lever_descriptor",
    "retained_question_descriptor_missing",
}
_LEGACY_LEVER_CARD_RE = re.compile(
    r"^cards\[[^\]]+\]\[field\d+\]\s*\|\s*[^|]+$",
    flags=re.IGNORECASE,
)


class ManualReviewPolicyRevalidationError(ValueError):
    pass


def _retained_questions(review: ManualReviewTask) -> List[Dict[str, Any]]:
    details = dict(review.details or {})
    questions = details.get("questions") or []
    if not isinstance(questions, list):
        return []
    return [item for item in questions if isinstance(item, dict)]


def _legacy_opaque_lever_descriptor(descriptor: str) -> bool:
    """Identify the pre-fix Lever descriptor that retained only field name + option.

    The descriptor extraction fix now appends the human employer prompt as another
    descriptor segment. The old two-part form cannot be safely classified later,
    because the question text was never persisted in the review.
    """

    return bool(_LEGACY_LEVER_CARD_RE.fullmatch(str(descriptor or "").strip()))


def _stale_lever_question_evidence(question: Dict[str, Any]) -> bool:
    """Return True only when retained Lever question text is unrecoverably absent.

    Historical reviews exist in two fail-closed shapes: the old two-part opaque
    descriptor and records whose descriptor was never persisted at all. Neither
    shape can be reclassified safely from storage, so both require a fresh fill-only
    preparation to re-read the employer prompt.
    """

    details = dict(question.get("details") or {})
    descriptor = str(details.get("descriptor") or "").strip()
    return not descriptor or _legacy_opaque_lever_descriptor(descriptor)


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

    if _legacy_opaque_lever_descriptor(descriptor):
        return {
            "descriptor": descriptor,
            "canonical_key": retained_key,
            "ready": False,
            "reason": (
                "This review was captured before Lever human question prompts were retained. "
                "It must be retired only for a mandatory fresh fill-only preparation."
            ),
            "blocker_codes": ["legacy_opaque_lever_descriptor"],
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


def _fresh_reprepare_available(review: ManualReviewTask, results: List[Dict[str, Any]]) -> bool:
    questions = _retained_questions(review)
    return bool(
        questions
        and len(results) == len(questions)
        and all(
            set(item.get("blocker_codes") or []) <= _STALE_REPREPARE_BLOCKERS
            and bool(item.get("blocker_codes"))
            for item in results
        )
    )


def _is_lever_apply_url(value: str) -> bool:
    try:
        parsed = urlparse(value or "")
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return (
        host in {"jobs.lever.co", "jobs.eu.lever.co"}
        and parsed.path.rstrip("/").endswith("/apply")
    )


def retire_stale_answer_policy_review_for_reprepare(
    db: Session,
    application: Application,
    review: ManualReviewTask,
) -> Dict[str, Any]:
    """Retire only provably stale Lever question evidence so a fresh fill-only pass can run.

    No answer is accepted by this operation. It is limited to retained question
    records whose employer prompt is unrecoverable from storage: either the old
    opaque two-part descriptor or a missing descriptor. The next preparation must
    re-read and re-classify every employer question under the current control engine
    before any final-submit boundary can exist.
    """

    if review.reason_code not in POLICY_REVIEW_REASONS:
        raise ManualReviewPolicyRevalidationError(
            "This manual review is not an answer-policy review and cannot be retired for reprepare."
        )
    if review.status not in {ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value}:
        raise ManualReviewPolicyRevalidationError("Only an open answer-policy review can be retired for reprepare.")
    if normalize_state(application.automation_state) != ApplicationAutomationState.needs_review.value:
        raise ManualReviewPolicyRevalidationError(
            "The application must be stopped in needs_review before a stale review can be retired."
        )
    if application.status == ApplicationStatus.applied:
        raise ManualReviewPolicyRevalidationError("An applied application cannot be re-prepared.")

    questions = _retained_questions(review)
    if not questions or not all(_stale_lever_question_evidence(item) for item in questions):
        raise ManualReviewPolicyRevalidationError(
            "This review contains current or classifiable question evidence and must pass normal policy revalidation."
        )

    target_url = application.application_target_url or review.blocking_url or ""
    if not _is_lever_apply_url(target_url):
        raise ManualReviewPolicyRevalidationError(
            "Stale-review retirement is restricted to an exact Lever /apply target."
        )

    live_or_consumed_approval = (
        db.query(SubmissionApproval.id)
        .filter(
            SubmissionApproval.application_id == application.id,
            SubmissionApproval.status.in_([
                SubmissionApprovalStatus.active.value,
                SubmissionApprovalStatus.consumed.value,
            ]),
        )
        .first()
    )
    if live_or_consumed_approval:
        raise ManualReviewPolicyRevalidationError(
            "A live or consumed submission approval exists, so fresh reprepare is forbidden."
        )

    sufficient_evidence = (
        db.query(SubmissionEvidence.id)
        .filter(
            SubmissionEvidence.application_id == application.id,
            SubmissionEvidence.is_sufficient.is_(True),
        )
        .first()
    )
    if sufficient_evidence:
        raise ManualReviewPolicyRevalidationError(
            "Submission evidence exists, so fresh reprepare is forbidden."
        )

    resolve_manual_review_task(
        db,
        application,
        review,
        (
            "Stale Lever question review with unrecoverable prompt evidence retired solely to require "
            "a fresh fill-only preparation under the current descriptor extractor. No applicant answer "
            "was accepted."
        ),
    )
    db.add(ApplicationEvent(
        application_id=application.id,
        event_type="legacy_policy_review_retired_for_fresh_reprepare",
        from_state=normalize_state(application.automation_state),
        to_state=normalize_state(application.automation_state),
        payload={
            "review_id": review.id,
            "question_count": len(questions),
            "fresh_reprepare_required": True,
            "submission_authorized": False,
        },
    ))
    return {
        "review_id": review.id,
        "retired": True,
        "fresh_reprepare_required": True,
        "submission_authorized": False,
        "application_state": normalize_state(application.automation_state),
    }


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
            "fresh_reprepare_available": False,
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
            "fresh_reprepare_available": False,
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
            "fresh_reprepare_available": _fresh_reprepare_available(review, results),
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
        "fresh_reprepare_available": False,
        "application_state": normalize_state(application.automation_state),
    }
