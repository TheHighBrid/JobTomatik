from types import SimpleNamespace

from app.services.material_generation_v5 import (
    GENERATOR_VERSION,
    _cover_letter_content,
    _header_support_phrase,
    _paraphrase_support_detail,
    _resume_summary_content,
    _support_details,
    _target_alignment_sentence,
    _technical_skill_units,
    _v4_compatible_quality_warnings,
    _v5_quality_warnings,
)
from app.services.material_generation_v4 import _curated_ranked


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
        label="Fullscript v5 regression evidence",
        statement=statement,
        organization=organization,
        role=role,
        source_type=source_type,
        source_ref=f"resume:{unit_id}",
        source_hash=f"fullscript-v5-{unit_id}",
        verification_status="source_backed",
        confidence=0.9,
    )


def _job():
    return SimpleNamespace(
        id=1824,
        title="Technical Support Specialist",
        company="Fullscript",
        location="Ottawa, ON",
        url="https://jobs.lever.co/fullscript/a52e4915-8239-4581-8828-84661f070424/apply",
        updated_at=None,
        description=(
            "Validate, reproduce, document, and coordinate customer-reported technical issues. "
            "Investigate defects and configuration issues, provide reproduction steps and logs, "
            "partner with Engineering, and communicate clear technical guidance."
        ),
        requirements=(
            "Technical support, CX operations, incident management, APIs, web technologies, "
            "troubleshooting, problem-solving, documentation, and excellent communication."
        ),
        skills=["Technical Support", "Troubleshooting", "Communication", "AI Tools"],
    )


def _evidence():
    return [
        _unit("Credit Officer", 5, kind="role", source_type="profile"),
        _unit(
            "Monitored account for any suspicious activity",
            35,
            organization="Royal Bank of Canada",
            role="Fraud Officer",
        ),
        _unit(
            "Supported clients with fraud, account-security, and digital-banking concerns through multiple communication channels.",
            64,
        ),
        _unit(
            "Educated clients on fraud prevention, account protection, online banking safety, and appropriate security actions.",
            67,
        ),
        _unit(
            "Customer Care Officer (Bilingual) | TD Canada Trust Bank, Ottawa, ON | November 2018 - April 2022",
            70,
        ),
        _unit("EDUCATION & TECHNICAL SKILLS", 79),
        _unit("Bilingual", 6, kind="skill", source_type="profile"),
        _unit("Microsoft Office", 9, kind="skill", source_type="profile"),
        _unit("Linux", 11, kind="skill", source_type="profile"),
        _unit("De-escalation", 13, kind="skill", source_type="profile"),
        _unit("Debian", 12, kind="skill", source_type="profile"),
        _unit("Time Management", 29, kind="skill", source_type="profile"),
        _unit("Data Analysis", 17, kind="skill", source_type="profile"),
        _unit("AI Tools", 10, kind="skill", source_type="profile"),
        _unit("Risk Management", 20, kind="skill", source_type="profile"),
        _unit("TSYS", 21, kind="skill", source_type="profile"),
    ]


def test_v5_renders_fullscript_cover_as_support_plus_technical_story():
    job = _job()
    ranked = _curated_ranked(_evidence(), job)
    user = SimpleNamespace(full_name="Mohamed Alem")

    cover, claims, warnings = _cover_letter_content(user, job, ranked)

    assert GENERATOR_VERSION == "verified-material-v5"
    assert warnings == []
    assert "bilingual customer care experience" in cover
    assert "technical skills in Linux, Debian, AI Tools, Data Analysis, Microsoft Office" in cover
    assert "technical skills in Bilingual" not in cover
    assert "technical skills in De-escalation" not in cover
    assert "technical skills in Time Management" not in cover
    assert "Supported clients across multiple communication channels." in cover
    assert "issue investigation, documentation, and cross-functional collaboration" in cover

    assert "Credit Officer" not in cover
    assert "Fraud Officer" not in cover
    assert "Monitored account" not in cover
    assert "EDUCATION & TECHNICAL SKILLS" not in cover
    assert "fraud prevention" not in cover.casefold()
    assert "fraud, account-security" not in cover.casefold()
    assert "TSYS" not in cover
    assert "Risk Management" not in cover
    assert "Time Management" not in cover
    assert "My documented experience relevant to this role includes:" not in cover
    assert _v5_quality_warnings(cover, "cover_letter") == []
    assert any(claim["category"] == "career_summary" for claim in claims)


