import json
from pathlib import Path

from backend.scripts.verify_ashby_real_certification import verify


def test_template_evidence_cannot_satisfy_final_gate():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert verify(payload)
