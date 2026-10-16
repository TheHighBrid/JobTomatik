"""The Affirm #14 repair script must be safe to run more than once."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "apply_affirm14_timezone_fix.py"
SPEC = importlib.util.spec_from_file_location("apply_affirm14_timezone_fix", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
FIX_SCRIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIX_SCRIPT)


def test_timezone_fix_script_is_idempotent_even_when_docstring_mentions_utcnow(
    tmp_path, monkeypatch, capsys
):
    target = tmp_path / "supervised_submission.py"
    target.write_text(
        "from datetime import datetime, timedelta\n\n"
        "def _now() -> datetime:\n"
        "    return datetime.utcnow()\n"
    )
    monkeypatch.setattr(FIX_SCRIPT, "TARGET", target)

    assert FIX_SCRIPT.main() == 0
    fixed_source = target.read_text()
    assert "Naive utcnow() caused TypeError" in fixed_source
    assert "return datetime.now(timezone.utc)" in fixed_source

    assert FIX_SCRIPT.main() == 0
    assert target.read_text() == fixed_source
    assert "already fixed" in capsys.readouterr().out
