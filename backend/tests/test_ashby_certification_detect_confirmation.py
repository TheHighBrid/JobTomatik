from pathlib import Path


def test_real_gate_requires_post_submit_confirmation():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "detect sufficient Ashby post-submit confirmation evidence" in text
