"""JT5's four essential decisions, independent of approval references.

This module deliberately does not publish tasks or click an ATS submit button.
Callers must perform the authorization check and reserve an attempt in one
database transaction before publishing a worker task.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ApplyDecision(str, Enum):
    EXECUTE = "execute"
    ALREADY_CONFIRMED = "already_confirmed"
    IN_PROGRESS = "in_progress"
    RECONCILE = "reconcile"
    FORBIDDEN = "forbidden"
    AUTH_REQUIRED = "auth_required"


@dataclass(frozen=True)
class ApplyGateResult:
    decision: ApplyDecision
    reason: str


def decide_application_execution(
    *,
    authenticated_user_id: Optional[int],
    application_owner_id: int,
    application_state: str,
    has_active_attempt: bool,
) -> ApplyGateResult:
    """Evaluate only authentication, ownership, duplicate and uncertainty gates.

    This pure decision is not a substitute for an atomic database reservation.
    """
    if authenticated_user_id is None:
        return ApplyGateResult(ApplyDecision.AUTH_REQUIRED, "authentication_required")
    if authenticated_user_id != application_owner_id:
        return ApplyGateResult(ApplyDecision.FORBIDDEN, "application_not_owned")
    state = application_state.strip().lower()
    if state in {"confirmed", "submitted", "applied"}:
        return ApplyGateResult(ApplyDecision.ALREADY_CONFIRMED, "existing_submission")
    if state in {"submission_uncertain", "submitted_unconfirmed"}:
        return ApplyGateResult(ApplyDecision.RECONCILE, "prior_outcome_uncertain")
    if has_active_attempt or state in {"applying", "submitting"}:
        return ApplyGateResult(ApplyDecision.IN_PROGRESS, "attempt_in_progress")
    return ApplyGateResult(ApplyDecision.EXECUTE, "ready")
