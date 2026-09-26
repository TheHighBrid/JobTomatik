from pathlib import Path


def test_certification_status_is_truthful_before_physical_run():
    doc = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert "Status: IN PROGRESS" in doc
    assert '"mode": "not_yet_certified"' in adapter
