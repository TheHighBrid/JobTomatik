from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
)
from app.models.intelligence import AgentRun, AgentTask
from app.models.job import Job, JobSource, JobStatus
from app.models.material import ApplicationMaterial
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services.submission_handoff import (
    create_submission_handoff,
    evaluate_submission_handoff,
    review_submission_handoff,
)


def _build_ready_run(db_session, user, tmp_path, *, suffix="one"):
    resume_path = tmp_path / f"resume-{suffix}.pdf"
    resume_path.write_bytes(b"%PDF-1.4\nsource-backed test resume\n%%EOF")
    user.resume_path = str(resume_path)
    user.phone = "+1 613 555 0100"
    user.profile_data = {"summary": "Fraud investigation specialist"}

    job = Job(
        external_id=f"phase5-{suffix}",
        title="Fraud Analyst",
        company="Example Bank",
        location="Ottawa, Ontario",
        url=f"https://boards.greenhouse.io/example/jobs/{suffix}",
        source=JobSource.greenhouse,
        status=JobStatus.approved,
        skills=["fraud", "investigation"],
        raw_data={"official_public_ats": True},
    )
    db_session.add(job)
    db_session.flush()

    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        source_listing_url=job.url,
        application_target_url=job.url,
        application_target_status="resolved",
        submission_idempotency_key=f"phase5-{user.id}-{suffix}",
        cover_letter="Verified cover letter content",
    )
    db_session.add(application)
    db_session.flush()

    materials = {}
    for material_type, content in (
        ("cover_letter", application.cover_letter),
        ("resume_summary", "Verified resume summary content"),
    ):
        material = ApplicationMaterial(
            user_id=user.id,
            application_id=application.id,
            material_type=material_type,
            version=1,
            status="verified",
            content=content,
            claims=[],
            warnings=[],
            source_snapshot={"source": "phase5-test"},
            generator_version="verified-material-v1",
        )
        db_session.add(material)
        db_session.flush()
        materials[material_type] = material

    plan = [
        {
            "id": "prepare_application",
            "name": "Prepare application",
            "agent_type": "application",
            "dependencies": [],
            "input": {"application_id": application.id},
        }
    ]
    run = AgentRun(
        user_id=user.id,
        objective="Prepare exact application handoff",
        status="completed",
        autonomy_level="reviewed",
        risk_level="high",
        requires_approval=True,
        plan=plan,
        run_context={
            "application_id": application.id,
            "execution_control": {
                "approval_state": "approved",
                "scope": "bounded_local_execution",
                "paused": False,
                "cancellation_requested": False,
                "submission_authorized": False,
                "outreach_authorized": False,
            },
        },
    )
    db_session.add(run)
    db_session.flush()
    task = AgentTask(
        run_id=run.id,
        sequence=0,
        name="Prepare application",
        agent_type="application",
        status="completed",
        dependencies=[],
        task_input={"application_id": application.id, "plan_task_id": "prepare_application"},
        task_output={
            "application_id": application.id,
            "materials": {
                material_type: {
                    "id": material.id,
                    "version": material.version,
                    "status": material.status,
                }
                for material_type, material in materials.items()
            },
            "blockers": [],
            "ready_for_separate_submission_preflight": True,
            "submission_attempted": False,
            "submission_authorized": False,
        },
        attempt_count=1,
        max_attempts=3,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(run)
    _ = run.tasks
    return run, application


def test_handoff_creation_and_review_never_authorize_or_queue(db_session, tmp_path):
    user = User(
        email="phase5-owner@example.com",
        hashed_password="not-used",
        full_name="Phase Five Owner",
    )
    db_session.add(user)
    db_session.flush()
    run, application = _build_ready_run(db_session, user, tmp_path)

    before = evaluate_submission_handoff(db_session, run)
    assert before["eligible"] is True
    assert before["status"] == "not_created"

    created = create_submission_handoff(db_session, run, user_id=user.id)
    db_session.commit()
    assert created["status"] == "created"
    assert created["submission_authorized"] is False
    assert created["approval_issued"] is False
    assert created["queue_attempted"] is False
    assert created["stored_snapshot"]["combined_payload_hash"]
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0

    reviewed = review_submission_handoff(
        db_session,
        run,
        user_id=user.id,
        note="Reviewed locally before opening supervised preflight.",
    )
    db_session.commit()
    assert reviewed["status"] == "reviewed"
    assert reviewed["stored_snapshot"]["reviewed_by_user_id"] == user.id
    assert reviewed["submission_authorized"] is False
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0

    event_types = {
        event.event_type
        for event in db_session.query(ApplicationEvent)
        .filter(ApplicationEvent.application_id == application.id)
        .all()
    }
    assert "bounded_submission_handoff_created" in event_types
    assert "bounded_submission_handoff_reviewed" in event_types


def test_handoff_detects_exact_payload_drift(db_session, tmp_path):
    user = User(
        email="phase5-drift@example.com",
        hashed_password="not-used",
        full_name="Drift Owner",
    )
    db_session.add(user)
    db_session.flush()
    run, application = _build_ready_run(db_session, user, tmp_path, suffix="drift")
    create_submission_handoff(db_session, run, user_id=user.id)
    db_session.commit()

    application.cover_letter = "Mutated after handoff creation"
    db_session.commit()
    drifted = evaluate_submission_handoff(db_session, run)

    assert drifted["status"] == "drifted"
    assert drifted["drifted"] is True
    assert "changed:cover_letter_hash" in drifted["drift_reasons"]
    assert "changed:combined_payload_hash" in drifted["drift_reasons"]
    assert drifted["submission_authorized"] is False


def test_handoff_api_is_exact_phrase_and_account_scoped(
    auth_client,
    db_session,
    tmp_path,
):
    owner = db_session.query(User).filter(User.email == "test@example.com").one()
    run, _ = _build_ready_run(db_session, owner, tmp_path, suffix="api")

    preview = auth_client.get(
        f"/api/intelligence/agent-runs/{run.id}/submission-handoff"
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["eligible"] is True
    assert preview.json()["submission_authorized"] is False

    wrong = auth_client.post(
        f"/api/intelligence/agent-runs/{run.id}/submission-handoff",
        json={"acknowledgment": "CREATE IT"},
    )
    assert wrong.status_code == 422

    created = auth_client.post(
        f"/api/intelligence/agent-runs/{run.id}/submission-handoff",
        json={"acknowledgment": f"CREATE SUBMISSION HANDOFF {run.id}"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "created"
    assert created.json()["approval_issued"] is False

    reviewed = auth_client.post(
        f"/api/intelligence/agent-runs/{run.id}/submission-handoff/review",
        json={
            "acknowledgment": f"REVIEW SUBMISSION HANDOFF {run.id}",
            "note": "Reviewed without granting final-submit consent.",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "reviewed"
    assert reviewed.json()["queue_attempted"] is False

    other = User(
        email="phase5-other@example.com",
        hashed_password="not-used",
        full_name="Other User",
    )
    db_session.add(other)
    db_session.flush()
    other_run, _ = _build_ready_run(db_session, other, tmp_path, suffix="other")

    hidden = auth_client.get(
        f"/api/intelligence/agent-runs/{other_run.id}/submission-handoff"
    )
    assert hidden.status_code == 404
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0
