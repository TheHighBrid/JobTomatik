from pathlib import Path


def test_real_gate_requires_unknown_answer_pause():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "stop on unknown or policy-bound questions and surface them to Answer Vault" in text
