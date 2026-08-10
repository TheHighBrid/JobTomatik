from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

from scripts import repair_android_frontend_native_deps as native_deps


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _package_tarball(
    package_name: str = "lightningcss-android-arm64",
    binary_name: str = "lightningcss.android-arm64.node",
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        files = {
            "package/package.json": json.dumps(
                {"name": package_name, "version": "1.0.0"}
            ).encode(),
            f"package/{binary_name}": b"native-binding",
        }
        for name, payload in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _integrity(payload: bytes) -> str:
    digest = hashlib.sha512(payload).digest()
    return "sha512-" + base64.b64encode(digest).decode("ascii")


def test_node_runtime_uses_node_platform_not_python_host(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["node"],
            returncode=0,
            stdout='{"platform":"android","arch":"arm64"}\n',
            stderr="",
        )

    monkeypatch.delenv(native_deps.NODE_PLATFORM_OVERRIDE, raising=False)
    monkeypatch.delenv(native_deps.NODE_ARCH_OVERRIDE, raising=False)
    monkeypatch.setattr(native_deps.subprocess, "run", fake_run)

    assert native_deps._node_runtime() == ("android", "arm64")
    assert native_deps._lightningcss_package_name() == "lightningcss-android-arm64"


def test_android_arm64_selects_android_binding_and_exact_binary():
    package = native_deps._lightningcss_package_name("android", "arm64")
    assert package == "lightningcss-android-arm64"
    assert (
        native_deps._expected_native_binary(package)
        == "lightningcss.android-arm64.node"
    )


def test_repair_restores_all_android_locked_bindings_without_npm_install(
    tmp_path,
    monkeypatch,
):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    payload = _package_tarball()
    metadata = {
        "version": "1.0.0",
        "resolved": "https://registry.example/lightningcss-android-arm64.tgz",
        "integrity": _integrity(payload),
        "optional": True,
    }
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "node_modules/lightningcss-android-arm64": dict(metadata),
            "node_modules/vite/node_modules/lightningcss-android-arm64": dict(metadata),
        },
    }
    lock_file = frontend / "package-lock.json"
    lock_file.write_text(json.dumps(lock), encoding="utf-8")

    monkeypatch.setattr(native_deps, "_node_runtime", lambda: ("android", "arm64"))
    downloads = []

    def fake_download(url: str) -> bytes:
        downloads.append(url)
        return payload

    monkeypatch.setattr(native_deps, "_download", fake_download)

    messages = native_deps.repair_frontend_native_dependencies(
        frontend_root=frontend,
        lock_file=lock_file,
    )

    for key in lock["packages"]:
        restored = frontend / key
        assert (restored / "package.json").is_file()
        assert (restored / "lightningcss.android-arm64.node").is_file()
    assert downloads == [metadata["resolved"], metadata["resolved"]]
    assert sum("source=verified_lockfile_download" in item for item in messages) == 2
    assert any(
        "platform=android arch=arm64 package=lightningcss-android-arm64" in item
        for item in messages
    )

    monkeypatch.setattr(
        native_deps,
        "_download",
        lambda _url: (_ for _ in ()).throw(AssertionError("unexpected download")),
    )
    messages = native_deps.repair_frontend_native_dependencies(
        frontend_root=frontend,
        lock_file=lock_file,
    )
    assert sum("source=existing" in item for item in messages) == 2


def test_wrong_target_node_file_is_not_considered_healthy(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    destination = frontend / "node_modules/lightningcss-android-arm64"
    destination.mkdir(parents=True)
    (destination / "package.json").write_text(
        json.dumps({"name": "lightningcss-android-arm64", "version": "1.0.0"}),
        encoding="utf-8",
    )
    (destination / "lightningcss.linux-arm64-gnu.node").write_bytes(b"wrong-target")

    payload = _package_tarball()
    lock_file = frontend / "package-lock.json"
    lock_file.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "node_modules/lightningcss-android-arm64": {
                        "version": "1.0.0",
                        "resolved": "https://registry.example/android.tgz",
                        "integrity": _integrity(payload),
                        "optional": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(native_deps, "_node_runtime", lambda: ("android", "arm64"))
    monkeypatch.setattr(native_deps, "_download", lambda _url: payload)

    messages = native_deps.repair_frontend_native_dependencies(
        frontend_root=frontend,
        lock_file=lock_file,
    )

    assert (destination / "lightningcss.android-arm64.node").is_file()
    assert "source=verified_lockfile_download" in messages[0]


def test_repair_rejects_payload_that_does_not_match_lockfile_integrity(
    tmp_path,
    monkeypatch,
):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    lock_file = frontend / "package-lock.json"
    lock_file.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "node_modules/lightningcss-android-arm64": {
                        "version": "1.0.0",
                        "resolved": "https://registry.example/lightningcss.tgz",
                        "integrity": _integrity(b"expected-payload"),
                        "optional": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(native_deps, "_node_runtime", lambda: ("android", "arm64"))
    monkeypatch.setattr(native_deps, "_download", lambda _url: b"tampered")

    with pytest.raises(
        native_deps.FrontendNativeDependencyError,
        match="Integrity verification failed",
    ):
        native_deps.repair_frontend_native_dependencies(
            frontend_root=frontend,
            lock_file=lock_file,
        )


def test_android_launcher_repairs_native_binding_before_browser_and_stack_start():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    assert "ensure_frontend_native_dependencies()" in wrapper
    assert "repair_android_frontend_native_deps.py" in wrapper
    assert "require('lightningcss')" in wrapper

    activate = wrapper.split("activate_stack() {", 1)[1].split("\n}", 1)[0]
    repair_index = activate.index("ensure_frontend_native_dependencies")
    browser_index = activate.index('"$BROWSER_COMMAND" start')
    stack_index = activate.index('start_stack_detached "$action"')
    assert repair_index < browser_index < stack_index


def test_android_launcher_rejects_false_ready_and_retires_supervisor():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    detached = wrapper.split("start_stack_detached() {", 1)[1].split(
        "\n}\n\nstop_stack_supervisor()",
        1,
    )[0]
    assert "JOBTOMATIK_ANDROID_STACK_READY_REJECTED_FRONTEND_UNATTESTED" in detached
    assert 'reject_stack_supervisor "$proot_pid"' in detached
    assert "grep -v '^JOBTOMATIK_ANDROID_STACK_READY$'" in detached
    guard_index = detached.index("if ! run_frontend_guard status")
    success_tail_index = detached.index('tail -n 30 "$STACK_LOG"')
    assert guard_index < success_tail_index
