from pathlib import Path


def test_manifest_does_not_preclaim_submit():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"final_submit_clicked": False' in adapter
