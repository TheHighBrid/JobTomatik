from __future__ import annotations

from app.api import supervised_pilot_roster as api_module
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt


BUNDLE = {
    "material_ids": {"cover_letter": 15, "resume_summary": 16},
    "material_versions": {"cover_letter": 2, "resume_summary": 2},
    "posting_sha256": "b" * 64,
    "evidence_digest": "a" * 64,
}


def test_current_lever_operator_roster_is_authenticated_read_only(
    auth_client,
    db_session,
    monkeypatch,
):
    observed = {}

    def roster(_db, user):
        observed["user_id"] = user.id
        return {
            "selection_policy": "user_selected_exact_application_no_ranking",
            "candidate_count": 1,
            "eligible_count": 1,
            "candidates": [
                {
                    "application_id": 247,
                    "employer": "Maple",
                    "role": "Client Success Associate (Bilingual, French/English)",
                    "automation_state": "needs_review",
                    "uncertain_submission_attempt_count": 0,
                    "material_preparation_eligible": True,
                    "eligibility_blockers": [],
                }
            ],
            "read_only": True,
            "approval_issued": False,
            "submission_queued": False,
            "runtime_flags_changed": False,
        }

    monkeypatch.setattr(api_module, "list_current_lever_phase_b_candidates", roster)
    response = auth_client.get("/api/supervised-pilot/current-lever")

    assert response.status_code == 200, response.text
    body = response.json()
    assert observed["user_id"]
    assert body["candidate_count"] == 1
    assert body["candidates"][0]["application_id"] == 247
    assert body["read_only"] is True
    assert body["approval_issued"] is False
    assert body["submission_queued"] is False
    assert body["runtime_flags_changed"] is False
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0


def test_current_lever_operator_prepare_and_show_have_no_submission_authority(
    auth_client,
    db_session,
    monkeypatch,
):
    def prepare(_db, _user, *, application_id):
        assert application_id == 247
        return {
            "application_id": application_id,
            "review_eligible": True,
            "automation_state": "needs_review",
            "approval_issued": False,
            "submission_queued": False,
            "runtime_flags_changed": False,
        }

    def show(_db, _user, *, application_id):
        assert application_id == 247
        return {
            "application_id": application_id,
            "automation_state": "needs_review",
            "posting_sha256": BUNDLE["posting_sha256"],
            "open_review_count": 1,
            "materials": {
                "cover_letter": {
                    "id": 15,
                    "status": "verified",
                    "version": 2,
                    "preparation": {"evidence_digest": BUNDLE["evidence_digest"]},
                },
                "resume_summary": {
                    "id": 16,
                    "status": "verified",
                    "version": 2,
                    "preparation": {"evidence_digest": BUNDLE["evidence_digest"]},
                },
            },
            "read_only": True,
        }

    monkeypatch.setattr(api_module, "prepare_current_lever_operator_materials", prepare)
    monkeypatch.setattr(api_module, "show_current_lever_operator_materials", show)

    prepared = auth_client.post(
        "/api/supervised-pilot/current-lever/247/prepare-materials"
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["approval_issued"] is False
    assert prepared.json()["submission_queued"] is False

    shown = auth_client.get(
        "/api/supervised-pilot/current-lever/247/materials"
    )
    assert shown.status_code == 200, shown.text
    assert shown.json()["read_only"] is True
    assert shown.json()["materials"]["cover_letter"]["version"] == 2

    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0


def test_current_lever_operator_approval_requires_exact_application_and_bundle(
    auth_client,
    db_session,
    monkeypatch,
):
    calls = []

    def review(
        _db,
        _user,
        *,
        application_id,
        approved,
        notes,
        material_ids,
        material_versions,
        posting_sha256,
        evidence_digest,
    ):
        calls.append(
            (
                application_id,
                approved,
                notes,
                material_ids,
                material_versions,
                posting_sha256,
                evidence_digest,
            )
        )
        return {
            "application_id": application_id,
            "approved": approved,
            "automation_state": "ready_to_apply" if approved else "needs_review",
            "requires_fresh_runtime_preflight": bool(approved),
            "approval_issued": False,
            "submission_queued": False,
            "runtime_flags_changed": False,
        }

    monkeypatch.setattr(api_module, "review_current_lever_operator_materials", review)

    missing_ack = auth_client.post(
        "/api/supervised-pilot/current-lever/247/review-materials",
        json={"approved": True, **BUNDLE},
    )
    assert missing_ack.status_code == 409
    assert calls == []

    wrong_ack = auth_client.post(
        "/api/supervised-pilot/current-lever/247/review-materials",
        json={
            "approved": True,
            "acknowledgment": "APPROVE LEVER MATERIALS 246",
            **BUNDLE,
        },
    )
    assert wrong_ack.status_code == 409
    assert calls == []

    accepted = auth_client.post(
        "/api/supervised-pilot/current-lever/247/review-materials",
        json={
            "approved": True,
            "acknowledgment": "APPROVE LEVER MATERIALS 247",
            "notes": "Reviewed in JobTomatik operator UI",
            **BUNDLE,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert calls == [
        (
            247,
            True,
            "Reviewed in JobTomatik operator UI",
            BUNDLE["material_ids"],
            BUNDLE["material_versions"],
            BUNDLE["posting_sha256"],
            BUNDLE["evidence_digest"],
        )
    ]
    assert accepted.json()["approval_issued"] is False
    assert accepted.json()["submission_queued"] is False
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0


def test_current_lever_operator_reject_is_also_bound_to_displayed_bundle(
    auth_client,
    monkeypatch,
):
    calls = []

    def review(
        _db,
        _user,
        *,
        application_id,
        approved,
        notes,
        material_ids,
        material_versions,
        posting_sha256,
        evidence_digest,
    ):
        calls.append(
            (
                application_id,
                approved,
                notes,
                material_ids,
                material_versions,
                posting_sha256,
                evidence_digest,
            )
        )
        return {
            "application_id": application_id,
            "approved": False,
            "automation_state": "needs_review",
            "approval_issued": False,
            "submission_queued": False,
            "runtime_flags_changed": False,
        }

    monkeypatch.setattr(api_module, "review_current_lever_operator_materials", review)
    response = auth_client.post(
        "/api/supervised-pilot/current-lever/247/review-materials",
        json={"approved": False, "notes": "Needs revision", **BUNDLE},
    )

    assert response.status_code == 200, response.text
    assert calls[0][0:3] == (247, False, "Needs revision")
    assert calls[0][3] == BUNDLE["material_ids"]
    assert calls[0][4] == BUNDLE["material_versions"]
