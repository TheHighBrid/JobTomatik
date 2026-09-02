from types import SimpleNamespace

from app.services.operator_assisted_final_action import finalize_operator_final_action


class _FakeDb:
    def __init__(self):
        self.added = []
        self.flushed = False

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flushed = True


def test_finalization_preserves_fresh_live_checkpoint_from_outer_handoff_state():
    db = _FakeDb()
    application = SimpleNamespace(id=7, automation_state="applying")
    approval = SimpleNamespace(
        reference="lvsup-final-action-test",
        approval_metadata={
            "operator_submit_action_started": True,
            "operator_submit_action_result": "pending_external_action",
            "operator_submit_live_snapshot_checkpointed": False,
            "operator_submit_pre_submit_url": None,
            "operator_submit_pre_submit_fingerprint": None,
        },
    )
    session = SimpleNamespace(
        public_id="handoff-final-action-test",
        current_url="https://jobs.lever.co/safeco/posting-123/apply",
        current_fingerprint="fresh-page-before",
        handoff_metadata={
            "operator_submit_live_snapshot_checkpointed": True,
            "operator_submit_live_snapshot_checkpointed_at": "2026-09-02T13:15:00",
            "operator_submit_pre_submit_url": "https://jobs.lever.co/safeco/posting-123/apply",
            "operator_submit_pre_submit_fingerprint": "fresh-page-before",
            "automatic_retry_allowed": False,
        },
    )

    finalize_operator_final_action(
        db,
        application,
        session,
        approval,
        result={
            "submission_confirmed": False,
            "current_url": "https://jobs.lever.co/safeco/posting-123/apply",
            "current_fingerprint": "after-action",
            "confirmation_detector": "lever_adapter_strict",
        },
    )

    metadata = approval.approval_metadata
    assert metadata["operator_submit_live_snapshot_checkpointed"] is True
    assert metadata["operator_submit_live_snapshot_checkpointed_at"] == "2026-09-02T13:15:00"
    assert metadata["operator_submit_pre_submit_url"].endswith("/posting-123/apply")
    assert metadata["operator_submit_pre_submit_fingerprint"] == "fresh-page-before"
    assert metadata["operator_submit_action_result"] == "awaiting_confirmation"
    assert metadata["automatic_retry_allowed"] is False
    assert session.handoff_metadata["operator_submit_live_snapshot_checkpointed"] is True
    assert db.flushed is True
    assert len(db.added) == 1
