from types import SimpleNamespace

from app.services.material_generation import (
    _cover_letter_content,
    _resume_summary_content,
    _usable_narrative_unit,
    validate_claims,
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
        label="Fullscript regression evidence",
        statement=statement,
        organization=organization,
        role=role,
        source_type=source_type,
        source_hash=f"fullscript-regression-{unit_id}",
        verification_status="source_backed",
        confidence=0.9,
    )


def _job():
    return SimpleNamespace(
        title="Technical Support Specialist",
        company="Fullscript",
        location="Canada",
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


def test_current_fullscript_wrapped_resume_lines_are_not_usable_employment_evidence():
    broken = [
        _unit(
            "Created call-support resources and submitted process-improvement ideas "
            "to improve service consistency and customer",
            1,
        ),
        _unit(
            "environments, networking fundamentals, accurate data entry, case notes, "
            "and compliance documentation.",
            2,
        ),
        _unit(
            "Followed compliance routines, risk controls, and escalation procedures "
            "while documenting fraud/security interactions for",
            3,
        ),
    ]
    complete = _unit(
        "Supported clients with fraud, account-security, and digital-banking concerns "
        "through multiple communication channels.",
        4,
    )
    dated_header = _unit(
        "Customer Care Officer (Bilingual) | TD Canada Trust Bank, Ottawa, ON | "
        "November 2018 - April 2022",
        5,
    )

    assert [_usable_narrative_unit(unit) for unit in broken] == [False, False, False]
    assert _usable_narrative_unit(complete) is True
    assert _usable_narrative_unit(dated_header) is True

    claims = [
        {
            "text": unit.statement,
            "category": "employment",
            "applicant_fact": True,
            "evidence_unit_ids": [unit.id],
            "evidence_hashes": [unit.source_hash],
        }
        for unit in broken
    ]
    errors = validate_claims(claims, broken)

    assert any("unpunctuated wrapped résumé employment line" in error for error in errors)
    assert any("lowercase wrapped résumé continuation" in error for error in errors)
    assert any("truncated or dangling résumé employment ending" in error for error in errors)


def test_fullscript_materials_render_complete_evidence_instead_of_keyword_soup():
    current_role = _unit("Credit Officer", 10, kind="role", source_type="profile")
    complete = _unit(
        "Supported clients with fraud, account-security, and digital-banking concerns "
        "through multiple communication channels.",
        11,
    )
    broken = _unit(
        "Created call-support resources and submitted process-improvement ideas "
        "to improve service consistency and customer",
        12,
    )
    skills = [
        _unit("AI Tools", 20, kind="skill", source_type="profile"),
        _unit("Risk Management", 21, kind="skill", source_type="profile"),
        _unit("Data Analysis", 22, kind="skill", source_type="profile"),
        _unit("Time Management", 23, kind="skill", source_type="profile"),
    ]
    ranked = [current_role, complete, broken, *skills]
    user = SimpleNamespace(full_name="Mohamed Alem")

    cover, cover_claims, _ = _cover_letter_content(user, _job(), ranked)
    summary, summary_claims, _ = _resume_summary_content(user, _job(), ranked)

    for content in (cover, summary):
        assert "accurate, canada, care" not in content.casefold()
        assert "areas directly relevant to this role, including" not in content
        assert "Together, this background overlaps" not in content
        assert "Documented experience overlaps with this role in" not in content
        assert complete.statement in content
        assert broken.statement not in content

    assert "My background includes experience as Credit Officer." not in cover
    assert "My documented skills include AI Tools; Risk Management; Data Analysis; Time Management." not in cover
    assert all(broken.id not in claim["evidence_unit_ids"] for claim in cover_claims)
    assert all(broken.id not in claim["evidence_unit_ids"] for claim in summary_claims)
