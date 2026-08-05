from __future__ import annotations

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.job import Job
from app.models.material import ApplicationMaterial, EvidenceUnit
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services.evidence_ledger import evidence_hash
from app.services import lever_phase_b_reviewed_materials as reviewed_materials


REVIEW_ID = "D8-026"
POSTING_ID = "7d4a0f39-7771-4d19-b328-e8705cac1623"
APPLICATION_URL = f"https://jobs.lever.co/cin7/{POSTING_ID}/apply"


def _official_posting(*, title="Customer Success Manager", apply_url=APPLICATION_URL):
    return {
        "id": POSTING_ID,
        "text": title,
        "categories": {
            "commitment": "Full-Time",
            "location": "Toronto, CAN",
            "team": "Customer Success",
            "allLocations": ["Toronto, CAN"],
        },
        "description": (
            "<p>Support customers, lead onboarding, and improve retention.</p>"
        ),
        "descriptionPlain": (
            "Support customers, lead onboarding, improve retention, and partner "
            "with product and sales teams."
        ),
        "hostedUrl": f"https://jobs.lever.co/cin7/{POSTING_ID}",
        "applyUrl": apply_url,
        "lists": [
            {
                "text": "What you bring",
                "content": (
                    "<ul><li>Customer success experience</li>"
                    "<li>Clear communication and onboarding skills</li></ul>"
                ),
            }
        ],
    }


def _user(db_session):
    return db_session.query(User).filter(User.email == "test@example.com").one()


def _set_owner_sources(db_session, user, tmp_path):
    resume = tmp_path / "owner-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nsource-backed owner resume\n")
    user.resume_path = str(resume)
    user.resume_filename = resume.name
    user.full_name = "Test Applicant"
    user.profile_data = {
        "current_role": "Customer Success Specialist",
        "years_experience": "5",
        "employment_history": (
            "Example SaaS | Customer Success Specialist | Led onboarding and "
            "customer retention programs"
        ),
        "key_achievements": (
            "Improved customer onboarding completion and maintained account notes"
        ),
        "languages": "English; French",
    }
    user.job_preferences = {
        "skills": [
            "Customer Success",
            "Customer Onboarding",
            "Account Management",
            "Communication",
        ]
    }
    db_session.commit()
    return resume


