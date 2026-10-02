from types import SimpleNamespace

from app.services.evidence_ledger import normalize_statement, resume_text_candidates
from app.services.material_generation import (
    _as_sentence,
    _cover_letter_content,
    _resume_summary_content,
    _usable_narrative_unit,
    validate_claims,
)


def _unit(
    statement: str,
    unit_id: int,
    *,
    kind: str,
    organization: str | None = None,
    role: str | None = None,
):
    return SimpleNamespace(
        id=unit_id,
        kind=kind,
        label="Review follow-up evidence",
        statement=statement,
        organization=organization,
        role=role,
        source_hash=f"review-followup-{unit_id}",
        verification_status="source_backed",
        confidence=0.9,
    )


def _job():
    return SimpleNamespace(
        title="Fraud Investigator",
        company="Example Bank",
        location="Ottawa, ON",
        description="Investigate fraud alerts and document cases for customers.",
        requirements="Fraud investigation, case documentation, customer support.",
        skills=["Fraud Investigation", "Case Documentation"],
    )


def test_complete_sentences_ending_in_prepositions_remain_usable():
    statements = (
        "Built the reporting tool customers asked for.",
        "Led the engineering team I worked with.",
        "This is the role I applied to.",
        "That is the result I am proud of.",
    )

    for index, statement in enumerate(statements, start=1):
        unit = _unit(statement, index, kind="achievement")
        assert _usable_narrative_unit(unit) is True
        claim = {
            "text": statement,
            "category": "achievement",
            "applicant_fact": True,
            "evidence_unit_ids": [unit.id],
            "evidence_hashes": [unit.source_hash],
        }
        assert not any(
            "likely incomplete" in warning
            for warning in validate_claims([claim], [unit])
        )


def test_punctuated_role_and_year_values_are_composed_as_phrases():
    role = _unit("Fraud Analyst.", 1, kind="role")
    years = _unit("4.", 2, kind="experience")
    user = SimpleNamespace(full_name=None)

    cover, _, _ = _cover_letter_content(user, _job(), [role, years])
    summary, _, _ = _resume_summary_content(user, _job(), [role, years])

    expected = "Fraud Analyst with 4 years of experience."
    assert expected in summary
    assert "Fraud Analyst. with" not in summary
    assert "4. years" not in summary
    assert "work as Fraud Analyst." in cover
    assert "Fraud Analyst.." not in cover
    assert "4. years" not in cover


def test_unstructured_employment_alignment_is_emitted_once():
    employment = _unit(
        "Investigated fraud alerts and documented cases.",
        1,
        kind="employment",
    )

    content, claims, _ = _cover_letter_content(
        SimpleNamespace(full_name=None),
        _job(),
        [employment],
    )

    alignment_claims = [claim for claim in claims if claim["category"] == "job_alignment"]
    assert len(alignment_claims) == 1
    assert alignment_claims[0]["evidence_unit_ids"] == [employment.id]
    assert content.count("My documented employment history also covers") == 1
    assert "Together, this background overlaps" not in content


def test_sentence_punctuation_is_added_outside_unpunctuated_closing_quote():
    assert _as_sentence('Known for being a "customer advocate"') == (
        'Known for being a "customer advocate".'
    )
    assert _as_sentence('Known for being a "customer advocate."') == (
        'Known for being a "customer advocate."'
    )


def test_evidence_normalization_preserves_signed_metrics_before_rendering():
    assert normalize_statement("-10% error rate") == "-10% error rate"
    assert normalize_statement("- Reduced error rate") == "Reduced error rate"
    assert normalize_statement("• Reduced error rate") == "Reduced error rate"

    candidates = resume_text_candidates(
        "ACHIEVEMENTS\n-10% error rate\n- Reduced processing errors",
        source_ref="resume:signed-metric-test.pdf",
    )
    statements = [candidate["statement"] for candidate in candidates]

    assert "-10% error rate" in statements
    assert "Reduced processing errors" in statements
    assert "10% error rate" not in statements


def test_job_alignment_validates_every_referenced_fragment_sensitive_unit():
    units = [
        _unit("Fraud Investigation", 1, kind="skill"),
        _unit("Case Documentation", 2, kind="skill"),
        _unit("Customer Support", 3, kind="skill"),
        _unit("Risk management, data analysis, and", 4, kind="skill"),
    ]
    claim = {
        "text": "This background overlaps with the posting in fraud investigation.",
        "category": "job_alignment",
        "applicant_fact": True,
        "evidence_unit_ids": [unit.id for unit in units],
        "evidence_hashes": [unit.source_hash for unit in units],
    }

    warnings = validate_claims([claim], units)

    assert any("skill evidence unit 4" in warning for warning in warnings)


def test_capitalized_labels_are_not_mistaken_for_dangling_articles():
    complete = (
        _unit("Commercial Driver's License Class A", 1, kind="credential"),
        _unit("Maintained Grade A.", 2, kind="achievement"),
    )
    dangling = _unit("Worked on a", 3, kind="achievement")

    assert all(_usable_narrative_unit(unit) for unit in complete)
    assert _usable_narrative_unit(dangling) is False
    for unit in complete:
        claim = {
            "text": unit.statement,
            "category": unit.kind,
            "applicant_fact": True,
            "evidence_unit_ids": [unit.id],
            "evidence_hashes": [unit.source_hash],
        }
        assert validate_claims([claim], [unit]) == []


def test_malformed_experience_is_filtered_from_generation_and_stale_claims():
    experience = _unit("4 and", 1, kind="experience")
    user = SimpleNamespace(full_name=None)

    cover, cover_claims, _ = _cover_letter_content(user, _job(), [experience])
    summary, summary_claims, _ = _resume_summary_content(user, _job(), [experience])

    assert "4 and years" not in cover
    assert "4 and years" not in summary
    assert all(experience.id not in claim["evidence_unit_ids"] for claim in cover_claims)
    assert all(experience.id not in claim["evidence_unit_ids"] for claim in summary_claims)

    stale_claim = {
        "text": "Fraud Analyst with 4 and years of experience.",
        "category": "career_summary",
        "applicant_fact": True,
        "evidence_unit_ids": [experience.id],
        "evidence_hashes": [experience.source_hash],
    }
    assert any(
        "experience evidence unit 1" in warning
        for warning in validate_claims([stale_claim], [experience])
    )


def test_structured_employment_preserves_organization_terminal_punctuation():
    employment = _unit(
        "Investigated fraud alerts at Yahoo!",
        1,
        kind="employment",
        organization="Yahoo!",
        role="Fraud Analyst",
    )

    content, claims, _ = _cover_letter_content(
        SimpleNamespace(full_name=None),
        _job(),
        [employment],
    )

    assert "work as Fraud Analyst with Yahoo!" in content
    assert "with Yahoo." not in content
    employment_claim = next(claim for claim in claims if claim["category"] == "employment")
    assert employment_claim["evidence_unit_ids"] == [employment.id]
    assert employment_claim["evidence_hashes"] == [employment.source_hash]
