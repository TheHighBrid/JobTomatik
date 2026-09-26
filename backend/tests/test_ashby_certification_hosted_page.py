from pathlib import Path


def test_real_target_is_ashby_hosted():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    template = Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8")
    assert "real Ashby job/application target" in contract
    assert "jobs.ashbyhq.com" in template
