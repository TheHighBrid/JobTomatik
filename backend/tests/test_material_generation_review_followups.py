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
    assert content.count("My documented experience relevant to this role includes:") == 1
    assert employment.statement in content
    assert "My documented employment history also covers" not in content
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


def test_capitalized_terminal_labels_are_not_treated_as_fragments():
    cases = (
        ("Commercial Driver's License Class A", "credential"),
        ("Maintained Grade A.", "achievement"),
    )

    for index, (statement, kind) in enumerate(cases, start=20):
        unit = _unit(statement, index, kind=kind)
        assert _usable_narrative_unit(unit) is True
        claim = {
            "text": statement,
            "category": kind,
            "applicant_fact": True,
            "evidence_unit_ids": [unit.id],
            "evidence_hashes": [unit.source_hash],
        }
        assert validate_claims([claim], [unit]) == []

    broken = _unit("Completed the", 30, kind="achievement")
    assert _usable_narrative_unit(broken) is False
    broken_claim = {
        "text": "Completed the.",
        "category": "achievement",
        "applicant_fact": True,
        "evidence_unit_ids": [broken.id],
        "evidence_hashes": [broken.source_hash],
    }
    assert any(
        "likely incomplete" in warning
        for warning in validate_claims([broken_claim], [broken])
    )


def test_malformed_experience_is_filtered_before_sentence_composition():
    bad_years = _unit("4 and", 40, kind="experience")
    role = _unit("Fraud Analyst", 41, kind="role")
    user = SimpleNamespace(full_name=None)

    assert _usable_narrative_unit(bad_years) is False
    cover, cover_claims, _ = _cover_letter_content(user, _job(), [role, bad_years])
    summary, summary_claims, _ = _resume_summary_content(user, _job(), [role, bad_years])

    assert "4 and years" not in cover
    assert "4 and years" not in summary
    assert all(bad_years.id not in claim["evidence_unit_ids"] for claim in cover_claims)
    assert all(bad_years.id not in claim["evidence_unit_ids"] for claim in summary_claims)

    stale_claim = {
        "text": "Background includes 4 and years of experience.",
        "category": "career_summary",
        "applicant_fact": True,
        "evidence_unit_ids": [bad_years.id],
        "evidence_hashes": [bad_years.source_hash],
    }
    assert any(
        "likely incomplete experience evidence unit" in warning
        for warning in validate_claims([stale_claim], [bad_years])
    )


def test_job_alignment_claim_validates_hidden_fragmentary_referenced_evidence():
    units = [
        _unit("Risk Management", 50, kind="skill"),
        _unit("Python", 51, kind="skill"),
        _unit("Case Documentation", 52, kind="skill"),
        _unit("Risk management, data analysis, and", 53, kind="skill"),
    ]
    claim = {
        "text": "Together, this background overlaps with the posting in areas including risk, python.",
        "category": "job_alignment",
        "applicant_fact": True,
        "evidence_unit_ids": [unit.id for unit in units],
        "evidence_hashes": [unit.source_hash for unit in units],
    }

    errors = validate_claims([claim], units)

    assert any(
        "likely incomplete skill evidence unit 53" in warning
        for warning in errors
    )


def test_structured_employment_preserves_organization_terminal_punctuation():
    employment = _unit(
        "Structured employment record.",
        60,
        kind="employment",
        organization="Yahoo!",
        role="Fraud Analyst",
    )

    content, claims, _ = _cover_letter_content(
        SimpleNamespace(full_name=None),
        _job(),
        [employment],
    )

    assert "with Yahoo!" in content
    assert "with Yahoo." not in content
    assert "Yahoo!." not in content
    employment_claim = next(
        claim
        for claim in claims
        if claim["category"] == "employment"
        and claim["evidence_unit_ids"] == [employment.id]
    )
    assert "with Yahoo!" in employment_claim["text"]
    assert employment_claim["evidence_hashes"] == [employment.source_hash]


def test_complete_phrase_ending_in_and_strong_remains_usable():
    valid = _unit(
        "Maintained controls that were effective and strong.",
        70,
        kind="achievement",
    )
    known_fragment = _unit(
        "Resolved client issues using authentication procedures, analytical troubleshooting, clear bilingual communication, and strong",
        71,
        kind="employment",
    )

    assert _usable_narrative_unit(valid) is True
    assert _usable_narrative_unit(known_fragment) is False

    valid_claim = {
        "text": valid.statement,
        "category": "achievement",
        "applicant_fact": True,
        "evidence_unit_ids": [valid.id],
        "evidence_hashes": [valid.source_hash],
    }
    assert validate_claims([valid_claim], [valid]) == []


