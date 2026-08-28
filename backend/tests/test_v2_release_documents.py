from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_root_release_identity_is_v2_candidate():
    assert _read("VERSION").strip() == "2.0.0"

    readme = _read("README.md")
    assert readme.startswith("# JobTomatik v2.00\n")
    assert "Release-candidate source" in readme
    assert "v2.0.0" in readme
    assert "version name: `2.0.0`" not in readme.lower() or "2.0.0" in readme


def test_v2_release_document_set_exists():
    required = (
        "docs/RELEASE_NOTES_v2.00.md",
        "docs/KNOWN_BOUNDARIES_v2.00.md",
        "docs/OPERATOR_GUIDE_v2.00.md",
        "docs/RELEASE_CHECKLIST_v2.00.md",
        "docs/operations/recovery-incident-response.md",
        "docs/operations/DAY_41_RELEASE_CANDIDATE_AUDIT.md",
        "docs/operations/DAY_42_V2_RELEASE.md",
    )
    missing = [path for path in required if not (REPO_ROOT / path).is_file()]
    assert missing == []


def test_release_notes_are_truthful_prepublication_docs():
    notes = _read("docs/RELEASE_NOTES_v2.00.md")

    assert "Pre-release document" in notes
    assert "must not be represented as a published v2.00 release" in notes
    assert "Publication itself never promotes adapter maturity" in notes
    assert "development_signed" in notes
    assert "release_signed" in notes
    assert "CANDIDATE-METADATA.json" in notes
    assert "DAY42-READINESS-SHA256.txt" in notes


def test_known_boundaries_match_bounded_autonomy_contract():
    boundaries = _read("docs/KNOWN_BOUNDARIES_v2.00.md")

    for token in (
        "CAPTCHA",
        "MFA",
        "submission_uncertain",
        "certified_autonomous",
        "rolling application caps",
        "quiet hours",
        "live authorization",
        "Real follow-up sending is separately gated",
        "must not rebuild the APK after owner approval",
        "development_signed",
    ):
        assert token in boundaries


def test_operator_guide_contains_containment_upgrade_and_rollback_contracts():
    guide = _read("docs/OPERATOR_GUIDE_v2.00.md")

    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in guide
    assert "AUTOPILOT_ENABLED=false" in guide
    assert "Do not click submit again." in guide
    assert "A runtime acceptance receipt from an older source revision is stale" in guide
    assert "Never reuse one from the previous commit" in guide
    assert "Do not downgrade the database in place" in guide
    assert "DAY42-READINESS-SHA256.txt" in guide


def test_release_checklist_is_evidence_bound_not_calendar_bound():
    checklist = _read("docs/RELEASE_CHECKLIST_v2.00.md")

    assert "No checkbox in this file substitutes for retained machine-readable evidence" in checklist
    assert "Genuine physical 24-hour Day 38 endurance report passed" in checklist
    assert "Frozen-v1 compatibility report SHA-256" in checklist
    assert "Candidate workflow run ID" in checklist
    assert "Publisher does not rebuild the APK" in checklist
    assert "Post-publication verification reference" in checklist


def test_readme_and_changelog_match_release_scope_and_exact_artifact_flow():
    readme = _read("README.md")
    changelog = _read("CHANGELOG.md")

    for document in (readme, changelog):
        assert "Lever" in document
        assert "Greenhouse" in document
        assert "Ashby" in document
        assert "SmartRecruiters" in document
        assert "Workday" in document
        assert "certified_autonomous" in document
        assert "dry_run" in document
        assert "detect_only" in document

    assert "## [2.0.0]" in changelog
    assert "publisher downloads and verifies the approved prebuilt candidate" in changelog.lower()
    assert "The publisher does **not** rebuild the APK after owner approval." in readme


def test_release_docs_do_not_claim_publication_is_already_complete():
    readme = _read("README.md")
    notes = _read("docs/RELEASE_NOTES_v2.00.md")
    checklist = _read("docs/RELEASE_CHECKLIST_v2.00.md")

    assert "release exists only after" in readme
    assert "Pre-release document" in notes
    assert "Pre-release checklist" in checklist
    assert "publication_executed=true" not in readme
    assert "publication_executed=true" not in notes
