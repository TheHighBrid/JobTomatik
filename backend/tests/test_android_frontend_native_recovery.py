from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from scripts import repair_android_frontend_native_deps as native_deps


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _package_tarball() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        files = {
            "package/package.json": b'{"name":"lightningcss-linux-x64-gnu","version":"1.0.0"}',
            "package/lightningcss.linux-x64-gnu.node": b"native-binding",
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


def test_repair_restores_missing_locked_native_binding_without_npm_install(
    tmp_path,
    monkeypatch,
):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    payload = _package_tarball()
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "node_modules/lightningcss-linux-x64-gnu": {
                "version": "1.0.0",
                "resolved": "https://registry.example/lightningcss.tgz",
                "integrity": _integrity(payload),
                "optional": True,
            }
        },
    }
    lock_file = frontend / "package-lock.json"
    lock_file.write_text(json.dumps(lock), encoding="utf-8")

    monkeypatch.setattr(
        native_deps,
        "_lightningcss_package_name",
        lambda: "lightningcss-linux-x64-gnu",
    )
    downloads = []

    def fake_download(url: str) -> bytes:
        downloads.append(url)
        return payload

    monkeypatch.setattr(native_deps, "_download", fake_download)

    messages = native_deps.repair_frontend_native_dependencies(
        frontend_root=frontend,
        lock_file=lock_file,
    )

    restored = frontend / "node_modules/lightningcss-linux-x64-gnu"
    assert (restored / "package.json").is_file()
    assert (restored / "lightningcss.linux-x64-gnu.node").is_file()
    assert downloads == ["https://registry.example/lightningcss.tgz"]
    assert "source=verified_lockfile_download" in messages[0]

    monkeypatch.setattr(
        native_deps,
        "_download",
        lambda _url: (_ for _ in ()).throw(AssertionError("unexpected download")),
    )
    messages = native_deps.repair_frontend_native_dependencies(
        frontend_root=frontend,
        lock_file=lock_file,
    )
    assert "source=existing" in messages[0]


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
                    "node_modules/lightningcss-linux-x64-gnu": {
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

    monkeypatch.setattr(
        native_deps,
        "_lightningcss_package_name",
        lambda: "lightningcss-linux-x64-gnu",
    )
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
