from pathlib import Path


def test_confirmation_evidence_binds_adapter_metadata():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"adapter": self.name' in adapter
    assert '"adapter_version": self.version' in adapter
