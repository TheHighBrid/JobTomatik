import json
from pathlib import Path

from backend.scripts.verify_ashby_real_certification import verify


def test_template_is_intentionally_noncertifying():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert verify(payload) != []
