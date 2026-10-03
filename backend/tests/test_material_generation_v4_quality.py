from types import SimpleNamespace

from app.services import material_generation as base
from app.services.material_generation_v4 import (
    GENERATOR_VERSION,
    _curated_ranked,
    _looks_like_section_heading_text,
    _quality_warnings,
)
from app.services.material_generation_v4_policy import (
    FILTERED_ROLE_WARNING,
    _normalize_intentional_filter_warnings,
)


def _unit(
    statement: str,
    unit_id: int,
    *,
    kind: str = "employment",
    source_type: str = "resume_pdf",
    organization: str | None = None,
    role: str | None = None,
):
    return SimpleNamespace(
        id=unit_id,
        kind=kind,
        label="Fullscript v4 regression evidence",
        statement=statement,
        organization=organization,
        role=role,
        source_type=source_type,
        source_ref=f"resume:{unit_id}",
        source_hash=f"fullscript-v4-{unit_id}",
        verification_status="source_backed",
        confidence=0.9,
    )


def _job():
    return SimpleNamespace(
        id=1824,
        title="Technical Support Specialist",
        company="Fullscript",
        location="Canada",
        url="https://jobs.lever.co/fullscript/example/apply",
        updated_at=None,
        description=(
            "Support customers with technical issues, troubleshoot software and web "
            "problems, communicate clearly, document cases, and provide accurate care."
        ),
        requirements=(
            "Customer support, technical troubleshooting, communication, accurate "
            "documentation, and consistent service."
        ),
        skills=["Technical Support", "Customer Support", "Troubleshooting", "Communication"],
    )


def test_v4_rejects_resume_section_headings_as_evidence():
    assert _looks_like_section_heading_text("EDUCATION & TECHNICAL SKILLS") is True
    assert _looks_like_section_heading_text("PROFESSIONAL SUMMARY") is True
    assert _looks_like_section_heading_text(
        "Customer Care Officer (Bilingual) | TD Canada Trust Bank | November 2018 - April 2022"
    ) is False


def test_v4_curates_fullscript_materials_toward_support_evidence():
    job = _job()
    credit_role = _unit("Credit Officer", 5, kind="role", source_type="profile")
    fraud = _unit(
        "Monitored account for any suspicious activity",
        35,
        organization="Royal Bank of Canada",
        role="Fraud Officer",
    )
    customer_care = _unit(
        "Customer Care Officer (Bilingual) | TD Canada Trust Bank, Ottawa, ON | "
        "November 2018 - April 2022",
        70,
        organization="TD Canada Trust Bank",
        role="Customer Care Officer (Bilingual)",
    )
    supported_clients = _unit(
        "Supported clients with fraud, account-security, and digital-banking concerns "
        "through multiple communication channels.",
        64,
    )
    section_heading = _unit("EDUCATION & TECHNICAL SKILLS", 79)
    skills = [
        _unit("Risk Management", 10, kind="skill", source_type="profile"),
        _unit("TSYS", 11, kind="skill", source_type="profile"),
        _unit("Bilingual", 12, kind="skill", source_type="profile"),
        _unit("Microsoft Office", 13, kind="skill", source_type="profile"),
        _unit("Linux", 14, kind="skill", source_type="profile"),
        _unit("De-escalation", 15, kind="skill", source_type="profile"),
    ]

    curated = _curated_ranked(
        [credit_role, fraud, customer_care, supported_clients, section_heading, *skills],
        job,
    )
    curated_ids = {unit.id for unit in curated}

    assert credit_role.id not in curated_ids
    assert fraud.id not in curated_ids
    assert section_heading.id not in curated_ids
    assert customer_care.id in curated_ids
    assert supported_clients.id in curated_ids
    assert 10 not in curated_ids
    assert 11 not in curated_ids
    assert {12, 13, 14, 15}.issubset(curated_ids)

    user = SimpleNamespace(full_name="Mohamed Alem")
    cover, cover_claims, cover_warnings = base._cover_letter_content(user, job, curated)
    summary, summary_claims, summary_warnings = base._resume_summary_content(user, job, curated)

    assert GENERATOR_VERSION == "verified-material-v4"
    assert "Credit Officer" not in cover
    assert "Credit Officer" not in summary
    assert "Fraud Officer" not in cover
    assert "Monitored account for any suspicious activity" not in summary
    assert "EDUCATION & TECHNICAL SKILLS" not in cover
    assert "EDUCATION & TECHNICAL SKILLS" not in summary
    assert "Customer Care Officer" in cover or "Customer Care Officer" in summary
    assert supported_clients.statement in cover
    assert supported_clients.statement in summary

    unit_by_id = {unit.id: unit for unit in curated}
    assert _quality_warnings(cover, cover_claims, job, unit_by_id) == []
    assert _quality_warnings(summary, summary_claims, job, unit_by_id) == []
    assert cover_warnings == [FILTERED_ROLE_WARNING]
    assert not summary_warnings


def test_v4_intentional_role_filter_warning_is_non_blocking_with_aligned_employment():
    material = SimpleNamespace(
        warnings=[FILTERED_ROLE_WARNING],
        status="needs_review",
        claims=[
            {
                "category": "job_alignment",
                "evidence_unit_ids": [64],
            }
        ],
    )

    _normalize_intentional_filter_warnings(material)

    assert material.warnings == []
    assert material.status == "verified"


def test_v4_intentional_role_filter_warning_remains_blocking_without_aligned_evidence():
    material = SimpleNamespace(
        warnings=[FILTERED_ROLE_WARNING],
        status="needs_review",
        claims=[
            {
                "category": "identity",
                "evidence_unit_ids": [1],
            }
        ],
    )

    _normalize_intentional_filter_warnings(material)

    assert material.warnings == [FILTERED_ROLE_WARNING]
    assert material.status == "needs_review"


def test_v4_quality_gate_fails_closed_on_section_heading_claim():
    job = _job()
    heading = _unit("EDUCATION & TECHNICAL SKILLS", 79)
    claims = [
        {
            "text": "EDUCATION & TECHNICAL SKILLS",
            "category": "employment",
            "applicant_fact": True,
            "evidence_unit_ids": [79],
            "evidence_hashes": [heading.source_hash],
        }
    ]

    warnings = _quality_warnings(
        "RELEVANT EXPERIENCE\n• EDUCATION & TECHNICAL SKILLS\n",
        claims,
        job,
        {79: heading},
    )

    assert any("section heading" in warning for warning in warnings)
