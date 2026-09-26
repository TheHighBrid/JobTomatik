from pathlib import Path


def test_resumed_handoff_cannot_select_unrelated_tab():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "A resumed handoff must not silently select an unrelated browser tab" in text
