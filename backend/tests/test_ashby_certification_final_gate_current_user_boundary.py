from pathlib import Path


def test_user_involvement_is_limited_to_genuine_application_boundary():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "genuinely intends to apply to" in runbook
    assert "## One physical run" in runbook
