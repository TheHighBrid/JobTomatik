from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import stage_android_frontend_native_bindings as linker_stage


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_package(
    destination: Path,
    *,
    package: str,
    version: str,
    binary: str,
    payload: bytes,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "package.json").write_text(
        json.dumps({"name": package, "version": version}),
        encoding="utf-8",
    )
    (destination / binary).write_bytes(payload)


def _write_receipt(
    frontend: Path,
    *,
    lock_key: str,
    package: str,
    version: str,
    binary: str,
    payload: bytes,
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
                        "binary_sha256": _sha256(payload),
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_android_native_package_is_linked_into_runtime_stage(tmp_path):
    frontend = tmp_path / "frontend"
    stage_root = tmp_path / "termux-prefix/var/lib/jobtomatik/frontend-native"
    lock_key = "node_modules/lightningcss-android-arm64"
    package = "lightningcss-android-arm64"
    version = "1.32.0"
    binary = "lightningcss.android-arm64.node"
    payload = b"verified-android-native-binding"
    destination = frontend / lock_key

    _write_package(
        destination,
        package=package,
        version=version,
        binary=binary,
        payload=payload,
    )
    _write_receipt(
        frontend,
        lock_key=lock_key,
        package=package,
        version=version,
        binary=binary,
        payload=payload,
    )

    messages = linker_stage.stage_android_native_bindings(
        frontend_root=frontend,
        stage_root=stage_root,
    )

    assert destination.is_symlink()
    resolved = destination.resolve(strict=True)
    resolved.relative_to(stage_root.resolve())
    assert (resolved / binary).read_bytes() == payload
    assert any("ANDROID_FRONTEND_NATIVE_LINKER_STAGE_READY" in item for item in messages)
    assert any("entries=1" in item for item in messages)

    messages = linker_stage.stage_android_native_bindings(
        frontend_root=frontend,
        stage_root=stage_root,
    )
    assert destination.is_symlink()
    assert destination.resolve(strict=True) == resolved
    assert any("ANDROID_FRONTEND_NATIVE_LINKER_STAGE_READY" in item for item in messages)


def test_corrupt_staged_binary_is_replaced_from_fresh_repaired_source(tmp_path):
    frontend = tmp_path / "frontend"
    stage_root = tmp_path / "termux-prefix/var/lib/jobtomatik/frontend-native"
    lock_key = "node_modules/@rolldown/binding-android-arm64"
    package = "@rolldown/binding-android-arm64"
    version = "1.2.1"
    binary = "rolldown-binding.android-arm64.node"
    payload = b"verified-rolldown-native-binding"
    destination = frontend / lock_key

    _write_package(
        destination,
        package=package,
        version=version,
        binary=binary,
        payload=payload,
    )
    _write_receipt(
        frontend,
        lock_key=lock_key,
        package=package,
        version=version,
        binary=binary,
        payload=payload,
    )
    linker_stage.stage_android_native_bindings(
        frontend_root=frontend,
        stage_root=stage_root,
    )

    staged_package = destination.resolve(strict=True)
    (staged_package / binary).write_bytes(b"corrupt-but-nonempty")

    # Legacy compatibility only: if this quarantined bridge is ever invoked manually,
    # it must retain its existing integrity behavior even though canonical Android V2
    # startup no longer calls it.
    destination.unlink()
    _write_package(
        destination,
        package=package,
        version=version,
        binary=binary,
        payload=payload,
    )

    linker_stage.stage_android_native_bindings(
        frontend_root=frontend,
        stage_root=stage_root,
    )

    assert destination.is_symlink()
    recovered = destination.resolve(strict=True) / binary
    assert recovered.read_bytes() == payload
    assert _sha256(recovered.read_bytes()) == _sha256(payload)


def test_unsafe_receipt_path_is_rejected(tmp_path):
    frontend = tmp_path / "frontend"
    stage_root = tmp_path / "stage"
    receipt = frontend / "node_modules/.jobtomatik-android-native-integrity.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "../escape": {
                        "package": "lightningcss-android-arm64",
                        "version": "1.32.0",
                        "binary": "lightningcss.android-arm64.node",
                        "lock_integrity": "sha512-test",
                        "binary_sha256": "0" * 64,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(linker_stage.AndroidNativeStageError, match="Unsafe lockfile"):
        linker_stage.stage_android_native_bindings(
            frontend_root=frontend,
            stage_root=stage_root,
        )


def test_android_launcher_quarantines_native_staging_from_canonical_runtime():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    # The bridge remains unit-tested for rollback/forensics, but Architecture V2 must
    # never call it from normal start/restart/update/qualify execution.
    assert "repair_android_frontend_native_deps.py" not in wrapper
    assert "stage_android_frontend_native_bindings.py" not in wrapper
    assert "ensure_frontend_native_dependencies" not in wrapper
    assert "npm run dev" not in wrapper
    assert "npm run dev" not in manager
    assert "install_android_static_frontend_artifact.py" in wrapper
    assert "serve_static_frontend.py" in manager

    activate = wrapper.split("activate_stack() {", 1)[1].split("\n}", 1)[0]
    artifact_index = activate.index("ensure_static_frontend_artifact")
    browser_index = activate.index('"$BROWSER_COMMAND" start')
    detached_index = activate.index('start_stack_detached "$action"')
    acceptance_index = activate.index("run_runtime_acceptance")
    assert artifact_index < browser_index < detached_index < acceptance_index
