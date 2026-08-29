from types import SimpleNamespace

from app.models.application import Application, ApplicationAutomationState, ApplicationStatus
from app.models.job import Job, JobSource, JobStatus
from app.models.material import ApplicationMaterial, ApplicationMaterialEvidence
from app.models.user import User
from app.services.material_generation import (
    _clean_material_statement,
    _cover_letter_content,
    _resume_summary_content,
    _usable_narrative_unit,
    generate_application_material,
    validate_claims,
)


def _user(db_session):
    return db_session.query(User).filter(User.email == "test@example.com").one()


def _job(db_session, suffix: str = "1") -> Job:
    job = Job(
        external_id=f"material-job-{suffix}",
        title="Bilingual Fraud Investigator",
        company="Example Bank",
        location="Ottawa, ON",
        salary_min=78000,
        salary_max=90000,
        salary_currency="CAD",
        description="Investigate fraud alerts, review suspicious transactions, and document cases.",
        requirements="Banking, AML, bilingual English and French, case documentation.",
        url=f"https://boards.greenhouse.io/example/jobs/{suffix}",
        source=JobSource.greenhouse,
        status=JobStatus.approved,
        skills=["Fraud Investigation", "AML", "Case Documentation"],
        relevance_score=0.9,
        raw_data={"official_public_ats": True},
    )
    db_session.add(job)
    db_session.flush()
    return job


def _application(db_session, user: User, job: Job) -> Application:
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.preparing.value,
        source_listing_url=job.url,
        submission_idempotency_key=f"material-test:{user.id}:{job.id}",
    )
    db_session.add(application)
    db_session.flush()
    return application


def _complete_profile(user: User):
    user.full_name = "Test Applicant"
    user.profile_data = {
        "current_role": "Fraud Analyst",
        "years_experience": "4",
        "employment_history": (
            "RBC | Fraud Operations | Reviewed suspicious transaction alerts\n"
            "TD Bank | Customer Service | Supported clients with sensitive account issues"
        ),
        "key_achievements": "Maintained clear audit-ready case documentation",
        "languages": "English; French",
    }
    user.job_preferences = {
        "skills": ["AML", "Fraud Investigation", "Case Documentation"],
        "preferred_locations": ["Ottawa"],
    }


def _unit(
    statement: str,
    unit_id: int = 1,
    *,
    kind: str = "employment",
    organization: str | None = None,
    role: str | None = None,
    confidence: float = 0.85,
):
    return SimpleNamespace(
        id=unit_id,
        kind=kind,
        label="Resume evidence",
        statement=statement,
        organization=organization,
        role=role,
        source_hash=f"hash-{unit_id}",
        verification_status="source_backed",
        confidence=confidence,
    )


def _narrative_unit(statement: str, unit_id: int = 1):
    return _unit(statement, unit_id)


def _simple_job():
    return SimpleNamespace(
        title="Technical Support Specialist",
        company="Example Co",
        location="Ottawa, ON",
        description="Investigate fraud issues, troubleshoot systems, and document cases.",
        requirements="Fraud investigation, troubleshooting, and case documentation.",
        skills=["Fraud Investigation", "Troubleshooting"],
    )


def test_verified_cover_letter_maps_every_applicant_claim_to_evidence(auth_client, db_session):
    user = _user(db_session)
    _complete_profile(user)
    job = _job(db_session)
    application = _application(db_session, user, job)
    db_session.commit()

    material = generate_application_material(
        db_session,
        application,
        user,
        job,
        material_type="cover_letter",
    )
    db_session.commit()

    assert material.status == "verified"
    assert material.version == 1
    assert "RBC" in material.content
    assert "TD Bank" in material.content
    assert "Tangerine" not in material.content
    assert application.cover_letter == material.content
    assert material.warnings == []
    applicant_claims = [
        claim for claim in material.claims if claim.get("applicant_fact", True)
    ]
    assert applicant_claims
    assert all(claim["evidence_unit_ids"] for claim in applicant_claims)
    assert all(claim["evidence_hashes"] for claim in applicant_claims)
    assert db_session.query(ApplicationMaterialEvidence).filter(
        ApplicationMaterialEvidence.material_id == material.id
    ).count() >= 1


def test_material_generation_versions_instead_of_overwriting(auth_client, db_session):
    user = _user(db_session)
    _complete_profile(user)
    job = _job(db_session, "2")
    application = _application(db_session, user, job)
    db_session.commit()

    first = generate_application_material(db_session, application, user, job)
    db_session.commit()
    second = generate_application_material(db_session, application, user, job)
    db_session.commit()

    assert first.version == 1
    assert second.version == 2
    assert second.supersedes_material_id == first.id
    assert db_session.query(ApplicationMaterial).filter(
        ApplicationMaterial.application_id == application.id,
        ApplicationMaterial.material_type == "cover_letter",
    ).count() == 2


def test_insufficient_evidence_creates_review_material_without_invented_facts(auth_client, db_session):
    user = _user(db_session)
    user.full_name = None
    user.profile_data = {}
    user.job_preferences = {}
    job = _job(db_session, "3")
    application = _application(db_session, user, job)
    db_session.commit()

    material = generate_application_material(db_session, application, user, job)
    db_session.commit()

    assert material.status == "needs_review"
    assert any(
        warning.startswith("No substantive applicant claim")
        for warning in material.warnings
    )
    assert "TD Bank" not in material.content
    assert "Mohamed Alem" not in material.content
    assert "several years" not in material.content
    applicant_claims = [
        claim for claim in material.claims if claim.get("applicant_fact", True)
    ]
    assert all(claim["evidence_unit_ids"] for claim in applicant_claims)


