from pathlib import Path


def test_contract_covers_full_lifecycle():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert all(term in text for term in ("real Ashby", "retained application tab", "Answer Vault", "post-submit confirmation", "persist confirmation", "`applied`", "submission attempt"))
