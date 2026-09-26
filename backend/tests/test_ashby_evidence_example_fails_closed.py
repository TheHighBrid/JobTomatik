import json
from pathlib import Path

from backend.scripts.verify_ashby_real_certification import verify


def test_example_is_non_certifying_template():
    payload = json.loads(
        Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8")
    )
    assert verify(payload)
