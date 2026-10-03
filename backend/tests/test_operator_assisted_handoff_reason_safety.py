from types import SimpleNamespace

from app.models.application import ManualReviewReason
from app.services.handoff_safety_integration import (
    _operator_final_submit_reason_policy,
)
from app.services.operational_safety import classify_handoff_reason


FINAL_REASON = ManualReviewReason.operator_final_submit_required.value
IDENTITY_HASH = "b" * 64


def _review(details):
    return SimpleNamespace(reason_code=FINAL_REASON, details=details)


def _certified_review_details():
    return {
        "handoff_stage": "operator_final_submit",
        "operator_final_click_required": True,
        "submit_clicked": False,
        "automated_submission_authorized": False,
        "queue_submission_authorized": False,
        "target_identity_hash": IDENTITY_HASH,
    }


def _certified_snapshot():
    return {
        "dry_run": True,
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "operator_assisted_final_submit": True,
        "operator_final_click_required": True,
        "automated_submission_authorized": False,
        "queue_submission_authorized": False,
        "operator_target_identity_hash": IDENTITY_HASH,
        "supervised_target": {
            "platform": "lever",
            "adapter": "lever",
            "adapter_version": "1.1.0",
            "verified": True,
            "blockers": [],
            "identity_hash": IDENTITY_HASH,
        },
    }


def test_operator_final_submit_reason_is_not_globally_resumable():
    policy = classify_handoff_reason(FINAL_REASON)

    assert policy.resumable is False
    assert policy.operator_reason_code == "handoff_not_certified"


def test_bare_operator_final_submit_reason_is_rejected_by_scoped_policy():
    policy = _operator_final_submit_reason_policy(
        _review({"handoff_stage": "operator_final_submit"}),
        {},
    )

    assert policy is not None
    assert policy.resumable is False
    assert policy.operator_reason_code == "operator_final_submit_not_certified"


def test_scoped_policy_requires_all_authority_fields_to_be_explicitly_false():
    snapshot = _certified_snapshot()
    snapshot.pop("queue_submission_authorized")
    policy = _operator_final_submit_reason_policy(
        _review(_certified_review_details()),
        snapshot,
    )

    assert policy is not None
    assert policy.resumable is False


def test_scoped_policy_certifies_exact_operator_lever_snapshot_only():
    policy = _operator_final_submit_reason_policy(
        _review(_certified_review_details()),
        _certified_snapshot(),
    )

    assert policy is not None
    assert policy.resumable is True
    assert policy.disposition == "operator_final_submit"
    assert policy.operator_reason_code == "operator_final_submit_owner_boundary"


def test_scoped_policy_rejects_target_identity_drift():
    snapshot = _certified_snapshot()
    snapshot["supervised_target"]["identity_hash"] = "c" * 64
    policy = _operator_final_submit_reason_policy(
        _review(_certified_review_details()),
        snapshot,
    )

    assert policy is not None
    assert policy.resumable is False
