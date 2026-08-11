from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile

from scripts import repair_android_frontend_native_deps as native_repair
from scripts import stage_android_frontend_native_bindings as linker_stage


def _integrity(payload: bytes) -> str:
    digest = hashlib.sha512(payload).digest()
    return "sha512-" + base64.b64encode(digest).decode("ascii")


def _tarball(package: str, version: str, binary: str, binary_payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        files = {
            "package/package.json": json.dumps(
                {"name": package, "version": version}
            ).encode(),
            f"package/{binary}": binary_payload,
        }
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _write_receipt(
    frontend: Path,
    lock_key: str,
    package: str,
    version: str,
    binary: str,
    binary_payload: bytes,
) -> None:
    receipt = frontend / "node_modules/.jobtomatik-android-native-integrity.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    lock_key: {
                        "package": package,
                        "version": version,
                        "binary": binary,
                        "lock_integrity": "sha512-test-lock-integrity",
                        "binary_sha256": hashlib.sha256(binary_payload).hexdigest(),
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _write_package(
    destination: Path,
    package: str,
    version: str,
    binary: str,
    binary_payload: bytes,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "package.json").write_text(
        json.dumps({"name": package, "version": version}),
        encoding="utf-8",
    )
    (destination / binary).write_bytes(binary_payload)


def test_real_repair_handles_corrupted_staged_package_symlink(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    stage_root = tmp_path / "termux-prefix/var/lib/jobtomatik/frontend-native"
    lock_key = "node_modules/@rolldown/binding-android-arm64"
    package = "@rolldown/binding-android-arm64"
    version = "1.2.1"
    binary = "rolldown-binding.android-arm64.node"
    binary_payload = b"verified-native-binding"
    archive = _tarball(package, version, binary, binary_payload)
    resolved_url = "https://registry.example/rolldown.tgz"
    lock_file = frontend / "package-lock.json"
    lock_file.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    lock_key: {
                        "version": version,
                        "resolved": resolved_url,
                        "integrity": _integrity(archive),
                        "optional": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    spec = native_repair.NativePackageSpec(package, binary)
    monkeypatch.setattr(native_repair, "_node_runtime", lambda: ("android", "arm64"))
    monkeypatch.setattr(native_repair, "_native_package_specs", lambda *_args: [spec])
    downloads: list[str] = []

    def download(url: str) -> bytes:
        downloads.append(url)
        return archive

    monkeypatch.setattr(native_repair, "_download", download)

    native_repair.repair_frontend_native_dependencies(
        frontend_root=frontend,
        lock_file=lock_file,
    )
    destination = frontend / lock_key
    linker_stage.stage_android_native_bindings(
        frontend_root=frontend,
        stage_root=stage_root,
    )
    assert destination.is_symlink()

    staged_package = destination.resolve(strict=True)
    (staged_package / binary).write_bytes(b"damaged-native-binding")

    messages = native_repair.repair_frontend_native_dependencies(
        frontend_root=frontend,
        lock_file=lock_file,
    )

    assert not destination.is_symlink()
    assert (destination / binary).read_bytes() == binary_payload
    assert downloads == [resolved_url, resolved_url]
    assert any("source=verified_lockfile_download" in item for item in messages)

    linker_stage.stage_android_native_bindings(
        frontend_root=frontend,
        stage_root=stage_root,
    )
    assert destination.is_symlink()
    assert (destination.resolve(strict=True) / binary).read_bytes() == binary_payload


def test_successful_stage_prunes_obsolete_containers(tmp_path):
    frontend = tmp_path / "frontend"
    stage_root = tmp_path / "termux-prefix/var/lib/jobtomatik/frontend-native"
    lock_key = "node_modules/lightningcss-android-arm64"
    package = "lightningcss-android-arm64"
    version = "1.32.0"
    binary = "lightningcss.android-arm64.node"
    binary_payload = b"verified-lightningcss-binding"
    destination = frontend / lock_key

    _write_package(destination, package, version, binary, binary_payload)
    _write_receipt(frontend, lock_key, package, version, binary, binary_payload)

    obsolete = stage_root / "obsolete-content-addressed-container"
    obsolete.mkdir(parents=True)
    (obsolete / "unused.node").write_bytes(b"unused")

    messages = linker_stage.stage_android_native_bindings(
        frontend_root=frontend,
        stage_root=stage_root,
    )

    assert not obsolete.exists()
    assert any(
        "ANDROID_FRONTEND_NATIVE_LINKER_STAGE_PRUNED" in item and "removed=1" in item
        for item in messages
    )
    assert destination.is_symlink()
