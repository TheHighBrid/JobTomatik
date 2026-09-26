from pathlib import Path


def test_historical_dry_runs_are_not_current_certification():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "Historical Ashby dry-run/certification work" in text
    assert "is not accepted as proof of the current Android/native-Chrome runtime" in text
