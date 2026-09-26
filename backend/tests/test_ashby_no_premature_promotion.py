from pathlib import Path


def test_no_premature_certified_marker_exists():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    doc = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert 'certification_level = "fixture_pending_live_certification"' in adapter
    assert "Status: CERTIFIED" not in doc
