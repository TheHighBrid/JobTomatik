from __future__ import annotations

from app.models.application import Application, ApplicationAutomationState
from app.models.job import Job
from app.models.material import ApplicationMaterial, EvidenceUnit
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services import lever_phase_b_current_intake as intake_service
from app.services import lever_phase_b_current_materials_v4 as current_materials
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
        "verified_at": "2026-08-29T18:00:00",
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
            "Technical Support Specialists support customers with technical issues, "
            "troubleshoot software and web problems, communicate clearly, document "
            "cases, and provide consistent service."
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
        label=f"v4 regression {unit_id_hint}",
        statement=statement,
        organization=organization,
        role=role,
        source_type=source_type,
        source_ref=f"v4:{unit_id_hint}",
        source_hash=evidence_hash(statement, kind=kind),
        verification_status="source_backed",
        confidence=0.9,
        provenance={"v4_regression": True},
        is_active=True,
    )
    db_session.add(unit)
    db_session.flush()
    return unit


def test_current_lever_v4_prepare_filters_heading_and_irrelevant_banking_roles(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    resume = tmp_path / "v4-owner-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nv4 source-backed owner resume\n")
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
            "source_reference": "test-current-fullscript-v4",
        },
    )
    assert response.status_code == 201, response.text
    application_id = response.json()["application_id"]

    _add_unit(
        db_session,
        user,
        statement="Credit Officer",
        unit_id_hint="credit-role",
        kind="role",
        source_type="profile",
    )
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
        statement=(
            "Customer Care Officer (Bilingual) | TD Canada Trust Bank, Ottawa, ON | "
            "November 2018 - April 2022"
        ),
        unit_id_hint="customer-care",
        organization="TD Canada Trust Bank",
        role="Customer Care Officer (Bilingual)",
    )
    _add_unit(
        db_session,
        user,
        statement=(
            "Supported clients with digital-banking concerns through multiple "
            "communication channels."
        ),
        unit_id_hint="supported-clients",
    )
    _add_unit(
        db_session,
        user,
        statement="EDUCATION & TECHNICAL SKILLS",
        unit_id_hint="section-heading",
    )
    for skill in ("Risk Management", "TSYS", "Bilingual", "Microsoft Office", "Linux", "De-escalation"):
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
            "sources": {"profile": 7, "resume_pdf": 4},
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
    assert {item["generator_version"] for item in prepared["materials"]} == {
        "verified-material-v4"
    }

    materials = (
        db_session.query(ApplicationMaterial)
        .filter(ApplicationMaterial.application_id == application_id)
        .order_by(ApplicationMaterial.material_type)
        .all()
    )
    assert len(materials) == 2
    assert all(material.status == "verified" for material in materials)
    assert all(material.generator_version == "verified-material-v4" for material in materials)

    combined = "\n".join(material.content for material in materials)
    assert "Credit Officer" not in combined
    assert "Fraud Officer" not in combined
    assert "Monitored account for any suspicious activity" not in combined
    assert "EDUCATION & TECHNICAL SKILLS" not in combined
    assert "Customer Care Officer" in combined
    assert "Supported clients with digital-banking concerns" in combined
    assert "TSYS" not in combined
    assert "Risk Management" not in combined
    assert "Bilingual" in combined
    assert "Microsoft Office" in combined

    application = db_session.query(Application).filter(Application.id == application_id).one()
    assert application.automation_state == ApplicationAutomationState.needs_review.value
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0
