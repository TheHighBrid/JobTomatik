from types import SimpleNamespace

from app.services.material_generation_v5_policy import (
    _normalize_v5_structural_warnings,
    _rewrite_client_success_material,
    _role_aware_ranked,
)


def _skill(statement: str, unit_id: int):
    return SimpleNamespace(
        id=unit_id,
        kind="skill",
        label="client-success-policy-regression",
        statement=statement,
        organization=None,
        role=None,
        source_type="profile",
        source_ref=f"profile:{unit_id}",
        source_hash=f"policy-{unit_id}",
        verification_status="source_backed",
        confidence=0.9,
    )


def _maple_job():
    return SimpleNamespace(
        title="Client Success Associate (Bilingual, French/English)",
        company="Maple",
        description=(
            "Own the day-to-day success of a portfolio of channel partners. "
            "Lead bilingual partner communication, coordinate renewals, keep Salesforce "
            "accurate, use data for reporting, and work cross-functionally."
        ),
        requirements=(
            "Client-facing experience, organization, reporting, CRM comfort, "
            "professional communication, and proactive problem-solving."
        ),
        skills=[],
    )


def _fullscript_job():
    return SimpleNamespace(
        title="Technical Support Specialist",
        company="Fullscript",
        description=(
            "Investigate customer-reported technical issues, troubleshoot software, "
            "document reproduction steps, and partner with Engineering."
        ),
        requirements="Technical support, APIs, web technologies, troubleshooting.",
        skills=["Technical Support", "Troubleshooting"],
    )


def test_v5_structural_headings_are_non_blocking_but_other_warnings_remain():
    material = SimpleNamespace(
        content=(
            "Mohamed Alem\n\n"
            "EMPLOYMENT HISTORY\n"
            "• Customer Care Officer | TD Canada Trust | November 2018 - April 2022\n\n"
            "RELEVANT SUPPORT EXPERIENCE\n"
            "• Supported clients across multiple communication channels\n"
        ),
        warnings=[
            "Generated material contains an unexpected résumé section heading: EMPLOYMENT HISTORY",
            "Generated material contains an unexpected résumé section heading: RELEVANT SUPPORT EXPERIENCE",
        ],
        status="needs_review",
    )

    _normalize_v5_structural_warnings(material)

    assert material.warnings == []
    assert material.status == "verified"

    material.warnings = [
        "Generated material contains an unexpected résumé section heading: EMPLOYMENT HISTORY",
        "No substantive applicant claim could be supported by active evidence",
    ]
    material.status = "needs_review"

    _normalize_v5_structural_warnings(material)

    assert material.warnings == [
        "No substantive applicant claim could be supported by active evidence"
    ]
    assert material.status == "needs_review"


def test_v5_structural_warning_is_not_removed_when_heading_is_absent():
    material = SimpleNamespace(
        content="Mohamed Alem\n\nCORE SKILLS\nLinux\n",
        warnings=[
            "Generated material contains an unexpected résumé section heading: EMPLOYMENT HISTORY"
        ],
        status="needs_review",
    )

    _normalize_v5_structural_warnings(material)

    assert material.warnings == [
        "Generated material contains an unexpected résumé section heading: EMPLOYMENT HISTORY"
    ]
    assert material.status == "needs_review"


def test_client_success_policy_filters_specialist_skills_and_keeps_role_relevant_strengths():
    ranked = [
        _skill("Bilingual", 1),
        _skill("IP TRACKING", 2),
        _skill("REPORTING", 3),
        _skill("Linux", 4),
        _skill("Debian", 5),
        _skill("AI Tools", 6),
        _skill("Data Analysis", 7),
        _skill("De-escalation", 8),
        _skill("Time Management", 9),
        _skill("Microsoft Office", 10),
    ]

    filtered = _role_aware_ranked(ranked, _maple_job())
    labels = [unit.statement for unit in filtered]

    assert labels == [
        "Bilingual",
        "REPORTING",
        "Data Analysis",
        "De-escalation",
        "Time Management",
        "Microsoft Office",
    ]
    assert "IP TRACKING" not in labels
    assert "Linux" not in labels
    assert "Debian" not in labels
    assert "AI Tools" not in labels


def test_client_success_policy_uses_role_appropriate_summary_and_alignment_wording():
    job = _maple_job()
    old_alignment = (
        "I am particularly interested in Maple's Client Success Associate "
        "(Bilingual, French/English) role and its focus on cross-functional collaboration."
    )
    content = (
        "My background includes bilingual customer care experience and technical skills "
        "in Data Analysis, Microsoft Office.\n\n"
        + old_alignment
    )
    claims = [
        {
            "category": "career_summary",
            "text": (
                "My background includes bilingual customer care experience and technical "
                "skills in Data Analysis, Microsoft Office."
            ),
            "applicant_fact": True,
            "evidence_unit_ids": [1, 7, 10],
        },
        {
            "category": "target_alignment",
            "text": old_alignment,
            "applicant_fact": False,
            "evidence_unit_ids": [],
        },
    ]

    rewritten, rewritten_claims = _rewrite_client_success_material(
        content,
        claims,
        job,
    )

    assert "technical skills" not in rewritten
    assert "documented strengths in Data Analysis, Microsoft Office" in rewritten
    assert "bilingual partner communication" in rewritten
    assert "partner relationship management" in rewritten
    assert "renewal coordination" in rewritten
    assert rewritten_claims[0]["evidence_unit_ids"] == [1, 7, 10]
    assert "technical skills" not in rewritten_claims[0]["text"]
    assert rewritten_claims[1]["applicant_fact"] is False


def test_technical_support_behavior_is_not_rewritten_or_filtered():
    ranked = [_skill("Linux", 1), _skill("Debian", 2), _skill("AI Tools", 3)]
    job = _fullscript_job()

    assert _role_aware_ranked(ranked, job) == ranked

    content = "My background includes technical skills in Linux, Debian, AI Tools."
    claims = [
        {
            "category": "career_summary",
            "text": content,
            "applicant_fact": True,
            "evidence_unit_ids": [1, 2, 3],
        }
    ]
    rewritten, rewritten_claims = _rewrite_client_success_material(
        content,
        claims,
        job,
    )

    assert rewritten == content
    assert rewritten_claims == claims
