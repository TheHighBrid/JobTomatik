"""JT5 execution decision contract tests.

The decision layer is intentionally pure; concurrency safety is separately
enforced by a transactional unique attempt reservation.
"""
import pytest

from app.services.application_execution_gate import (
    ApplyDecision,
    decide_application_execution,
)


@pytest.mark.parametrize(
    ("user", "owner", "state", "active", "expected"),
    [
        (None, 1, "ready_to_apply", False, ApplyDecision.AUTH_REQUIRED),
        (2, 1, "ready_to_apply", False, ApplyDecision.FORBIDDEN),
        (1, 1, "confirmed", False, ApplyDecision.ALREADY_CONFIRMED),
        (1, 1, "submitted", False, ApplyDecision.ALREADY_CONFIRMED),
        (1, 1, "applied", False, ApplyDecision.ALREADY_CONFIRMED),
        (1, 1, "submission_uncertain", False, ApplyDecision.RECONCILE),
        (1, 1, "submitted_unconfirmed", False, ApplyDecision.RECONCILE),
        (1, 1, "ready_to_apply", True, ApplyDecision.IN_PROGRESS),
        (1, 1, "applying", False, ApplyDecision.IN_PROGRESS),
        (1, 1, "submitting", False, ApplyDecision.IN_PROGRESS),
        (1, 1, "ready_to_apply", False, ApplyDecision.EXECUTE),
    ],
)
def test_execution_decision(user, owner, state, active, expected):
    result = decide_application_execution(
        authenticated_user_id=user,
        application_owner_id=owner,
        application_state=state,
        has_active_attempt=active,
    )
    assert result.decision == expected


def test_owner_check_precedes_submission_state_disclosure():
    result = decide_application_execution(
        authenticated_user_id=999,
        application_owner_id=1,
        application_state="confirmed",
        has_active_attempt=False,
    )
    assert result.decision == ApplyDecision.FORBIDDEN
