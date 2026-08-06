from pathlib import Path
import subprocess

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative_path",
    [
        "scripts/start_android_browser_cdp.sh",
        "scripts/manage_android_stack.sh",
    ],
)
def test_android_runtime_shell_script_has_valid_bash_syntax(relative_path):
    script = BACKEND_ROOT / relative_path
    subprocess.run(["bash", "-n", str(script)], check=True)
