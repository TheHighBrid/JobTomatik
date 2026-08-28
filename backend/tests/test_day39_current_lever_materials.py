from __future__ import annotations

from app.models.application import Application, ApplicationAutomationState
from app.models.job import Job
from app.models.material import ApplicationMaterial, EvidenceUnit
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services import lever_phase_b_current_intake as intake_service
from app.services import lever_phase_b_current_materials as current_materials
from app.services.evidence_ledger import evidence_hash


POSTING_ID = "a52e4915-8239-4581-8828-84661f070424"
HOSTED_URL = f"https://jobs.lever.co/fullscript/{POSTING_ID}"
APPLY_URL = f"{HOSTED_URL}/apply"


def _user(db_session):
    return db_session.query(User).filter(User.email == "test@example.com").one()


def _set_owner_sources(db_session, user, tmp_path):
    resume = tmp_path / "owner-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nsource-backed owner resume\n")
    user.resume_path = str(resume)
    user.resume_filename = resume.name
    user.full_name = "Test Applicant"
    user.profile_data = {
        "current_role": "Technical Support Specialist",
        "years_experience": "5",
        "employment_history": (
            "Example SaaS | Technical Support Specialist | Investigated API and "
            "web issues, documented escalations, and supported customers"
        ),
        "key_achievements": (
            "Resolved technical issues and maintained clear escalation notes"
        ),
        "languages": "English; French",
    }
    user.job_preferences = {
        "skills": ["Technical Support", "APIs", "Troubleshooting", "Communication"]
    }
    db_session.commit()


def _patch_resume_evidence(monkeypatch):
    original = current_materials.rebuild_user_evidence

    def rebuild_with_resume_statement(db, user):
        result = original(db, user)
        statement = (
            "Investigated API and web issues, documented escalations, and supported customers."
        )
        digest = evidence_hash(statement, kind="employment")
        unit = (
            db.query(EvidenceUnit)
            .filter(
                EvidenceUnit.user_id == user.id,
                EvidenceUnit.source_type == "resume_pdf",
                EvidenceUnit.source_ref == "resume:test-owner:line:1",
                EvidenceUnit.source_hash == digest,
            )
            .first()
        )
        if unit is None:
            unit = EvidenceUnit(
                user_id=user.id,
                kind="employment",
                label="Résumé experience",
                statement=statement,
                organization="Example SaaS",
                role="Technical Support Specialist",
                source_type="resume_pdf",
                source_ref="resume:test-owner:line:1",
                source_hash=digest,
                verification_status="source_backed",
                confidence=0.9,
                provenance={
                    "document": "owner-resume.pdf",
                    "line_number": 1,
                    "verbatim": True,
                },
                is_active=True,
            )
            db.add(unit)
        else:
            unit.is_active = True
        db.flush()
        result = dict(result)
        result["total_active"] = (
            db.query(EvidenceUnit)
            .filter(EvidenceUnit.user_id == user.id, EvidenceUnit.is_active.is_(True))
            .count()
        )
        return result

    monkeypatch.setattr(current_materials, "rebuild_user_evidence", rebuild_with_resume_statement)


def _verified_target():
    return {
        "platform": "lever",
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "verified": True,
        "blockers": [],
        "target_url": APPLY_URL,
        "canonical_application_url": APPLY_URL,
        "site": "fullscript",
        "posting_id": POSTING_ID,
        "region": "global",
        "official_title": "Technical Support Specialist",
        "title_matches_local_job": True,
        "posting_metadata_hash": "a" * 64,
        "identity_hash": "b" * 64,
        "verification_error": None,
        "verified_at": "2026-08-28T21:00:00",
    }


def _official_posting():
    return {
        "id": POSTING_ID,
        "text": "Technical Support Specialist",
        "categories": {},
        "description": (
            "Technical Support Specialists validate and reproduce customer-reported "
            "technical issues and support API and web investigations."
        ),
        "descriptionPlain": (
            "Technical Support Specialists validate and reproduce customer-reported "
            "technical issues, document escalation details, partner with Engineering, "
            "and support API and web investigations. Required skills include technical "
            "support, communication, troubleshooting, and attention to detail."
        ),
        "hostedUrl": HOSTED_URL,
        "applyUrl": APPLY_URL,
        "lists": [],
        "_metadata_source": "lever_exact_hosted_page",
    }