def test_v5_resume_separates_employer_headers_from_unattributed_support_details():
    job = _job()
    ranked = _curated_ranked(_evidence(), job)
    user = SimpleNamespace(full_name="Mohamed Alem")

    summary, claims, warnings = _resume_summary_content(user, job, ranked)

    assert warnings == []
    assert "documented technical skills in Linux, Debian, AI Tools, Data Analysis, Microsoft Office" in summary
    assert "technical skills in Bilingual" not in summary
    employment = summary.split("EMPLOYMENT HISTORY\n", 1)[1].split("\n\n", 1)[0]
    assert employment.splitlines()[0].startswith(
        "• Customer Care Officer (Bilingual) | TD Canada Trust Bank"
    )
    support = summary.split("RELEVANT SUPPORT EXPERIENCE\n", 1)[1].split("\n\n", 1)[0]
    support_lines = support.splitlines()
    assert support_lines == ["• Supported clients across multiple communication channels"]
    assert "RELEVANT EXPERIENCE\n" not in summary

    assert "CORE SKILLS\nBilingual, Linux, Debian, AI Tools, Data Analysis, Microsoft Office" in summary
    assert "Time Management" not in summary
    assert "Risk Management" not in summary
    assert "TSYS" not in summary
    assert "Credit Officer" not in summary
    assert "Fraud Officer" not in summary
    assert "EDUCATION & TECHNICAL SKILLS" not in summary
    assert _v5_quality_warnings(summary, "resume_summary") == []
    employment_claims = [claim for claim in claims if claim["category"] == "employment"]
    assert employment_claims[0]["text"].startswith("Customer Care Officer (Bilingual)")

    unit_by_id = {unit.id: unit for unit in ranked}
    assert _v4_compatible_quality_warnings(summary, claims, job, unit_by_id) == []


def test_v5_does_not_infer_client_support_from_channel_phrase_alone():
    unit = _unit(
        "Coordinated marketing activity through multiple communication channels.",
        90,
    )
    assert _paraphrase_support_detail(unit) == unit.statement


def test_v5_support_section_rejects_zero_support_signal_even_with_job_overlap():
    data_job = SimpleNamespace(
        id=2000,
        title="Data Engineer",
        company="ExampleCo",
        location="Remote",
        url="https://example.com/jobs/data-engineer",
        updated_at=None,
        description="Build Python data pipelines and analytics systems.",
        requirements="Python data pipelines analytics.",
        skills=["Python", "Data"],
    )
    unit = _unit("Built Python data pipelines for analytics.", 97)
    assert _support_details([unit], data_job, limit=1) == []


def test_v5_preserves_customer_education_subject_instead_of_widening_it():
    unit = _unit("Educated customers about account fees.", 91)
    assert _paraphrase_support_detail(unit) == "Educated customers about account fees."


def test_v5_non_support_employment_header_gets_neutral_wording():
    header = _unit(
        "Software Engineer | Acme Inc. | January 2020 - April 2024",
        92,
        organization="Acme Inc.",
        role="Software Engineer",
    )
    assert _header_support_phrase(header) == "documented professional experience"


def test_v5_only_calls_explicit_hard_skill_labels_technical():
    skills = [
        _unit("Linux", 93, kind="skill", source_type="profile"),
        _unit("De-escalation", 94, kind="skill", source_type="profile"),
        _unit("Time Management", 95, kind="skill", source_type="profile"),
        _unit("Bilingual", 96, kind="skill", source_type="profile"),
    ]
    assert [unit.statement for unit in _technical_skill_units(skills)] == ["Linux"]


def test_v5_target_alignment_is_posting_only_and_does_not_assert_capabilities():
    unrelated = SimpleNamespace(
        title="Office Coordinator",
        company="ExampleCo",
        description="Coordinate schedules, maintain records, and organize office supplies.",
        requirements="Organization and communication.",
        skills=[],
    )
    text = _target_alignment_sentence(unrelated)
    assert "issue investigation" not in text
    assert "cross-functional collaboration" not in text
    assert "responsibilities described in the posting" in text
    assert "technical literacy" not in text
    assert "customer communication" not in text


def test_v5_retains_relevant_source_backed_role_without_employment_rows():
    job = _job()
    role = _unit(
        "Technical Support Specialist",
        98,
        kind="role",
        source_type="profile",
    )
    linux = _unit("Linux", 99, kind="skill", source_type="profile")
    ranked = _curated_ranked([role, linux], job)
    user = SimpleNamespace(full_name="Mohamed Alem")

    cover, _, cover_warnings = _cover_letter_content(user, job, ranked)
    summary, _, summary_warnings = _resume_summary_content(user, job, ranked)

    assert cover_warnings == []
    assert summary_warnings == []
    assert "experience as Technical Support Specialist" in cover
    assert "documented experience as Technical Support Specialist" in summary
    assert "technical skills in Linux" in cover
    assert "RELEVANT SUPPORT EXPERIENCE" not in summary


def test_v5_quality_gate_rejects_legacy_cover_mixed_experience_and_skill_labeling():
    cover = (
        "Dear Hiring Manager,\n\n"
        "My documented experience relevant to this role includes: Supported clients.\n"
    )
    assert "legacy evidence-dump" in _v5_quality_warnings(cover, "cover_letter")[0]

    resume = "RELEVANT EXPERIENCE\n• Some old mixed-employer rendering\n"
    assert any("mixed-employer" in item for item in _v5_quality_warnings(resume, "resume_summary"))

    mislabeled = "My background includes technical skills in Bilingual, Linux."
    assert any("mislabeled" in item for item in _v5_quality_warnings(mislabeled, "cover_letter"))

    soft_mislabeled = "My background includes technical skills in De-escalation."
    assert any("mislabeled" in item for item in _v5_quality_warnings(soft_mislabeled, "cover_letter"))
