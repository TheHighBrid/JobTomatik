from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import Request, urlopen


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = REPO_ROOT / "frontend"
LOCK_FILE = FRONTEND_ROOT / "package-lock.json"
NODE_PLATFORM_OVERRIDE = "JOBTOMATIK_FRONTEND_NODE_PLATFORM"
NODE_ARCH_OVERRIDE = "JOBTOMATIK_FRONTEND_NODE_ARCH"


class FrontendNativeDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class NativePackageSpec:
    package_name: str
    expected_binary: str


def _linux_libc_suffix() -> str:
    libc_name = (platform.libc_ver()[0] or "").lower()
    if "musl" in libc_name or Path("/etc/alpine-release").exists():
        return "musl"
    return "gnu"


def _node_runtime() -> tuple[str, str]:
    platform_override = str(os.environ.get(NODE_PLATFORM_OVERRIDE) or "").strip().lower()
    arch_override = str(os.environ.get(NODE_ARCH_OVERRIDE) or "").strip().lower()
    if bool(platform_override) != bool(arch_override):
        raise FrontendNativeDependencyError(
            f"{NODE_PLATFORM_OVERRIDE} and {NODE_ARCH_OVERRIDE} must be set together"
        )
    if platform_override and arch_override:
        return platform_override, arch_override

    try:
        completed = subprocess.run(
            [
                "node",
                "-p",
                "JSON.stringify({platform:process.platform,arch:process.arch})",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        payload = json.loads(completed.stdout.strip())
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise FrontendNativeDependencyError(
            "Unable to resolve the frontend Node runtime platform and architecture"
        ) from exc

    node_platform = str(payload.get("platform") or "").strip().lower()
    node_arch = str(payload.get("arch") or "").strip().lower()
    if not node_platform or not node_arch:
        raise FrontendNativeDependencyError(
            "Node runtime did not report a platform and architecture"
        )
    return node_platform, node_arch


def _lightningcss_package_name(
    node_platform: str | None = None,
    node_arch: str | None = None,
) -> str:
    if node_platform is None and node_arch is None:
        node_platform, node_arch = _node_runtime()
    elif node_platform is None or node_arch is None:
        raise FrontendNativeDependencyError(
            "Lightning CSS target platform and architecture must be supplied together"
        )

    system = str(node_platform).lower()
    machine = str(node_arch).lower()

    if system == "android":
        if machine in {"aarch64", "arm64"}:
            return "lightningcss-android-arm64"
    elif system == "linux":
        libc = _linux_libc_suffix()
        if machine in {"x86_64", "x64", "amd64"}:
            return f"lightningcss-linux-x64-{libc}"
        if machine in {"aarch64", "arm64"}:
            return f"lightningcss-linux-arm64-{libc}"
        if machine.startswith("arm"):
            if libc == "musl":
                raise FrontendNativeDependencyError(
                    "Unsupported musl ARM Lightning CSS runtime"
                )
            return "lightningcss-linux-arm-gnueabihf"
    elif system == "darwin":
        if machine in {"aarch64", "arm64"}:
            return "lightningcss-darwin-arm64"
        if machine in {"x86_64", "x64", "amd64"}:
            return "lightningcss-darwin-x64"

    raise FrontendNativeDependencyError(
        f"Unsupported Lightning CSS Node runtime: platform={system} arch={machine}"
    )


def _expected_lightningcss_binary(package_name: str) -> str:
    suffix = package_name.removeprefix("lightningcss-")
    return f"lightningcss.{suffix}.node"


def _native_package_specs(node_platform: str, node_arch: str) -> list[NativePackageSpec]:
    lightningcss = _lightningcss_package_name(node_platform, node_arch)
    lightning_suffix = lightningcss.removeprefix("lightningcss-")
    specs = [
        NativePackageSpec(
            package_name=lightningcss,
            expected_binary=_expected_lightningcss_binary(lightningcss),
        )
    ]

    system = node_platform.lower()
    machine = node_arch.lower()
    if system == "android" and machine in {"aarch64", "arm64"}:
        specs.extend(
            [
                NativePackageSpec(
                    "@rolldown/binding-android-arm64",
                    "rolldown-binding.android-arm64.node",
                ),
                NativePackageSpec(
                    "@tailwindcss/oxide-android-arm64",
                    "tailwindcss-oxide.android-arm64.node",
                ),
            ]
        )
    elif system == "linux" and machine in {
        "x86_64",
        "x64",
        "amd64",
        "aarch64",
        "arm64",
    }:
        specs.extend(
            [
                NativePackageSpec(
                    f"@rolldown/binding-{lightning_suffix}",
                    f"rolldown-binding.{lightning_suffix}.node",
                ),
                NativePackageSpec(
                    f"@tailwindcss/oxide-{lightning_suffix}",
                    f"tailwindcss-oxide.{lightning_suffix}.node",
                ),
            ]
        )

    return specs


def _integrity_matches(payload: bytes, integrity: str) -> bool:
    for token in str(integrity or "").split():
        if "-" not in token:
            continue
        algorithm, encoded = token.split("-", 1)
        try:
            digest = hashlib.new(algorithm, payload).digest()
        except ValueError:
            continue
        if base64.b64encode(digest).decode("ascii") == encoded:
            return True
    return False


def _healthy_package(path: Path, spec: NativePackageSpec) -> bool:
    package_json = path / "package.json"
    if not path.is_dir() or not package_json.is_file():
        return False
    try:
        metadata = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if metadata.get("name") != spec.package_name:
        return False
    binary = path / spec.expected_binary
    try:
        return binary.is_file() and binary.stat().st_size > 0
    except OSError:
        return False


def _download(url: str) -> bytes:
    request = Request(
        url,
        headers={"User-Agent": "JobTomatik-Android-native-dependency-repair/1"},
    )
    with urlopen(request, timeout=45) as response:
        return response.read()


def _safe_extract_package(payload: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            raw_name = member.name.replace("\\", "/")
            if not raw_name.startswith("package/"):
                continue
            relative = raw_name.removeprefix("package/")
            if not relative:
                continue
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise FrontendNativeDependencyError(
                    f"Unsafe package archive path: {raw_name}"
                )
            target = destination / relative_path
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise FrontendNativeDependencyError(
                    f"Unsupported package archive member: {raw_name}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise FrontendNativeDependencyError(
                    f"Unable to extract package archive member: {raw_name}"
                )
            with source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            os.chmod(target, member.mode & 0o777)


def _repair_entry(
    frontend_root: Path,
    lock_key: str,
    metadata: dict,
    spec: NativePackageSpec,
) -> str:
    destination = frontend_root / lock_key
    if _healthy_package(destination, spec):
        return (
            "ANDROID_FRONTEND_NATIVE_DEP_READY "
            f"package={spec.package_name} path={lock_key} "
            f"native={spec.expected_binary} source=existing"
        )

    resolved = str(metadata.get("resolved") or "")
    integrity = str(metadata.get("integrity") or "")
    version = str(metadata.get("version") or "unknown")
    if not resolved.startswith("https://") or not integrity:
        raise FrontendNativeDependencyError(
            f"Lockfile entry lacks verified package source: {lock_key}"
        )

    payload = _download(resolved)
    if not _integrity_matches(payload, integrity):
        raise FrontendNativeDependencyError(
            f"Integrity verification failed for {lock_key}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}.repair-",
        dir=str(destination.parent),
    ) as temporary:
        staged = Path(temporary) / "package"
        _safe_extract_package(payload, staged)
        if not _healthy_package(staged, spec):
            raise FrontendNativeDependencyError(
                f"Downloaded package is incomplete or wrong-target: {lock_key} "
                f"expected={spec.expected_binary}"
            )

        backup = destination.with_name(f".{destination.name}.broken-{os.getpid()}")
        if backup.exists():
            shutil.rmtree(backup)
        if destination.exists():
            os.replace(destination, backup)
        try:
            os.replace(staged, destination)
        except Exception:
            if backup.exists() and not destination.exists():
                os.replace(backup, destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)

    return (
        "ANDROID_FRONTEND_NATIVE_DEP_READY "
        f"package={spec.package_name} path={lock_key} version={version} "
        f"native={spec.expected_binary} source=verified_lockfile_download"
    )


def repair_frontend_native_dependencies(
    frontend_root: Path = FRONTEND_ROOT,
    lock_file: Path = LOCK_FILE,
) -> list[str]:
    node_platform, node_arch = _node_runtime()
    specs = _native_package_specs(node_platform, node_arch)
    try:
        lock = json.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrontendNativeDependencyError(
            f"Unable to read frontend package lock: {lock_file}"
        ) from exc

    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise FrontendNativeDependencyError("Frontend package lock has no packages map")

    messages: list[str] = []
    for spec in specs:
        suffix = f"node_modules/{spec.package_name}"
        entries = [
            (str(key), value)
            for key, value in packages.items()
            if str(key).endswith(suffix) and isinstance(value, dict)
        ]
        if not entries:
            raise FrontendNativeDependencyError(
                f"Required native package is absent from package-lock.json: {spec.package_name}"
            )
        messages.extend(
            _repair_entry(frontend_root, lock_key, metadata, spec)
            for lock_key, metadata in entries
        )

    messages.append(
        "ANDROID_FRONTEND_NODE_TARGET "
        f"platform={node_platform} arch={node_arch} "
        f"packages={','.join(spec.package_name for spec in specs)}"
    )
    return messages


def main() -> int:
    try:
        messages = repair_frontend_native_dependencies()
    except FrontendNativeDependencyError as exc:
        print(f"ANDROID_FRONTEND_NATIVE_DEP_FAILED detail={exc}", file=sys.stderr)
        return 1

    for message in messages:
        print(message)
    print("ANDROID_FRONTEND_NATIVE_DEPENDENCIES_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
