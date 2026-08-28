from types import SimpleNamespace

from app.services.material_generation import (
    _clean_material_statement,
    _usable_narrative_unit,
    validate_claims,
)


def _unit(statement: str, unit_id: int = 1):
    return SimpleNamespace(
        id=unit_id,
        kind="employment",
        label="Resume experience",
        statement=statement,
        organization=None,
        role=None,
        source_hash=f"hash-{unit_id}",
        verification_status="source_backed",
        confidence=0.85,
    )


def test_real_pdf_fragments_are_not_usable_narrative_evidence():
    fragments = [
        "\uf0b7 Resolved client issues using authentication procedures, analytical troubleshooting, clear bilingual communication, and strong",
        "\uf0b7 Review account situations, document client interactions in internal systems, and maintain accurate notes for auditability,",
        "\uf0b7 Verified client information, assessed risk indicators, and resolved fraud/security issues at first point of contact when",
    ]

    assert all(_usable_narrative_unit(_unit(statement)) is False for statement in fragments)


def test_complete_pdf_bullet_is_cleaned_without_discarding_its_evidence():
    statement = (
        "\uf0b7 Investigated API and web issues, documented escalations, "
        "and supported customers."
    )
    unit = _unit(statement)

    assert _usable_narrative_unit(unit) is True
    assert _clean_material_statement(statement) == (
        "Investigated API and web issues, documented escalations, and supported customers."
    )


def test_validator_blocks_pre_fix_material_with_pdf_glyph_and_fragment():
    unit = _unit(
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
