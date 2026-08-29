from __future__ import annotations

from app.models.application import Application, ApplicationAutomationState
from app.models.material import ApplicationMaterial, EvidenceUnit
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services import lever_phase_b_current_intake as intake_service
from app.services import lever_phase_b_current_materials_v5 as current_materials
from app.services.evidence_ledger import evidence_hash


POSTING_ID = "a52e4915-8239-4581-8828-84661f070424"
HOSTED_URL = f"https://jobs.lever.co/fullscript/{POSTING_ID}"
APPLY_URL = f"{HOSTED_URL}/apply"


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
        "verified_at": "2026-08-29T21:00:00",
    }


def _official_posting():
    return {
        "id": POSTING_ID,
        "text": "Technical Support Specialist",
        "categories": {},
        "description": (
            "Validate, reproduce, document, and coordinate customer-reported technical issues. "
            "Partner with Engineering and investigate APIs, integrations, and web behavior."
        ),
        "descriptionPlain": (
            "Technical Support Specialists validate and reproduce technical issues, document "
            "findings, troubleshoot software and web problems, and communicate clearly."
        ),
        "hostedUrl": HOSTED_URL,
        "applyUrl": APPLY_URL,
        "lists": [],
        "_metadata_source": "lever_exact_hosted_page",
    }


def _add_unit(
    db_session,
    user,
    *,
    statement: str,
    unit_id_hint: str,
    kind: str = "employment",
    source_type: str = "resume_pdf",
    organization: str | None = None,
    role: str | None = None,
):
    unit = EvidenceUnit(
        user_id=user.id,
        kind=kind,
        label=f"v5 regression {unit_id_hint}",
        statement=statement,
        organization=organization,
        role=role,
        source_type=source_type,
        source_ref=f"v5:{unit_id_hint}",
        source_hash=evidence_hash(statement, kind=kind),
        verification_status="source_backed",
        confidence=0.9,
        provenance={"v5_regression": True},
        is_active=True,
    )
    db_session.add(unit)
    db_session.flush()
    return unit


def test_current_lever_v5_prepare_renders_support_story_and_keeps_submission_locked(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    resume = tmp_path / "v5-owner-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nv5 source-backed owner resume\n")
    user.resume_path = str(resume)
    user.resume_filename = resume.name
    user.full_name = "Mohamed Alem"
    db_session.commit()

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
            "source_reference": "test-current-fullscript-v5",
        },
    )
    assert response.status_code == 201, response.text
    application_id = response.json()["application_id"]

    _add_unit(db_session, user, statement="Credit Officer", unit_id_hint="credit-role", kind="role", source_type="profile")
    _add_unit(
        db_session,
        user,
        statement="Monitored account for any suspicious activity",
        unit_id_hint="fraud",
        organization="Royal Bank of Canada",
        role="Fraud Officer",
    )
    _add_unit(
        db_session,
        user,
        statement="Supported clients with fraud, account-security, and digital-banking concerns through multiple communication channels.",
        unit_id_hint="supported-clients",
    )
    _add_unit(
        db_session,
        user,
        statement="Educated clients on fraud prevention, account protection, online banking safety, and appropriate security actions.",
        unit_id_hint="education-clients",
    )
    _add_unit(
        db_session,
        user,
        statement="Customer Care Officer (Bilingual) | TD Canada Trust Bank, Ottawa, ON | November 2018 - April 2022",
        unit_id_hint="customer-care",
    )
    _add_unit(db_session, user, statement="EDUCATION & TECHNICAL SKILLS", unit_id_hint="section-heading")
    for skill in (
        "Bilingual",
        "Microsoft Office",
        "Linux",
        "Debian",
        "AI Tools",
        "Data Analysis",
        "Time Management",
        "Risk Management",
        "TSYS",
    ):
        _add_unit(
            db_session,
            user,
            statement=skill,
            unit_id_hint=f"skill-{skill.casefold().replace(' ', '-')}",
            kind="skill",
            source_type="profile",
        )
    db_session.commit()

    monkeypatch.setattr(
        current_materials,
        "rebuild_user_evidence",
        lambda _db, _user: {
            "created": 0,
            "deactivated": 0,
            "reused": 0,
            "total_active": db_session.query(EvidenceUnit)
            .filter(EvidenceUnit.user_id == user.id, EvidenceUnit.is_active.is_(True))
            .count(),
            "sources": {"profile": 10, "resume_pdf": 5},
            "warnings": [],
        },
    )
    monkeypatch.setattr(current_materials, "_fetch_current_hosted_posting", lambda _candidate: _official_posting())

    prepared = current_materials.prepare_current_lever_materials(
        db_session,
        user,
        application_id=application_id,
    )
    db_session.commit()

    assert prepared["review_eligible"] is True
    assert prepared["critical_errors"] == []
    assert prepared["approval_issued"] is False
    assert prepared["submission_queued"] is False
    assert prepared["runtime_flags_changed"] is False
    assert {item["generator_version"] for item in prepared["materials"]} == {"verified-material-v5"}

    materials = (
        db_session.query(ApplicationMaterial)
        .filter(ApplicationMaterial.application_id == application_id)
        .order_by(ApplicationMaterial.material_type)
        .all()
    )
    assert len(materials) == 2
    assert all(material.status == "verified" for material in materials)
    assert all(material.generator_version == "verified-material-v5" for material in materials)

    cover = next(material.content for material in materials if material.material_type == "cover_letter")
    summary = next(material.content for material in materials if material.material_type == "resume_summary")
    combined = cover + "\n" + summary

    assert "bilingual customer care experience" in cover
    assert "Supported clients across multiple communication channels." in cover
    assert "technical skills in Linux, Debian, AI Tools, Data Analysis, Microsoft Office" in cover
    assert "technical skills in Bilingual" not in combined
    assert "Credit Officer" not in combined
    assert "Fraud Officer" not in combined
    assert "Monitored account" not in combined
    assert "EDUCATION & TECHNICAL SKILLS" not in combined
    assert "TSYS" not in combined
    assert "Risk Management" not in combined
    assert "Time Management" not in combined

    experience = summary.split("RELEVANT EXPERIENCE\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert experience[0].startswith("• Customer Care Officer (Bilingual) | TD Canada Trust Bank")
    assert experience[1] == "• Supported clients across multiple communication channels"

    application = db_session.query(Application).filter(Application.id == application_id).one()
    assert application.automation_state == ApplicationAutomationState.needs_review.value
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0