def test_material_api_generates_cover_letter_and_resume_summary(auth_client, db_session):
    user = _user(db_session)
    _complete_profile(user)
    job = _job(db_session, "4")
    application = _application(db_session, user, job)
    db_session.commit()

    response = auth_client.post(
        f"/api/materials/applications/{application.id}/generate-bundle"
    )
    assert response.status_code == 200
    payload = response.json()
    assert {item["material_type"] for item in payload["materials"]} == {
        "cover_letter",
        "resume_summary",
    }

    listed = auth_client.get(f"/api/materials/applications/{application.id}")
    assert listed.status_code == 200
    materials = listed.json()
    assert len(materials) == 2
    assert all(item["evidence_links"] for item in materials)
    assert all(item["claims"] for item in materials)


def test_real_pdf_fragments_are_not_usable_narrative_evidence():
    fragments = [
        "\uf0b7 Resolved client issues using authentication procedures, analytical troubleshooting, clear bilingual communication, and strong",
        "\uf0b7 Review account situations, document client interactions in internal systems, and maintain accurate notes for auditability,",
        "\uf0b7 Verified client information, assessed risk indicators, and resolved fraud/security issues at first point of contact when",
    ]

    assert all(
        _usable_narrative_unit(_narrative_unit(statement)) is False
        for statement in fragments
    )


def test_complete_pdf_bullet_is_cleaned_without_discarding_its_evidence():
    statement = (
        "\uf0b7 Investigated API and web issues, documented escalations, "
        "and supported customers."
    )
    unit = _narrative_unit(statement)

    assert _usable_narrative_unit(unit) is True
    assert _clean_material_statement(statement) == (
        "Investigated API and web issues, documented escalations, and supported customers."
    )


def test_validator_blocks_pre_fix_material_with_pdf_glyph_and_fragment():
    unit = _narrative_unit(
        "\uf0b7 Resolved client issues using authentication procedures, analytical troubleshooting, clear bilingual communication, and strong"
    )
    claim = {
        "text": (
            "My employment record includes: \uf0b7 Resolved client issues using "
            "authentication procedures, analytical troubleshooting, clear bilingual "
            "communication, and strong."
        ),
        "category": "employment",
        "applicant_fact": True,
        "evidence_unit_ids": [unit.id],
        "evidence_hashes": [unit.source_hash],
    }

    errors = validate_claims([claim], [unit])

    assert any("unsafe PDF bullet glyph" in error for error in errors)
    assert any("likely incomplete narrative" in error for error in errors)


def test_complete_short_narrative_evidence_is_preserved():
    for statement in ("Won MVP award.", "Built JobTomatik."):
        assert _usable_narrative_unit(_narrative_unit(statement)) is True


def test_cleaner_preserves_signed_metrics_and_nix_terms():
    assert _clean_material_statement("-10% error rate") == "-10% error rate"
    assert _clean_material_statement("*nix administration") == "*nix administration"
    assert _clean_material_statement("- Reduced error rate") == "Reduced error rate"


def test_cover_letter_only_claims_structured_roles_that_are_rendered():
    units = [
        _unit("First complete role record.", 1, organization="Bank A", role="Analyst A"),
        _unit("Second complete role record.", 2, organization="Bank B", role="Analyst B"),
        _unit("Third complete role record.", 3, organization="Bank C", role="Analyst C"),
    ]

    content, claims, _ = _cover_letter_content(
        SimpleNamespace(full_name=None),
        _simple_job(),
        units,
    )

    employment_claims = [claim for claim in claims if claim["category"] == "employment"]
    assert [claim["evidence_unit_ids"] for claim in employment_claims] == [[1], [2]]
    assert "Analyst A" in content
    assert "Analyst B" in content
    assert "Analyst C" not in content
    assert all(3 not in claim["evidence_unit_ids"] for claim in claims)


def test_employment_alignment_is_applicant_fact_and_only_uses_supporting_units():
    relevant = _unit("Investigated fraud alerts and documented cases.", 1, confidence=0.5)
    unrelated = _unit("Supported retail customers with account questions.", 2)

    _, claims, _ = _cover_letter_content(
        SimpleNamespace(full_name=None),
        _simple_job(),
        [relevant, unrelated],
    )

    alignment_claims = [claim for claim in claims if claim["category"] == "job_alignment"]
    assert alignment_claims
    assert all(claim["applicant_fact"] is True for claim in alignment_claims)
    assert any(claim["evidence_unit_ids"] == [1] for claim in alignment_claims)
    assert all(2 not in claim["evidence_unit_ids"] for claim in alignment_claims)


def test_resume_summary_attaches_employment_only_when_rendered_alignment_uses_it():
    role = _unit("Credit Officer", 1, kind="role")
    relevant = _unit("Investigated fraud alerts and documented cases.", 2)
    unrelated = _unit("Supported retail customers with account questions.", 3)

    _, claims, _ = _resume_summary_content(
        SimpleNamespace(full_name=None),
        _simple_job(),
        [role, relevant, unrelated],
    )

    summary_claim = next(claim for claim in claims if claim["category"] == "career_summary")
    assert 1 in summary_claim["evidence_unit_ids"]
    assert 2 in summary_claim["evidence_unit_ids"]
    assert 3 not in summary_claim["evidence_unit_ids"]
