import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "jobtomatik_runtime_twin.py"
spec = importlib.util.spec_from_file_location("runtime_twin", SCRIPT)
runtime_twin = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(runtime_twin)


def fixture(browser="Chrome/152.0", protocol="1.3", adb_ok=True):
    return {
        "host": {"android": True, "machine": "aarch64", "termux": True, "proot_distro_available": True},
        "adb": {"devices": {"ok": adb_ok}},
        "browser": {"version": {"ok": True, "json": {"Browser": browser, "Protocol-Version": protocol}}},
    }


def test_identical_physical_contract_matches():
    expected = fixture()
    assert runtime_twin.compare(expected, expected) == []


def test_detects_wrong_architecture_and_browser_identity():
    expected = fixture()
    actual = fixture(browser="Chromium/149.0")
    actual["host"]["machine"] = "x86_64"
    failures = runtime_twin.compare(actual, expected)
    assert any("host.machine" in item for item in failures)
    assert any("browser.Browser" in item for item in failures)


def test_detects_lost_adb_transport_and_cdp():
    expected = fixture()
    actual = fixture(adb_ok=False)
    actual["browser"]["version"] = {"ok": False}
    failures = runtime_twin.compare(actual, expected)
    assert "adb.devices: expected working ADB transport" in failures
    assert "browser.version: expected reachable native Chrome CDP endpoint" in failures
