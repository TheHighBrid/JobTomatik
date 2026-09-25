#!/usr/bin/env python3
"""
Capture and compare the JobTomatik physical Android runtime contract.

This is deliberately not a generic CI environment check.  It records the pieces
that make the owner's production lane special: Android/Termux, Ubuntu PRoot,
ADB transport, native Chrome/CDP, Python/Node tooling, and repository revision.
The resulting JSON can be retained as a fixture and used as the contract for
future acceptance runners.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


def run(*args: str, timeout: int = 8) -> dict:
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        return {"ok": p.returncode == 0, "rc": p.returncode,
                "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)}


def http_json(url: str, timeout: int = 3) -> dict:
    try:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Prohibited URL scheme: {url}")
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return {"ok": True, "status": r.status, "json": json.load(r)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)}


def capture(endpoint: str) -> dict:
    adb = shutil.which("adb")
    proot = shutil.which("proot-distro")
    git = shutil.which("git")
    termux_prefix = os.environ.get("PREFIX", "")
    android = Path("/system/build.prop").exists() or "com.termux" in termux_prefix
    payload = {
        "schema": 1,
        "host": {
            "android": android,
            "machine": platform.machine(),
            "platform": platform.platform(),
            "termux_prefix": termux_prefix,
            "termux": bool(termux_prefix and "com.termux" in termux_prefix),
            "proot_distro_available": bool(proot),
        },
        "repo": run(git, "rev-parse", "HEAD") if git else {"ok": False},
        "tools": {
            "python": {"ok": True, "version": sys.version.split()[0], "executable": sys.executable},
            "adb": run(adb, "version") if adb else {"ok": False, "error": "not_found"},
            "proot_distro": run(proot, "--help") if proot else {"ok": False, "error": "not_found"},
        },
        "adb": {
            "devices": run(adb, "devices", "-l") if adb else {"ok": False, "error": "not_found"},
            "forward": run(adb, "forward", "--list") if adb else {"ok": False, "error": "not_found"},
        },
        "browser": {
            "endpoint": endpoint,
            "version": http_json(endpoint.rstrip("/") + "/json/version"),
            "targets": http_json(endpoint.rstrip("/") + "/json/list"),
        },
    }
    return payload


def compare(actual: dict, expected: dict) -> list[str]:
    failures: list[str] = []
    for key in ("android", "machine", "termux", "proot_distro_available"):
        if expected.get("host", {}).get(key) != actual.get("host", {}).get(key):
            failures.append(f"host.{key}: expected {expected.get('host', {}).get(key)!r}, got {actual.get('host', {}).get(key)!r}")
    exp_browser = expected.get("browser", {}).get("version", {}).get("json", {})
    act_browser = actual.get("browser", {}).get("version", {}).get("json", {})
    for key in ("Browser", "Protocol-Version"):
        if exp_browser.get(key) and exp_browser.get(key) != act_browser.get(key):
            failures.append(f"browser.{key}: expected {exp_browser.get(key)!r}, got {act_browser.get(key)!r}")
    if expected.get("adb", {}).get("devices", {}).get("ok") and not actual.get("adb", {}).get("devices", {}).get("ok"):
        failures.append("adb.devices: expected working ADB transport")
    if expected.get("browser", {}).get("version", {}).get("ok") and not actual.get("browser", {}).get("version", {}).get("ok"):
        failures.append("browser.version: expected reachable native Chrome CDP endpoint")
    return failures


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint", default=os.environ.get("APPLICATION_BROWSER_CDP_ENDPOINT", "http://127.0.0.1:9223"))
    p.add_argument("--output")
    p.add_argument("--compare")
    p.add_argument("--strict", action="store_true")
    args = p.parse_args()
    actual = capture(args.endpoint)
    text = json.dumps(actual, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    failures = []
    if args.compare:
        expected = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        failures = compare(actual, expected)
        for failure in failures:
            print(f"RUNTIME_TWIN_MISMATCH: {failure}", file=sys.stderr)
    hard = [
        not actual["host"]["android"],
        actual["host"]["machine"] not in {"aarch64", "arm64"},
        not actual["adb"]["devices"].get("ok"),
        not actual["browser"]["version"].get("ok"),
    ]
    if args.strict and (any(hard) or failures):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
