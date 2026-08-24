from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewTask,
)
from app.models.job import Job, JobStatus
from app.models.material import ApplicationMaterial
from app.models.user import User
from app.tasks import applications as application_tasks


def _user(db_session):
    return db_session.query(User).filter(User.email == "test@example.com").one()


def _attach_resume(user: User, tmp_path, name: str = "resume.pdf"):
    path = tmp_path / name
    path.write_bytes(b"day31 canonical resume fixture\n")
    user.resume_path = str(path)
    user.resume_filename = name
    return path


def _application(db_session, user: User, suffix: str) -> Application:
    job = Job(
        external_id=f"verified-task-{suffix}",
        title="Fraud Investigator",
        company="Example Bank",
        location="Ottawa, ON",
        description="Investigate suspicious transaction activity and document findings.",
        requirements="Fraud investigation, AML, case documentation.",
        url=f"https://boards.greenhouse.io/example/jobs/{suffix}",
        status=JobStatus.approved,
        skills=["Fraud Investigation", "AML", "Case Documentation"],
        relevance_score=0.9,
    )
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.preparing.value,
        source_listing_url=job.url,
        submission_idempotency_key=f"verified-task:{user.id}:{suffix}",
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def test_cover_letter_task_persists_verified_material_and_advances_state(
    auth_client,
    db_session,
    tmp_path,
):
    user = _user(db_session)
    _attach_resume(user, tmp_path)
    user.full_name = "Test Applicant"
    user.profile_data = {
        "current_role": "Fraud Analyst",
        "years_experience": "4",
        "employment_history": "RBC | Fraud Operations | Reviewed suspicious transactions",
        "key_achievements": "Maintained audit-ready investigation notes",
    }
    user.job_preferences = {"skills": ["AML", "Fraud Investigation"]}
    application = _application(db_session, user, "verified")

    result = application_tasks.generate_cover_letter_task.run(application.id)

    assert result["generated"] is True
    assert result["material_status"] == "verified"
    assert result["requires_manual_review"] is False
    assert len(result["content_sha256"]) == 64
    assert len(result["resume_sha256"]) == 64
    assert result["blockers"] == []

    db_session.expire_all()
    stored = db_session.query(Application).filter(Application.id == application.id).one()
    material = (
        db_session.query(ApplicationMaterial)
        .filter(
            ApplicationMaterial.application_id == application.id,
            ApplicationMaterial.material_type == "cover_letter",
        )
        .one()
    )
    assert stored.automation_state == ApplicationAutomationState.ready_to_apply.value
    assert stored.cover_letter == material.content
    assert material.claims
    assert material.evidence_links
    verification = material.source_snapshot["day31_material_verification"]
    assert verification["content_sha256"] == result["content_sha256"]
    assert verification["resume"]["sha256"] == result["resume_sha256"]
    assert "path" not in verification["resume"]


def test_cover_letter_task_routes_unsupported_profile_to_manual_review(
    auth_client,
    db_session,
    tmp_path,
):
    user = _user(db_session)
    _attach_resume(user, tmp_path)
    user.full_name = None
    user.profile_data = {}
    user.job_preferences = {}
    application = _application(db_session, user, "review")

    result = application_tasks.generate_cover_letter_task.run(application.id)

    assert result["generated"] is True
    assert result["material_status"] == "needs_review"
    assert result["requires_manual_review"] is True
    assert "substantive_applicant_evidence_missing" in result["blockers"]

    db_session.expire_all()
    stored = db_session.query(Application).filter(Application.id == application.id).one()
    review = (
        db_session.query(ManualReviewTask)
        .filter(ManualReviewTask.application_id == application.id)
        .one()
    )
    assert stored.automation_state == ApplicationAutomationState.needs_review.value
    assert review.reason_code == ManualReviewReason.validation_error.value
    assert review.details["stage"] == "day31_autonomous_material_verification"
    assert "substantive_applicant_evidence_missing" in review.details["blockers"]
    assert db_session.query(ApplicationMaterial).filter(
        ApplicationMaterial.application_id == application.id
    ).count() == 1
