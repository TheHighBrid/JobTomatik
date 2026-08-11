from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile

from scripts import repair_android_frontend_native_deps as native_deps


def _package_tarball(package_name: str, binary_name: str, payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        files = {
            "package/package.json": json.dumps(
                {"name": package_name, "version": "1.0.0"}
            ).encode(),
            f"package/{binary_name}": payload,
        }
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _integrity(payload: bytes) -> str:
    digest = hashlib.sha512(payload).digest()
    return "sha512-" + base64.b64encode(digest).decode("ascii")


def _android_fixture(tmp_path: Path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    package_name = "@rolldown/binding-android-arm64"
    binary_name = "rolldown-binding.android-arm64.node"
    expected_binary = b"verified-native-binary"
    tarball = _package_tarball(package_name, binary_name, expected_binary)
    url = "https://registry.example/rolldown.tgz"
    lock_file = frontend / "package-lock.json"
    lock_file.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "node_modules/@rolldown/binding-android-arm64": {
                        "version": "1.0.0",
                        "resolved": url,
                        "integrity": _integrity(tarball),
                        "optional": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    spec = native_deps.NativePackageSpec(package_name, binary_name)
    return frontend, lock_file, spec, url, tarball, expected_binary


def test_android_receipt_is_derived_from_sri_verified_download_and_reused(
    tmp_path,
    monkeypatch,
):
    frontend, lock_file, spec, url, tarball, expected_binary = _android_fixture(tmp_path)
    monkeypatch.setattr(native_deps, "_node_runtime", lambda: ("android", "arm64"))
    monkeypatch.setattr(native_deps, "_native_package_specs", lambda *_args: [spec])
    monkeypatch.setattr(
        native_deps,
        "_native_binding_loads",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("Android foreground repair must never dlopen native addons")
        ),
    )
    downloads: list[str] = []

    def download(requested: str) -> bytes:
        downloads.append(requested)
        assert requested == url
        return tarball

    monkeypatch.setattr(native_deps, "_download", download)
    messages = native_deps.repair_frontend_native_dependencies(frontend, lock_file)

    binary = frontend / "node_modules/@rolldown/binding-android-arm64" / spec.expected_binary
    assert binary.read_bytes() == expected_binary
    receipt_path = frontend / "node_modules" / native_deps.ANDROID_INTEGRITY_RECEIPT
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    record = receipt["entries"]["node_modules/@rolldown/binding-android-arm64"]
    assert record["package"] == spec.package_name
    assert record["version"] == "1.0.0"
    assert record["binary"] == spec.expected_binary
    assert record["binary_sha256"] == hashlib.sha256(expected_binary).hexdigest()
    assert len(downloads) == 1
    assert any("ANDROID_FRONTEND_NATIVE_INTEGRITY_RECEIPT_READY" in item for item in messages)

    monkeypatch.setattr(
        native_deps,
        "_download",
        lambda _url: (_ for _ in ()).throw(AssertionError("receipt-backed file should be reused")),
    )
    messages = native_deps.repair_frontend_native_dependencies(frontend, lock_file)
    assert any("source=existing_verified" in item for item in messages)


def test_corrupted_android_binary_is_replaced_from_verified_lockfile_package(
    tmp_path,
    monkeypatch,
):
    frontend, lock_file, spec, url, tarball, expected_binary = _android_fixture(tmp_path)
    monkeypatch.setattr(native_deps, "_node_runtime", lambda: ("android", "arm64"))
    monkeypatch.setattr(native_deps, "_native_package_specs", lambda *_args: [spec])
    monkeypatch.setattr(
        native_deps,
        "_native_binding_loads",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("Android foreground repair must never dlopen native addons")
        ),
    )
    monkeypatch.setattr(native_deps, "_download", lambda _url: tarball)
    native_deps.repair_frontend_native_dependencies(frontend, lock_file)

    binary = frontend / "node_modules/@rolldown/binding-android-arm64" / spec.expected_binary
    binary.write_bytes(b"corrupt-but-nonempty")

    downloads: list[str] = []

    def redownload(requested: str) -> bytes:
        downloads.append(requested)
        assert requested == url
        return tarball

    monkeypatch.setattr(native_deps, "_download", redownload)
    messages = native_deps.repair_frontend_native_dependencies(frontend, lock_file)

    assert binary.read_bytes() == expected_binary
    assert downloads == [url]
    assert any("source=verified_lockfile_download" in item for item in messages)


def test_missing_android_integrity_receipt_forces_verified_replacement(
    tmp_path,
    monkeypatch,
):
    frontend, lock_file, spec, url, tarball, expected_binary = _android_fixture(tmp_path)
    destination = frontend / "node_modules/@rolldown/binding-android-arm64"
    destination.mkdir(parents=True)
    (destination / "package.json").write_text(
        json.dumps({"name": spec.package_name, "version": "1.0.0"}),
        encoding="utf-8",
    )
    (destination / spec.expected_binary).write_bytes(expected_binary)

    monkeypatch.setattr(native_deps, "_node_runtime", lambda: ("android", "arm64"))
    monkeypatch.setattr(native_deps, "_native_package_specs", lambda *_args: [spec])
    downloads: list[str] = []

    def download(requested: str) -> bytes:
        downloads.append(requested)
        assert requested == url
        return tarball

    monkeypatch.setattr(native_deps, "_download", download)
    messages = native_deps.repair_frontend_native_dependencies(frontend, lock_file)

    assert downloads == [url]
    assert any("source=verified_lockfile_download" in item for item in messages)
