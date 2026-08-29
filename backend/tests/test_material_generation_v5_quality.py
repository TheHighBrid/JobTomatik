from types import SimpleNamespace

from app.services.material_generation_v5 import (
    GENERATOR_VERSION,
    _cover_letter_content,
    _paraphrase_support_detail,
    _resume_summary_content,
    _target_alignment_sentence,
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
    assert "Supported clients across multiple communication channels." in cover
    assert "Provided clear guidance on digital account and security concerns." in cover
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
    assert support_lines[0] == "• Supported clients across multiple communication channels"
    assert support_lines[1] == "• Provided clear guidance on digital account and security concerns"
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


def test_v5_does_not_infer_client_support_from_channel_phrase_alone():
    unit = _unit(
        "Coordinated marketing activity through multiple communication channels.",
        90,
    )
    assert _paraphrase_support_detail(unit) == unit.statement


def test_v5_target_alignment_is_derived_from_each_posting():
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
