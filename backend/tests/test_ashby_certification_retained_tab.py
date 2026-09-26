from pathlib import Path


def test_exact_retained_tab_is_required():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "exact retained application tab" in contract
    assert "unrelated browser tab" in contract