def _create_current_application(auth_client, monkeypatch):
    async def verified(_job):
        return _verified_target()

    monkeypatch.setattr(intake_service, "resolve_supervised_target_metadata", verified)
    response = auth_client.post(
        "/api/supervised-pilot/lever-candidates",
        json={
            "employer": "Fullscript",
            "role": "Technical Support Specialist",
            "application_url": HOSTED_URL,
            "location": "Ottawa, ON",
            "notes": "Preparation only",
            "source_reference": "test-current-fullscript",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["application_id"]


def test_current_lever_prepare_and_review_preserve_execution_boundary(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    user = _user(db_session)
    _set_owner_sources(db_session, user, tmp_path)
    _patch_resume_evidence(monkeypatch)
    application_id = _create_current_application(auth_client, monkeypatch)
    monkeypatch.setattr(
        current_materials,
        "_fetch_current_hosted_posting",
        lambda _candidate: _official_posting(),
    )

    prepared = current_materials.prepare_current_lever_materials(
        db_session,
        user,
        application_id=application_id,
    )
    db_session.commit()

    assert prepared["application_id"] == application_id
    assert prepared["posting_source"] == "lever_exact_hosted_page"
    assert prepared["review_eligible"] is True
    assert prepared["critical_errors"] == []
    assert prepared["automation_state"] == ApplicationAutomationState.needs_review.value
    assert prepared["approval_issued"] is False
    assert prepared["submission_queued"] is False
    assert prepared["runtime_flags_changed"] is False
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0

    job = (
        db_session.query(Job)
        .join(Application, Application.job_id == Job.id)
        .filter(Application.id == application_id)
        .one()
    )
    assert "Technical Support Specialists" in job.description
    materials = (
        db_session.query(ApplicationMaterial)
        .filter(ApplicationMaterial.application_id == application_id)
        .all()
    )
    assert {material.material_type for material in materials} == {
        "cover_letter",
        "resume_summary",
    }

    shown = current_materials.show_current_lever_materials(
        db_session,
        user,
        application_id=application_id,
    )
    assert shown["read_only"] is True
    assert shown["materials"]["cover_letter"]["content"]
    assert shown["materials"]["resume_summary"]["content"]

    reviewed = current_materials.review_current_lever_materials(
        db_session,
        user,
        application_id=application_id,
        approved=True,
        notes="Reviewed against my résumé and the exact Fullscript posting.",
    )
    db_session.commit()

    assert reviewed["approved"] is True
    assert reviewed["ready_for_fresh_preflight"] is True
    assert reviewed["automation_state"] == ApplicationAutomationState.ready_to_apply.value
    assert reviewed["open_review_count"] == 0
    assert reviewed["approval_issued"] is False
    assert reviewed["submission_queued"] is False
    assert reviewed["runtime_flags_changed"] is False
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0

    application = db_session.query(Application).filter(Application.id == application_id).one()
    assert application.cover_letter
    assert application.resume_path == user.resume_path
    assert all(material.status == "verified" for material in materials)
    assert all(
        (material.source_snapshot or {})["user_review"]["status"] == "approved"
        for material in materials
    )


def test_current_lever_materials_reject_non_current_application(
    db_session,
):
    user = _user(db_session)
    job = Job(title="Other", company="Other", url="https://example.com/job")
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        automation_state=ApplicationAutomationState.preparing.value,
    )
    db_session.add(application)
    db_session.commit()

    try:
        current_materials.show_current_lever_materials(
            db_session,
            user,
            application_id=application.id,
        )
    except Exception as exc:
        assert "not a current owner-selected Lever Phase B target" in str(exc)
    else:
        raise AssertionError("Non-current application unexpectedly crossed current Lever boundary")


def test_current_lever_review_rejects_stale_evidence(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    user = _user(db_session)
    _set_owner_sources(db_session, user, tmp_path)
    _patch_resume_evidence(monkeypatch)
    application_id = _create_current_application(auth_client, monkeypatch)
    monkeypatch.setattr(
        current_materials,
        "_fetch_current_hosted_posting",
        lambda _candidate: _official_posting(),
    )
    current_materials.prepare_current_lever_materials(
        db_session,
        user,
        application_id=application_id,
    )
    db_session.commit()

    statement = "New owner evidence added after material generation."
    db_session.add(
        EvidenceUnit(
            user_id=user.id,
            kind="achievement",
            label="New evidence",
            statement=statement,
            source_type="manual",
            source_ref="manual:after-current-preparation",
            source_hash=evidence_hash(statement, kind="achievement"),
            verification_status="user_confirmed",
            confidence=1.0,
            provenance={"created_by_user": True},
            is_active=True,
        )
    )
    db_session.commit()

    try:
        current_materials.review_current_lever_materials(
            db_session,
            user,
            application_id=application_id,
            approved=True,
        )
    except Exception as exc:
        assert "stale evidence" in str(exc)
    else:
        raise AssertionError("Stale evidence unexpectedly passed current Lever material review")

    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0
