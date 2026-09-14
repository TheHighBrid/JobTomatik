from __future__ import annotations

from typing import Any, Mapping

from app.models.application import ManualReviewTask


_PERSISTED_RESULT_KEY = "last_policy_revalidation"


def _human_question_label(item: Mapping[str, Any]) -> str:
    descriptor = str(item.get("descriptor") or "").strip()
    if descriptor:
        parts = [part.strip() for part in descriptor.split("|") if part.strip()]
        if len(parts) >= 3:
            return parts[-1]
        return descriptor
    return str(item.get("canonical_key") or "unclassified question").strip()


def persist_answer_policy_revalidation_visibility(
    review: ManualReviewTask,
    result: Mapping[str, Any],
) -> None:
    """Persist the latest safe recheck result so refresh cannot hide the blocker.

    The revalidation endpoint historically returned question-level diagnostics only
    in its transient HTTP response. Application-detail refreshes could remount the
    panel immediately afterward, leaving the operator with a generic review card and
    no way to see which retained employer question was still blocked.

    Persisting the already-sanitized revalidation result in the manual-review JSON
    and promoting the unresolved prompt/reason into ``summary`` keeps the existing UI
    useful without opening the employer form or creating submission authority.
    """

    payload = dict(result or {})
    details = dict(review.details or {})
    details[_PERSISTED_RESULT_KEY] = payload
    review.details = details

    remaining = [item for item in payload.get("remaining") or [] if isinstance(item, Mapping)]
    if not remaining:
        return

    visible = []
    for item in remaining[:3]:
        label = _human_question_label(item)
        reason = str(item.get("reason") or "A valid approved answer is still required.").strip()
        visible.append(f"{label}: {reason}" if label else reason)

    suffix = " | ".join(visible)
    review.summary = (
        f"{len(remaining)} application question(s) still require an approved answer policy. "
        f"{suffix}"
    ).strip()


__all__ = ["persist_answer_policy_revalidation_visibility"]
