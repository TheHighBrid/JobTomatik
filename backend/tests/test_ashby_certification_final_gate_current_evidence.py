from pathlib import Path


def test_physical_gate_has_evidence_schema_and_verifier():
    assert Path("docs/ashby-real-certification-evidence.example.json").exists()
    assert Path("backend/scripts/verify_ashby_real_certification.py").exists()