def _patch_resume_evidence(monkeypatch):
    original = reviewed_materials.rebuild_user_evidence

    def rebuild_with_resume_statement(db, user):
        result = original(db, user)
        statement = (
            "Led customer onboarding, account management, and retention programs "
            "for a software company."
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
                role="Customer Success Specialist",
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
        result["total_active"] = db.query(EvidenceUnit).filter(
            EvidenceUnit.user_id == user.id,
            EvidenceUnit.is_active.is_(True),
        ).count()
        result["sources"] = {
            **(result.get("sources") or {}),
            "resume_pdf": 1,
        }
        return result

    monkeypatch.setattr(
        reviewed_materials,
        "rebuild_user_evidence",
        rebuild_with_resume_statement,
    )


def _prepare(auth_client):
    response = auth_client.post(
        f"/api/supervised-pilot/lever-launch/{REVIEW_ID}/prepare-materials"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _candidate(auth_client):
    response = auth_client.get("/api/supervised-pilot/lever-launch")
    assert response.status_code == 200, response.text
    return next(
        candidate
        for candidate in response.json()["candidates"]
        if candidate["review_id"] == REVIEW_ID
    )


def test_prepare_requires_a_readable_owner_resume_without_side_effects(
    auth_client,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(
        reviewed_materials,
        "_fetch_official_posting",
        lambda _candidate: (_ for _ in ()).throw(
            AssertionError("posting metadata must not be fetched without a résumé")
        ),
    )

    response = auth_client.post(
        f"/api/supervised-pilot/lever-launch/{REVIEW_ID}/prepare-materials"
    )

    assert response.status_code == 409
    assert "Upload the owner résumé" in response.json()["detail"]
    assert db_session.query(Application).count() == 0
    assert db_session.query(ApplicationMaterial).count() == 0
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0
    assert db_session.query(SubmissionEvidence).count() == 0


def test_prepare_materializes_refreshes_posting_and_requires_review(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    user = _user(db_session)
    _set_owner_sources(db_session, user, tmp_path)
    _patch_resume_evidence(monkeypatch)
    monkeypatch.setattr(
        reviewed_materials,
        "_fetch_official_posting",
        lambda _candidate: _official_posting(),
    )

    result = _prepare(auth_client)

    assert result["review_id"] == REVIEW_ID
    assert result["posting_source"] == "lever_official_postings_api"
    assert len(result["posting_sha256"]) == 64
    assert result["resume_evidence_count"] == 1
    assert result["review_eligible"] is True
    assert result["critical_errors"] == []
    assert {item["material_type"] for item in result["materials"]} == {
        "cover_letter",
        "resume_summary",
    }
    assert all(item["review_status"] == "pending" for item in result["materials"])
    assert result["automation_state"] == ApplicationAutomationState.needs_review.value
    assert result["approval_issued"] is False
    assert result["submission_queued"] is False

    application = db_session.query(Application).filter(
        Application.id == result["application_id"]
    ).one()
    job = db_session.query(Job).filter(Job.id == result["job_id"]).one()
    materials = db_session.query(ApplicationMaterial).filter(
        ApplicationMaterial.application_id == application.id
    ).all()
    review = db_session.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == application.id,
        ManualReviewTask.status == ManualReviewStatus.open.value,
    ).one()

    assert "Support customers" in job.description
    assert (job.raw_data or {})["lever_official_posting_sha256"] == result[
        "posting_sha256"
    ]
    assert application.resume_path == user.resume_path
    assert len(materials) == 2
    assert all(
        (material.source_snapshot or {})["user_review"]["status"] == "pending"
        for material in materials
    )
    assert review.details["stage"] == reviewed_materials.REVIEW_STAGE
    assert review.details["review_eligible"] is True
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0
    assert db_session.query(SubmissionEvidence).count() == 0

    candidate = _candidate(auth_client)
    assert candidate["official_posting_context_present"] is True
    assert candidate["official_posting_sha256"] == result["posting_sha256"]
    assert candidate["material_review_eligible"] is True
    assert candidate["cover_letter_review_status"] == "pending"
    assert candidate["resume_summary_review_status"] == "pending"
    assert candidate["preparation_stage"] == "review_required"


def test_explicit_material_approval_reaches_fresh_preflight_boundary(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    user = _user(db_session)
    _set_owner_sources(db_session, user, tmp_path)
    _patch_resume_evidence(monkeypatch)
    monkeypatch.setattr(
        reviewed_materials,
        "_fetch_official_posting",
        lambda _candidate: _official_posting(),
    )
    prepared = _prepare(auth_client)

    response = auth_client.post(
        f"/api/supervised-pilot/lever-launch/{REVIEW_ID}/review-materials",
        json={
            "approved": True,
            "notes": "Reviewed both source-backed materials against my résumé.",
        },
    )

    assert response.status_code == 200, response.text
    reviewed = response.json()
    assert reviewed["approved"] is True
    assert reviewed["material_review_status"] == "approved"
    assert reviewed["ready_for_fresh_preflight"] is True
    assert reviewed["automation_state"] == ApplicationAutomationState.ready_to_apply.value
    assert reviewed["open_review_count"] == 0
    assert reviewed["approval_issued"] is False
    assert reviewed["submission_queued"] is False

    application = db_session.query(Application).filter(
        Application.id == prepared["application_id"]
    ).one()
    materials = db_session.query(ApplicationMaterial).filter(
        ApplicationMaterial.application_id == application.id
    ).all()
    assert application.cover_letter
    assert application.resume_path == user.resume_path
    assert len(materials) == 2
    assert all(material.status == "verified" for material in materials)
    assert all(
        (material.source_snapshot or {})["user_review"]["status"] == "approved"
        for material in materials
    )
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0
    assert db_session.query(SubmissionEvidence).count() == 0

    candidate = _candidate(auth_client)
    assert candidate["preparation_stage"] == "fresh_preflight_required"
    assert candidate["preparation_blockers"] == []
    assert candidate["cover_letter_review_status"] == "approved"
    assert candidate["resume_summary_review_status"] == "approved"
    assert candidate["application_cover_letter_matches_latest"] is True


def test_stale_evidence_blocks_material_approval(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    user = _user(db_session)
    _set_owner_sources(db_session, user, tmp_path)
    _patch_resume_evidence(monkeypatch)
    monkeypatch.setattr(
        reviewed_materials,
        "_fetch_official_posting",
        lambda _candidate: _official_posting(),
    )
    prepared = _prepare(auth_client)

    statement = "New evidence added after material generation."
    db_session.add(
        EvidenceUnit(
            user_id=user.id,
            kind="achievement",
            label="New evidence",
            statement=statement,
            source_type="manual",
            source_ref="manual:after-preparation",
            source_hash=evidence_hash(statement, kind="achievement"),
            verification_status="user_confirmed",
            confidence=1.0,
            provenance={"created_by_user": True},
            is_active=True,
        )
    )
    db_session.commit()

    response = auth_client.post(
        f"/api/supervised-pilot/lever-launch/{REVIEW_ID}/review-materials",
        json={"approved": True},
    )

    assert response.status_code == 409
    assert "stale evidence" in response.json()["detail"]
    application = db_session.query(Application).filter(
        Application.id == prepared["application_id"]
    ).one()
    assert application.automation_state == ApplicationAutomationState.needs_review.value
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0
    assert db_session.query(SubmissionEvidence).count() == 0


def test_official_posting_identity_drift_rolls_back_before_materialization(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    user = _user(db_session)
    _set_owner_sources(db_session, user, tmp_path)
    monkeypatch.setattr(
        reviewed_materials,
        "_fetch_official_posting",
        lambda _candidate: _official_posting(title="Different Role"),
    )

    response = auth_client.post(
        f"/api/supervised-pilot/lever-launch/{REVIEW_ID}/prepare-materials"
    )

    assert response.status_code == 409
    assert "role drifted" in response.json()["detail"]
    assert db_session.query(Application).count() == 0
    assert db_session.query(ApplicationMaterial).count() == 0
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0


def test_retained_material_preparation_requires_authentication(client):
    prepare = client.post(
        f"/api/supervised-pilot/lever-launch/{REVIEW_ID}/prepare-materials"
    )
    review = client.post(
        f"/api/supervised-pilot/lever-launch/{REVIEW_ID}/review-materials",
        json={"approved": True},
    )

    assert prepare.status_code == 401
    assert review.status_code == 401
