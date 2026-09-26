from pathlib import Path


def test_real_gate_covers_end_to_end_lifecycle():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    required = (
        "resolve a real Ashby job/application target",
        "exact retained application tab",
        "unknown or policy-bound questions",
        "submit only under the normal authorized submission policy",
        "detect sufficient Ashby post-submit confirmation evidence",
        "persist confirmation evidence",
        "`applied` only after sufficient evidence",
        "prevent another submission attempt",
    )
    for phrase in required:
        assert phrase in text
