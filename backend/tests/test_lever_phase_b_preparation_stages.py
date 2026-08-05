from datetime import datetime, timedelta

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.job import Job
from app.models.material import ApplicationMaterial
from app.models.submission_approval import (
    SubmissionApproval,
    SubmissionApprovalStatus,
)
from app.models.submission_integrity import (
    SubmissionAttempt,
    SubmissionAttemptStatus,
)
from app.models.user import User


REVIEW_ID = "D8-026"
POSTING_SHA = "9" * 64
EMPTY_EVIDENCE_SHA = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


def _candidate(auth_client):
    response = auth_client.get("/api/supervised-pilot/lever-launch")
    assert response.status_code == 200
    return next(
        item for item in response.json()["candidates"]
        if item["review_id"] == REVIEW_ID
    )


def _materialize(auth_client):
    response = auth_client.post(
        f"/api/supervised-pilot/lever-launch/{REVIEW_ID}/materialize"
    )
    assert response.status_code == 200
    return response.json()


def _records(db_session, application_id):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    application = (
        db_session.query(Application)
        .filter(Application.id == application_id)
        .one()
    )
    return user, application


def _reviewed_snapshot(*, approved=True, review_eligible=True):
    return {
        "lever_phase_b_preparation": {
            "review_id": REVIEW_ID,
            "posting_sha256": POSTING_SHA,
            "evidence_digest": EMPTY_EVIDENCE_SHA,
            "review_eligible": review_eligible,
            "critical_errors": [],
        },
        "user_review": {
            "status": "approved" if approved else "pending",
            "reviewed_at": datetime.utcnow().isoformat() if approved else None,
            "reviewed_by_user_id": 1 if approved else None,
            "notes": None,
        },
    }


def _add_material(
    db_session,
    user,
    application,
    *,
    material_type,
    version=1,
    status="verified",
    source_snapshot=None,
):
    material = ApplicationMaterial(
        user_id=user.id,
        application_id=application.id,
        material_type=material_type,
        version=version,
        status=status,
        content=f"{material_type} v{version}",
        claims=[],
        warnings=[] if status == "verified" else ["Review required"],
        source_snapshot=source_snapshot or {},
        generator_version="verified-material-v1",
    )
    db_session.add(material)
    return material


def _add_active_approval(db_session, user, application):
    approval = SubmissionApproval(
        application_id=application.id,
        user_id=user.id,
        platform="lever",
        status=SubmissionApprovalStatus.active.value,
        employer="Cin7",
        role="Customer Success Manager",
        application_url=(
            "https://jobs.lever.co/cin7/"
            "7d4a0f39-7771-4d19-b328-e8705cac1623/apply"
        ),
        submission_idempotency_key=application.submission_idempotency_key,
        profile_snapshot_hash="1" * 64,
        resume_hash="2" * 64,
        cover_letter_hash="3" * 64,
        answer_payload_hash="4" * 64,
        combined_payload_hash="5" * 64,
        approved_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=20),
        approval_metadata={"approval_source": "test"},
    )
    db_session.add(approval)
    db_session.flush()
    return approval


def _prepare_verified_materials(db_session, user, application, tmp_path):
    resume = tmp_path / "owner-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nOwner resume\n")
    user.resume_path = str(resume)
    application.cover_letter = "cover_letter v1"
    application.automation_state = ApplicationAutomationState.ready_to_apply.value
    job = db_session.query(Job).filter(Job.id == application.job_id).one()
    job.description = "Verified official Lever posting description."
    job.raw_data = {
        **(job.raw_data or {}),
        "lever_official_posting_sha256": POSTING_SHA,
    }
    _add_material(
        db_session,
        user,
        application,
        material_type="cover_letter",
        source_snapshot=_reviewed_snapshot(),
    )
    _add_material(
        db_session,
        user,
        application,
        material_type="resume_summary",
        source_snapshot=_reviewed_snapshot(),
    )


def test_launch_status_starts_at_not_materialized_without_side_effects(
    auth_client,
    db_session,
):
    candidate = _candidate(auth_client)
    assert candidate["preparation_stage"] == "not_materialized"
    assert candidate["preparation_blockers"] == ["materialize_preparation_record"]
    assert candidate["preparation_next_action"] == "materialize"
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0


def test_materialized_candidate_reports_exact_missing_materials(
    auth_client,
    db_session,
):
    result = _materialize(auth_client)
    candidate = _candidate(auth_client)
    assert candidate["materialized_application_id"] == result["application_id"]
    assert candidate["preparation_stage"] == "verified_materials_required"
    assert candidate["preparation_blockers"] == [
        "resume_required",
        "official_posting_context_required",
        "verified_cover_letter_required",
        "application_cover_letter_required",
        "verified_resume_summary_required",
        "application_not_ready_to_apply",
    ]
    assert candidate["official_posting_context_present"] is False
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0


def test_reviewed_latest_materials_reach_fresh_preflight_boundary(
    auth_client,
    db_session,
    tmp_path,
):
    result = _materialize(auth_client)
    user, application = _records(db_session, result["application_id"])
    _prepare_verified_materials(db_session, user, application, tmp_path)
    db_session.commit()

    candidate = _candidate(auth_client)
    assert candidate["preparation_stage"] == "fresh_preflight_required"
    assert candidate["preparation_blockers"] == []
    assert candidate["resume_present"] is True
    assert candidate["official_posting_sha256"] == POSTING_SHA
    assert candidate["application_cover_letter_matches_latest"] is True
    assert candidate["cover_letter_review_status"] == "approved"
    assert candidate["resume_summary_review_status"] == "approved"


