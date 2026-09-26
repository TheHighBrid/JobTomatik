from pathlib import Path


def test_tooling_prepared_while_status_pending():
    assert Path("backend/scripts/verify_ashby_real_certification.py").exists()
    assert "Status: IN PROGRESS" in Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
