from pathlib import Path


def test_real_gate_requires_exact_tab_resume():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "resume the same retained application after answers are saved" in text
