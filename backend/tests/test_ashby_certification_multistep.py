from pathlib import Path


def test_multistep_support_is_declared():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert '"multi_step": True' in adapter
