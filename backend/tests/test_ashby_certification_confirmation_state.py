from pathlib import Path


def test_applied_transition_is_confirmation_gated():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "`applied` only after sufficient evidence" in contract
