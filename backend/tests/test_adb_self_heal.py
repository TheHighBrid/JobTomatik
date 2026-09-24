import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/jobtomatik_adb_self_heal.sh"


def run_with_fake_adb(fake_body: str):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        adb = root / "adb"
        adb.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + fake_body)
        adb.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{root}:{env['PATH']}"
        env["JOBTOMATIK_ANDROID_RUNTIME_DIR"] = str(root / "runtime")
        env["JOBTOMATIK_FAKE_ADB_STATE"] = str(root / "connected")
        env.pop("ANDROID_SERIAL", None)
        return subprocess.run(
            ["bash", str(SCRIPT)], env=env, text=True, capture_output=True, check=False
        )


def test_mdns_rotated_endpoint_reconnects_without_stack_restart():
    result = run_with_fake_adb(r'''
state="$JOBTOMATIK_FAKE_ADB_STATE"
case "${1:-}" in
  devices)
    echo "List of devices attached"
    if [[ -f "$state" ]]; then echo -e "10.0.0.231:44117\tdevice"; fi
    ;;
  mdns)
    echo "adb-ABC123 _adb-tls-connect._tcp 10.0.0.231:44117"
    ;;
  connect)
    [[ "$2" == "10.0.0.231:44117" ]]
    touch "$state"
    echo "connected to $2"
    ;;
  *) exit 2 ;;
esac
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "10.0.0.231:44117"
    assert "source=mdns" in result.stderr
    assert "restart" not in result.stderr.lower()


def test_multiple_connected_devices_fail_closed():
    result = run_with_fake_adb(r'''
if [[ "${1:-}" == devices ]]; then
  printf 'List of devices attached\none:1\tdevice\ntwo:2\tdevice\n'
elif [[ "${1:-}" == mdns ]]; then
  exit 0
else
  echo FORBIDDEN >&2
  exit 9
fi
''')
    assert result.returncode != 0
    assert "AMBIGUOUS" in result.stderr
    assert "FORBIDDEN" not in result.stderr


def test_unpaired_mdns_candidate_fails_closed():
    result = run_with_fake_adb(r'''
case "${1:-}" in
  devices) echo "List of devices attached" ;;
  mdns) echo "adb-UNKNOWN _adb-tls-connect._tcp 10.0.0.99:39999" ;;
  connect) echo "failed to connect"; exit 1 ;;
  *) exit 2 ;;
esac
''')
    assert result.returncode != 0
    assert "UNAVAILABLE" in result.stderr
