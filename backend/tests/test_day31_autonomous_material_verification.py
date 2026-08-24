from datetime import datetime

from app.models.application import Application, ApplicationAutomationState, ApplicationStatus
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.answer_policy import resolve_runtime_policy
from app.services.autonomous_material_verification import (
    generate_autonomy_verified_material,
    inspect_resume_selection,
    verify_material_integrity,
)


def _user(db_session):
    return db_session.query(User).filter(User.email == "test@example.com").one()


def _resume(user: User, tmp_path, name: str = "resume.pdf", content: bytes = b"resume-v1"):
    path = tmp_path / name
    path.write_bytes(content)
    user.resume_path = str(path)
    user.resume_filename = name
    return path


def _profile(user: User):
    user.full_name = "Test Applicant"
    user.profile_data = {
        "current_role": "Fraud Analyst",
        "years_experience": "4",
        "employment_history": "Example Bank | Fraud Analyst | Reviewed suspicious transactions",
        "key_achievements": "Maintained audit-ready case documentation",
        "languages": "English; French",
    }
    user.job_preferences = {
        "skills": ["Fraud Investigation", "AML", "Case Documentation"],
    }


def _job(db_session, suffix: str) -> Job:
    job = Job(
        external_id=f"day31-{suffix}",
        title="Bilingual Fraud Investigator",
        company="Example Bank",
        location="Ottawa, ON",
        description="Investigate fraud alerts and document suspicious activity.",
        requirements="Fraud investigation, AML, bilingual English and French.",
        url=f"https://boards.greenhouse.io/example/jobs/{suffix}",
        source=JobSource.greenhouse,
        status=JobStatus.approved,
        skills=["Fraud Investigation", "AML", "Case Documentation"],
        relevance_score=0.9,
    )
    db_session.add(job)
    db_session.flush()
    return job


def _application(db_session, user: User, job: Job, *, resume_path: str | None = None) -> Application:
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.preparing.value,
        source_listing_url=job.url,
        resume_path=resume_path,
        submission_idempotency_key=f"day31:{user.id}:{job.id}",
    )
    db_session.add(application)
    db_session.flush()
    return application


def test_missing_applicant_fact_stays_in_manual_review(db_session, tmp_path):
    user = _user(db_session)
    _resume(user, tmp_path)
    user.full_name = None
    user.profile_data = {}
    user.job_preferences = {}
    job = _job(db_session, "missing-fact")
    application = _application(db_session, user, job)

    material, verification = generate_autonomy_verified_material(
        db_session,
        application,
        user,
        job,
    )

    assert material.status == "needs_review"
    assert verification["requires_manual_review"] is True
    assert "substantive_applicant_evidence_missing" in verification["blockers"]
    assert "several years" not in material.content
    assert all(
        claim.get("evidence_unit_ids")
        for claim in material.claims
        if claim.get("applicant_fact", True)
    )


def test_conflicting_resume_selection_fails_closed(db_session, tmp_path):
    user = _user(db_session)
    canonical = _resume(user, tmp_path, "canonical.pdf", b"canonical")
    _profile(user)
    conflicting = tmp_path / "conflicting.pdf"
    conflicting.write_bytes(b"different resume")
    job = _job(db_session, "resume-conflict")
    application = _application(db_session, user, job, resume_path=str(conflicting))

    material, verification = generate_autonomy_verified_material(
        db_session,
        application,
        user,
        job,
    )

    assert canonical.is_file()
    assert material.status == "needs_review"
    assert "conflicting_resume_selection" in verification["blockers"]
    assert application.resume_path == str(conflicting)


def test_stale_resume_digest_invalidates_prepared_material(db_session, tmp_path):
    user = _user(db_session)
    resume = _resume(user, tmp_path, content=b"resume-v1")
    _profile(user)
    job = _job(db_session, "stale-resume")
    application = _application(db_session, user, job)

    material, verification = generate_autonomy_verified_material(
        db_session,
        application,
        user,
        job,
    )
    assert verification["requires_manual_review"] is False
    original_digest = verification["resume"]["sha256"]

    resume.write_bytes(b"resume-v2 changed after material generation")
    recheck = verify_material_integrity(db_session, material, application, user)

    assert recheck["valid"] is False
    assert recheck["resume"]["sha256"] != original_digest
    assert "resume_document_changed" in recheck["blockers"]


def test_unsupported_claim_or_content_mutation_is_detected(db_session, tmp_path):
    user = _user(db_session)
    _resume(user, tmp_path)
    _profile(user)
    job = _job(db_session, "unsupported-claim")
    application = _application(db_session, user, job)

    material, verification = generate_autonomy_verified_material(
        db_session,
        application,
        user,
        job,
    )
    assert verification["requires_manual_review"] is False

    material.claims = list(material.claims or []) + [
        {
            "text": "I hold an unsupported professional credential.",
            "category": "credential",
            "applicant_fact": True,
            "evidence_unit_ids": [],
            "evidence_hashes": [],
        }
    ]
    material.content += "\nI hold an unsupported professional credential.\n"
    recheck = verify_material_integrity(db_session, material, application, user)

    assert recheck["valid"] is False
    assert "material_content_changed" in recheck["blockers"]
    assert "material_claims_changed" in recheck["blockers"]
    assert "material_evidence_drift" in recheck["blockers"]


def test_low_confidence_custom_answer_cannot_autofill():
    policy = {
        "id": 31,
        "canonical_key": "custom.motivation",
        "category": "custom",
        "sensitivity": "standard",
        "mode": "answer",
        "answer_value": "I am interested in the role.",
        "answer_label": "I am interested in the role.",
        "fallback_answers": [],
        "match_phrases": ["why are you interested"],
        "scope": "global",
        "scope_value": "",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": datetime(2026, 8, 24, 12, 0, 0),
        "provenance": "user_provided",
        "confidence": 0.50,
        "consent_metadata": {"autofill_authorized": True},
        "is_expired": False,
        "encryption_valid": True,
        "updated_at": datetime(2026, 8, 24, 12, 0, 0),
    }

    resolved = resolve_runtime_policy(
        "Why are you interested in this position?",
        [policy],
    )

    assert resolved["matched"] is True
    assert resolved["can_autofill"] is False
    assert "policy_confidence_low" in resolved["blocker_codes"]


def test_material_hashes_are_deterministic_for_same_sources(db_session, tmp_path):
    user = _user(db_session)
    _resume(user, tmp_path)
    _profile(user)
    job = _job(db_session, "deterministic")
    application = _application(db_session, user, job)

    first, first_verification = generate_autonomy_verified_material(
        db_session,
        application,
        user,
        job,
    )
    second, second_verification = generate_autonomy_verified_material(
        db_session,
        application,
        user,
        job,
    )

    assert first.content == second.content
    assert first_verification["content_sha256"] == second_verification["content_sha256"]
    assert first_verification["claims_sha256"] == second_verification["claims_sha256"]
    assert first_verification["resume"]["sha256"] == second_verification["resume"]["sha256"]


def test_resume_selection_uses_canonical_resume_when_application_has_none(db_session, tmp_path):
    user = _user(db_session)
    canonical = _resume(user, tmp_path)
    job = _job(db_session, "selection")
    application = _application(db_session, user, job)

    selection = inspect_resume_selection(application, user)

    assert selection["status"] == "verified"
    assert selection["path"] == str(canonical.resolve())
    assert len(selection["sha256"]) == 64