def test_structured_employment_rejects_malformed_role_field():
    employment = _unit(
        "Yahoo! | Fraud Analyst and | Investigated fraud alerts.",
        80,
        kind="employment",
        organization="Yahoo!",
        role="Fraud Analyst and",
    )

    assert _usable_narrative_unit(employment) is False

    cover, cover_claims, _ = _cover_letter_content(
        SimpleNamespace(full_name=None),
        _job(),
        [employment],
    )
    summary, summary_claims, _ = _resume_summary_content(
        SimpleNamespace(full_name=None),
        _job(),
        [employment],
    )

    assert "Fraud Analyst and with" not in cover
    assert "Fraud Analyst and" not in summary
    assert all(employment.id not in claim["evidence_unit_ids"] for claim in cover_claims)
    assert all(employment.id not in claim["evidence_unit_ids"] for claim in summary_claims)

    stale_claim = {
        "text": "My experience includes work as Fraud Analyst and with Yahoo!",
        "category": "employment",
        "applicant_fact": True,
        "evidence_unit_ids": [employment.id],
        "evidence_hashes": [employment.source_hash],
    }
    assert any(
        "likely incomplete employment role in evidence unit 80" in warning
        for warning in validate_claims([stale_claim], [employment])
    )


def test_serial_and_strong_narrative_is_preserved_while_known_fragments_stay_blocked():
    valid = _unit(
        "Maintained controls that were reliable, effective, and strong.",
        90,
        kind="achievement",
    )
    observed_strong_fragment = _unit(
        "Resolved client issues using authentication procedures, analytical troubleshooting, clear bilingual communication, and strong",
        91,
        kind="employment",
    )
    observed_internal_fragment = _unit(
        "Assess hardship scenarios and arrange payment solutions aligned with client affordability, account status, and internal",
        92,
        kind="employment",
    )

    assert _usable_narrative_unit(valid) is True
    assert _usable_narrative_unit(observed_strong_fragment) is False
    assert _usable_narrative_unit(observed_internal_fragment) is False

    valid_claim = {
        "text": valid.statement,
        "category": "achievement",
        "applicant_fact": True,
        "evidence_unit_ids": [valid.id],
        "evidence_hashes": [valid.source_hash],
    }
    assert validate_claims([valid_claim], [valid]) == []


def test_role_phrase_rejects_dangling_preposition_but_narrative_preposition_remains_valid():
    role = _unit("Fraud Analyst with", 100, kind="role")
    employment = _unit(
        "Yahoo! | Fraud Analyst with | Investigated fraud alerts.",
        101,
        kind="employment",
        organization="Yahoo!",
        role="Fraud Analyst with",
    )
    narrative = _unit(
        "Built the reporting tool customers asked for.",
        102,
        kind="achievement",
    )

    assert _usable_narrative_unit(role) is False
    assert _usable_narrative_unit(employment) is False
    assert _usable_narrative_unit(narrative) is True

    role_claim = {
        "text": "Background includes experience as Fraud Analyst with.",
        "category": "career_summary",
        "applicant_fact": True,
        "evidence_unit_ids": [role.id],
        "evidence_hashes": [role.source_hash],
    }
    employment_claim = {
        "text": "My experience includes work as Fraud Analyst with with Yahoo!",
        "category": "employment",
        "applicant_fact": True,
        "evidence_unit_ids": [employment.id],
        "evidence_hashes": [employment.source_hash],
    }

    assert any(
        "likely incomplete role evidence unit 100" in warning
        for warning in validate_claims([role_claim], [role])
    )
    assert any(
        "likely incomplete employment role in evidence unit 101" in warning
        for warning in validate_claims([employment_claim], [employment])
    )


def test_experience_phrase_rejects_dangling_preposition_before_material_composition():
    bad_years = _unit("4 to", 110, kind="experience")
    role = _unit("Fraud Analyst", 111, kind="role")
    user = SimpleNamespace(full_name=None)

    assert _usable_narrative_unit(bad_years) is False

    cover, cover_claims, _ = _cover_letter_content(user, _job(), [role, bad_years])
    summary, summary_claims, _ = _resume_summary_content(user, _job(), [role, bad_years])

    assert "4 to years" not in cover
    assert "4 to years" not in summary
    assert all(bad_years.id not in claim["evidence_unit_ids"] for claim in cover_claims)
    assert all(bad_years.id not in claim["evidence_unit_ids"] for claim in summary_claims)

    stale_claim = {
        "text": "Fraud Analyst with 4 to years of experience.",
        "category": "career_summary",
        "applicant_fact": True,
        "evidence_unit_ids": [bad_years.id],
        "evidence_hashes": [bad_years.source_hash],
    }
    assert any(
        "likely incomplete experience evidence unit 110" in warning
        for warning in validate_claims([stale_claim], [bad_years])
    )
