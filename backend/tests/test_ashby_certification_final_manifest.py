from pathlib import Path


def test_branch_head_manifest_is_not_yet_certified():
    text = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"mode": "not_yet_certified"' in text
