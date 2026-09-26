import json
from pathlib import Path


def test_template_binds_hosted_application_target():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert payload["target_url"].startswith("https://jobs.ashbyhq.com/")
    assert payload["target_url"].endswith("/application")