def test_unreadable_resume_path_cannot_reach_fresh_preflight(
    auth_client,
    db_session,
    tmp_path,
):
    result = _materialize(auth_client)
    user, application = _records(db_session, result["application_id"])
    _prepare_verified_materials(db_session, user, application, tmp_path)
    user.resume_path = str(tmp_path / "missing-resume.pdf")
    db_session.commit()
    candidate = _candidate(auth_client)
    assert candidate["preparation_stage"] == "verified_materials_required"
    assert candidate["resume_present"] is False
    assert "resume_required" in candidate["preparation_blockers"]


def test_stale_attached_cover_letter_cannot_reach_fresh_preflight(
    auth_client,
    db_session,
    tmp_path,
):
    result = _materialize(auth_client)
    user, application = _records(db_session, result["application_id"])
    _prepare_verified_materials(db_session, user, application, tmp_path)
    application.cover_letter = "Older or manually changed cover letter."
    db_session.commit()
    candidate = _candidate(auth_client)
    assert candidate["preparation_stage"] == "verified_materials_required"
    assert candidate["application_cover_letter_matches_latest"] is False
    assert "application_cover_letter_out_of_sync" in candidate["preparation_blockers"]


def test_latest_needs_review_material_blocks_preflight(
    auth_client,
    db_session,
    tmp_path,
):
    result = _materialize(auth_client)
    user, application = _records(db_session, result["application_id"])
    resume = tmp_path / "owner-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nOwner resume\n")
    user.resume_path = str(resume)
    application.cover_letter = "cover_letter v1"
    application.automation_state = ApplicationAutomationState.ready_to_apply.value
    job = db_session.query(Job).filter(Job.id == application.job_id).one()
    job.description = "Verified official Lever posting description."
    job.raw_data = {**(job.raw_data or {}), "lever_official_posting_sha256": POSTING_SHA}
    _add_material(
        db_session,
        user,
        application,
        material_type="cover_letter",
        version=1,
        status="verified",
        source_snapshot=_reviewed_snapshot(),
    )
    _add_material(
        db_session,
        user,
        application,
        material_type="cover_letter",
        version=2,
        status="needs_review",
        source_snapshot=_reviewed_snapshot(approved=False),
    )
    _add_material(
        db_session,
        user,
        application,
        material_type="resume_summary",
        status="verified",
        source_snapshot=_reviewed_snapshot(),
    )
    db_session.commit()
    candidate = _candidate(auth_client)
    assert candidate["preparation_stage"] == "review_required"
    assert candidate["cover_letter_material_version"] == 2
    assert "cover_letter_review_required" in candidate["preparation_blockers"]


def test_open_review_task_blocks_even_with_verified_materials(
    auth_client,
    db_session,
    tmp_path,
):
    result = _materialize(auth_client)
    user, application = _records(db_session, result["application_id"])
    _prepare_verified_materials(db_session, user, application, tmp_path)
    db_session.add(
        ManualReviewTask(
            application_id=application.id,
            reason_code=ManualReviewReason.validation_error.value,
            status=ManualReviewStatus.open.value,
            summary="Review generated materials.",
            details={"stage": "verified_material_generation"},
        )
    )
    db_session.commit()
    candidate = _candidate(auth_client)
    assert candidate["preparation_stage"] == "review_required"
    assert candidate["open_review_count"] == 1
    assert "open_manual_review_tasks" in candidate["preparation_blockers"]


def test_review_blocker_takes_priority_over_active_approval(
    auth_client,
    db_session,
):
    result = _materialize(auth_client)
    user, application = _records(db_session, result["application_id"])
    approval = _add_active_approval(db_session, user, application)
    db_session.add(
        ManualReviewTask(
            application_id=application.id,
            reason_code=ManualReviewReason.validation_error.value,
            status=ManualReviewStatus.open.value,
            summary="Review required after approval was issued.",
            details={"stage": "verified_material_generation"},
        )
    )
    db_session.commit()
    candidate = _candidate(auth_client)
    assert candidate["preparation_stage"] == "review_required"
    assert candidate["active_approval_reference"] == approval.reference


def test_active_approval_is_surfaced_without_creating_or_consuming_it(
    auth_client,
    db_session,
):
    result = _materialize(auth_client)
    user, application = _records(db_session, result["application_id"])
    approval = _add_active_approval(db_session, user, application)
    db_session.commit()
    candidate = _candidate(auth_client)
    assert candidate["preparation_stage"] == "active_approval_present"
    assert candidate["active_approval_reference"] == approval.reference
    assert db_session.query(SubmissionAttempt).count() == 0


def test_submission_attempt_takes_priority_over_active_approval(
    auth_client,
    db_session,
):
    result = _materialize(auth_client)
    user, application = _records(db_session, result["application_id"])
    approval = _add_active_approval(db_session, user, application)
    attempt = SubmissionAttempt(
        application_id=application.id,
        user_id=user.id,
        approval_reference=approval.reference,
        attempt_number=1,
        task_id="day16-stage-test-task",
        status=SubmissionAttemptStatus.queued.value,
        binding_hash="6" * 64,
        identity_digest="7" * 64,
        combined_payload_hash="5" * 64,
        adapter_version="1.1.0",
        target_identity_hash="8" * 64,
        attempt_metadata={"source": "test"},
    )
    db_session.add(attempt)
    db_session.commit()
    candidate = _candidate(auth_client)
    assert candidate["preparation_stage"] == "submission_state_present"
    assert candidate["latest_attempt_reference"] == attempt.reference
    assert candidate["active_approval_reference"] == approval.reference
