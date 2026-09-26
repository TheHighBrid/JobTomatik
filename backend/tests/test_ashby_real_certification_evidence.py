import json
from pathlib import Path

from backend.scripts.verify_ashby_real_certification import verify


def test_retained_real_evidence_is_absent_or_valid():
    evidence = Path("evidence/ashby-real-certification.json")
    if not evidence.exists():
        return
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert verify(payload) == []
