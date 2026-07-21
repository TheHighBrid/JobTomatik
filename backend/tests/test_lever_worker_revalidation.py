from unittest.mock import MagicMock

from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.services import supervised_submission_integration
from app.tasks.applications import submit_application_task
from tests.conftest import TestingSessionLocal
from tests.test_lever_supervised_preflight import (
    _approval_payload,
    _enable_lever_pilot,
    _mock_metadata,
    _prepare_application,
    _valid_metadata,
)


def test_worker_refresh_revokes_drifted_target_before_browser_launch(
    auth_client,
    tmp_path,
    monkeypatch,
):
    _enable_lever_pilot(monkeypatch)
    app_id = _prepare_application(auth_client, tmp_path, suffix="worker-drift")
    _mock_metadata(monkeypatch, _valid_metadata(identity_hash="b" * 64))

    created = auth_client.post(
        f"/api/supervised-submissions/applications/{app_id}/approvals",
        json=_approval_payload(),
    )
    assert created.status_code == 201
    reference = created.json()["reference"]

    changed = _valid_metadata(identity_hash="c" * 64)
    changed["posting_metadata_hash"] = "d" * 64

    async def resolved(_job):
        return dict(changed)

    monkeypatch.setattr(
        supervised_submission_integration,
        "resolve_supervised_target_metadata",
        resolved,
    )
    inner_worker = MagicMock()
    monkeypatch.setattr(
        supervised_submission_integration,
        "_ORIGINAL_RUN",
        inner_worker,
    )

    result = submit_application_task.run(
        app_id,
        dry_run=False,
        approval_reference=reference,
    )

    assert result["success"] is False
    assert result["approval_required"] is True
    assert result["platform"] == "lever"
    assert "payload changed" in result["error"].lower()
    inner_worker.assert_not_called()

    db = TestingSessionLocal()
    approval = db.query(SubmissionApproval).filter(
        SubmissionApproval.reference == reference
    ).one()
    assert approval.status == SubmissionApprovalStatus.revoked.value
    assert "target_identity_hash" in approval.approval_metadata["mismatched_fields"]
    db.close()
