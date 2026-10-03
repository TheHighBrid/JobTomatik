from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXPORTER = BACKEND_ROOT / "scripts" / "export_day38_shadow_endurance.py"


def test_day38_exporter_starts_as_standalone_script_without_pythonpath():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(EXPORTER), "--help"],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--session-id" in result.stdout
    assert "--verification-revision" in result.stdout
    assert "--output" in result.stdout
