from types import SimpleNamespace

from app.services.material_generation_v5_policy import (
    _normalize_v5_structural_warnings,
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
