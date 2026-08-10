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
    package_name: str,
    binary_name: str,
    *,
    version: str = "1.0.0",
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        files = {
            "package/package.json": json.dumps(
                {"name": package_name, "version": version}
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


def test_android_arm64_selects_complete_native_toolchain_with_exact_binaries():
    specs = native_deps._native_package_specs("android", "arm64")
    assert [(spec.package_name, spec.expected_binary) for spec in specs] == [
        ("lightningcss-android-arm64", "lightningcss.android-arm64.node"),
        ("@rolldown/binding-android-arm64", "rolldown-binding.android-arm64.node"),
        ("@tailwindcss/oxide-android-arm64", "tailwindcss-oxide.android-arm64.node"),
    ]


def test_linux_32bit_arm_selects_complete_native_toolchain(monkeypatch):
    monkeypatch.setattr(native_deps, "_linux_libc_suffix", lambda: "gnu")
    specs = native_deps._native_package_specs("linux", "arm")
    assert [(spec.package_name, spec.expected_binary) for spec in specs] == [
        (
            "lightningcss-linux-arm-gnueabihf",
            "lightningcss.linux-arm-gnueabihf.node",
        ),
        (
            "@rolldown/binding-linux-arm-gnueabihf",
            "rolldown-binding.linux-arm-gnueabihf.node",
        ),
        (
            "@tailwindcss/oxide-linux-arm-gnueabihf",
            "tailwindcss-oxide.linux-arm-gnueabihf.node",
        ),
    ]


def test_darwin_arm64_selects_complete_native_toolchain():
    specs = native_deps._native_package_specs("darwin", "arm64")
    assert [(spec.package_name, spec.expected_binary) for spec in specs] == [
        ("lightningcss-darwin-arm64", "lightningcss.darwin-arm64.node"),
        ("@rolldown/binding-darwin-arm64", "rolldown-binding.darwin-arm64.node"),
        ("@tailwindcss/oxide-darwin-arm64", "tailwindcss-oxide.darwin-arm64.node"),
    ]


def test_cross_target_override_disables_direct_native_load_probe(monkeypatch):
    monkeypatch.setenv(native_deps.NODE_PLATFORM_OVERRIDE, "android")
    monkeypatch.setenv(native_deps.NODE_ARCH_OVERRIDE, "arm64")
    monkeypatch.setattr(native_deps, "_query_node_runtime", lambda: ("linux", "arm64"))

    assert native_deps._node_runtime() == ("android", "arm64")
    assert native_deps._can_execute_target("android", "arm64") is False


def test_repair_restores_complete_android_native_toolchain_without_npm_install(
    tmp_path,
    monkeypatch,
):
    frontend = tmp_path / "frontend"
    frontend.mkdir()

    lightning_payload = _package_tarball(
        "lightningcss-android-arm64",
        "lightningcss.android-arm64.node",
    )
    rolldown_payload = _package_tarball(
        "@rolldown/binding-android-arm64",
        "rolldown-binding.android-arm64.node",
    )
    oxide_payload = _package_tarball(
        "@tailwindcss/oxide-android-arm64",
        "tailwindcss-oxide.android-arm64.node",
    )
    payloads = {
        "https://registry.example/lightningcss.tgz": lightning_payload,
        "https://registry.example/rolldown.tgz": rolldown_payload,
        "https://registry.example/oxide.tgz": oxide_payload,
    }

    def metadata(url: str, payload: bytes) -> dict:
        return {
            "version": "1.0.0",
            "resolved": url,
            "integrity": _integrity(payload),
            "optional": True,
        }

    lock = {
        "lockfileVersion": 3,
        "packages": {
            "node_modules/lightningcss-android-arm64": metadata(
                "https://registry.example/lightningcss.tgz", lightning_payload
            ),
            "node_modules/vite/node_modules/lightningcss-android-arm64": metadata(
                "https://registry.example/lightningcss.tgz", lightning_payload
            ),
            "node_modules/@rolldown/binding-android-arm64": metadata(
                "https://registry.example/rolldown.tgz", rolldown_payload
            ),
            "node_modules/@tailwindcss/oxide-android-arm64": metadata(
                "https://registry.example/oxide.tgz", oxide_payload
            ),
        },
    }
    lock_file = frontend / "package-lock.json"
    lock_file.write_text(json.dumps(lock), encoding="utf-8")

    monkeypatch.setattr(native_deps, "_node_runtime", lambda: ("android", "arm64"))
    monkeypatch.setattr(native_deps, "_can_execute_target", lambda *_args: False)
    downloads: list[str] = []

    def fake_download(url: str) -> bytes:
        downloads.append(url)
        return payloads[url]

    monkeypatch.setattr(native_deps, "_download", fake_download)

    messages = native_deps.repair_frontend_native_dependencies(
        frontend_root=frontend,
        lock_file=lock_file,
    )

    expected_files = [
        frontend
        / "node_modules/lightningcss-android-arm64/lightningcss.android-arm64.node",
        frontend
        / "node_modules/vite/node_modules/lightningcss-android-arm64/lightningcss.android-arm64.node",
        frontend
        / "node_modules/@rolldown/binding-android-arm64/rolldown-binding.android-arm64.node",
        frontend
        / "node_modules/@tailwindcss/oxide-android-arm64/tailwindcss-oxide.android-arm64.node",
    ]
    for binary in expected_files:
        assert binary.is_file()
        assert binary.stat().st_size > 0
        package_metadata = json.loads(
            (binary.parent / "package.json").read_text(encoding="utf-8")
        )
        assert package_metadata["version"] == "1.0.0"

    assert downloads.count("https://registry.example/lightningcss.tgz") == 2
    assert downloads.count("https://registry.example/rolldown.tgz") == 1
    assert downloads.count("https://registry.example/oxide.tgz") == 1
    assert sum("source=verified_lockfile_download" in item for item in messages) == 4
    assert any(
        "platform=android arch=arm64" in item
        and "native_load_validation=cross_target_skipped" in item
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
    assert sum("source=existing_verified" in item for item in messages) == 4


def test_native_load_probe_controls_existing_package_health(tmp_path, monkeypatch):
    destination = tmp_path / "binding"
    destination.mkdir()
    (destination / "package.json").write_text(
        json.dumps(
            {
                "name": "@rolldown/binding-android-arm64",
                "version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    (destination / "rolldown-binding.android-arm64.node").write_bytes(b"nonempty")
    spec = native_deps.NativePackageSpec(
        "@rolldown/binding-android-arm64",
        "rolldown-binding.android-arm64.node",
    )

    monkeypatch.setattr(native_deps, "_native_binding_loads", lambda _path: False)
    assert (
        native_deps._healthy_package(
            destination,
            spec,
            "1.0.0",
            validate_native_load=True,
        )
        is False
    )

    monkeypatch.setattr(native_deps, "_native_binding_loads", lambda _path: True)
    assert native_deps._healthy_package(
        destination,
        spec,
        "1.0.0",
        validate_native_load=True,
    )


def test_stale_native_package_version_is_repaired_from_locked_version(
    tmp_path,
    monkeypatch,
):
    frontend = tmp_path / "frontend"
    destination = frontend / "node_modules/@rolldown/binding-android-arm64"
    destination.mkdir(parents=True)
    (destination / "package.json").write_text(
        json.dumps(
            {
                "name": "@rolldown/binding-android-arm64",
                "version": "0.9.0",
            }
        ),
        encoding="utf-8",
    )
    (destination / "rolldown-binding.android-arm64.node").write_bytes(b"old-binding")

    payload = _package_tarball(
        "@rolldown/binding-android-arm64",
        "rolldown-binding.android-arm64.node",
        version="1.0.0",
    )
    lock_file = frontend / "package-lock.json"
    lock_file.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "node_modules/@rolldown/binding-android-arm64": {
                        "version": "1.0.0",
                        "resolved": "https://registry.example/rolldown.tgz",
                        "integrity": _integrity(payload),
                        "optional": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    spec = native_deps.NativePackageSpec(
        "@rolldown/binding-android-arm64",
        "rolldown-binding.android-arm64.node",
    )
    monkeypatch.setattr(native_deps, "_node_runtime", lambda: ("android", "arm64"))
    monkeypatch.setattr(native_deps, "_native_package_specs", lambda *_args: [spec])
    monkeypatch.setattr(native_deps, "_can_execute_target", lambda *_args: False)
    monkeypatch.setattr(native_deps, "_download", lambda _url: payload)

    messages = native_deps.repair_frontend_native_dependencies(
        frontend_root=frontend,
        lock_file=lock_file,
    )

    repaired_metadata = json.loads(
        (destination / "package.json").read_text(encoding="utf-8")
    )
    assert repaired_metadata["version"] == "1.0.0"
    assert "source=verified_lockfile_download" in messages[0]


@pytest.mark.parametrize(
    ("package_name", "expected_binary", "wrong_binary"),
    [
        (
            "lightningcss-android-arm64",
            "lightningcss.android-arm64.node",
            "lightningcss.linux-arm64-gnu.node",
        ),
        (
            "@rolldown/binding-android-arm64",
            "rolldown-binding.android-arm64.node",
            "rolldown-binding.linux-arm64-gnu.node",
        ),
        (
            "@tailwindcss/oxide-android-arm64",
            "tailwindcss-oxide.android-arm64.node",
            "tailwindcss-oxide.linux-arm64-gnu.node",
        ),
    ],
)
def test_wrong_target_native_file_is_not_considered_healthy(
    tmp_path,
    package_name,
    expected_binary,
    wrong_binary,
):
    destination = tmp_path / package_name.replace("/", "-")
    destination.mkdir()
    (destination / "package.json").write_text(
        json.dumps({"name": package_name, "version": "1.0.0"}),
        encoding="utf-8",
    )
    (destination / wrong_binary).write_bytes(b"wrong-target")

    spec = native_deps.NativePackageSpec(package_name, expected_binary)
    assert (
        native_deps._healthy_package(
            destination,
            spec,
            "1.0.0",
            validate_native_load=False,
        )
        is False
    )


@pytest.mark.parametrize(
    ("package_name", "expected_binary"),
    [
        ("lightningcss-android-arm64", "lightningcss.android-arm64.node"),
        ("@rolldown/binding-android-arm64", "rolldown-binding.android-arm64.node"),
        ("@tailwindcss/oxide-android-arm64", "tailwindcss-oxide.android-arm64.node"),
    ],
)
def test_zero_length_expected_native_file_is_not_considered_healthy(
    tmp_path,
    package_name,
    expected_binary,
):
    destination = tmp_path / package_name.replace("/", "-")
    destination.mkdir()
    (destination / "package.json").write_text(
        json.dumps({"name": package_name, "version": "1.0.0"}),
        encoding="utf-8",
    )
    (destination / expected_binary).write_bytes(b"")

    spec = native_deps.NativePackageSpec(package_name, expected_binary)
    assert (
        native_deps._healthy_package(
            destination,
            spec,
            "1.0.0",
            validate_native_load=False,
        )
        is False
    )


@pytest.mark.parametrize(
    "package_json_payload",
    [
        b"\xff\xfe\xfd",
        b"null",
        b"[1,2,3]",
        b"{broken-json",
    ],
)
def test_malformed_package_metadata_is_unhealthy_not_exception(
    tmp_path,
    package_json_payload,
):
    destination = tmp_path / "binding"
    destination.mkdir()
    (destination / "package.json").write_bytes(package_json_payload)
    (destination / "rolldown-binding.android-arm64.node").write_bytes(b"binding")
    spec = native_deps.NativePackageSpec(
        "@rolldown/binding-android-arm64",
        "rolldown-binding.android-arm64.node",
    )

    assert (
        native_deps._healthy_package(
            destination,
            spec,
            "1.0.0",
            validate_native_load=False,
        )
        is False
    )


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
    monkeypatch.setattr(
        native_deps,
        "_native_package_specs",
        lambda _platform, _arch: [
            native_deps.NativePackageSpec(
                "lightningcss-android-arm64",
                "lightningcss.android-arm64.node",
            )
        ],
    )
    monkeypatch.setattr(native_deps, "_can_execute_target", lambda *_args: False)
    monkeypatch.setattr(native_deps, "_download", lambda _url: b"tampered")

    with pytest.raises(
        native_deps.FrontendNativeDependencyError,
        match="Integrity verification failed",
    ):
        native_deps.repair_frontend_native_dependencies(
            frontend_root=frontend,
            lock_file=lock_file,
        )


def test_android_launcher_repairs_and_smoke_tests_full_native_toolchain():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    assert "ensure_frontend_native_dependencies()" in wrapper
    assert "repair_android_frontend_native_deps.py" in wrapper
    assert "require('lightningcss')" in wrapper
    assert "require('rolldown')" in wrapper
    assert "require('@tailwindcss/oxide')" in wrapper
    assert "ANDROID_FRONTEND_NATIVE_TOOLCHAIN_READY" in wrapper

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
