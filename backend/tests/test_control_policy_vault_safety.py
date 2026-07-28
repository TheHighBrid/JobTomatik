from copy import deepcopy

import pytest

from app.services.control_policy import resolve_control_policy


def _policy(*, policy_id=1, answer="Yes"):
    return {
        "id": policy_id,
        "canonical_key": "work_authorization",
        "category": "work_authorization",
        "sensitivity": "legal",
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "fallback_answers": [],
        "match_phrases": [],
        "scope": "global",
        "scope_value": "",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-28T10:00:00Z",
        "provenance": "user_provided",
        "confidence": 1.0,
        "consent_metadata": {"autofill_authorized": True},
        "is_expired": False,
        "encryption_valid": True,
        "created_at": "2026-07-28T09:00:00Z",
        "updated_at": "2026-07-28T10:00:00Z",
    }


def _resolve(policy):
    return resolve_control_policy(
        "Are you legally authorized to work in Canada?",
        [policy],
    )


@pytest.mark.parametrize(
    ("changes", "expected_blocker"),
    [
        ({"is_expired": True}, "policy_expired"),
        ({"confidence": 0.79}, "policy_confidence_low"),
        ({"provenance": "unknown"}, "policy_provenance_unknown"),
        ({"consent_metadata": {}}, "policy_consent_missing"),
        ({"encryption_valid": False}, "policy_encryption_invalid"),
    ],
)
def test_control_policy_blocks_unsafe_vault_records(changes, expected_blocker):
    policy = _policy()
    policy.update(changes)

    result = _resolve(policy)

    assert result["matched"] is True
    assert result["can_autofill"] is False
    assert expected_blocker in result["blocker_codes"]


def test_control_policy_blocks_conflicting_same_scope_records():
    first = _policy(policy_id=1, answer="Yes")
    second = deepcopy(first)
    second.update({"id": 2, "answer_value": "No", "answer_label": "No"})

    result = resolve_control_policy(
        "Are you legally authorized to work in Canada?",
        [first, second],
    )

    assert result["matched"] is True
    assert result["can_autofill"] is False
    assert result["blocker_codes"] == ["policy_scope_conflict"]
    assert set(result["conflict_policy_ids"]) == {1, 2}
