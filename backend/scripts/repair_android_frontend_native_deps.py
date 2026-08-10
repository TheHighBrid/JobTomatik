from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import tempfile
from urllib.request import Request, urlopen


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = REPO_ROOT / "frontend"
LOCK_FILE = FRONTEND_ROOT / "package-lock.json"


class FrontendNativeDependencyError(RuntimeError):
    pass


def _linux_libc_suffix() -> str:
    libc_name = (platform.libc_ver()[0] or "").lower()
    if "musl" in libc_name or Path("/etc/alpine-release").exists():
        return "musl"
    return "gnu"


def _lightningcss_package_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        libc = _linux_libc_suffix()
        if machine in {"x86_64", "amd64"}:
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
        if machine in {"x86_64", "amd64"}:
            return "lightningcss-darwin-x64"

    raise FrontendNativeDependencyError(
        f"Unsupported Lightning CSS runtime: system={system} machine={machine}"
    )


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


def _healthy_package(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "package.json").is_file()
        and any(path.rglob("*.node"))
    )


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


def _repair_entry(frontend_root: Path, lock_key: str, metadata: dict) -> str:
    destination = frontend_root / lock_key
    if _healthy_package(destination):
        return f"ANDROID_FRONTEND_NATIVE_DEP_READY path={lock_key} source=existing"

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
        if not _healthy_package(staged):
            raise FrontendNativeDependencyError(
                f"Downloaded package is incomplete: {lock_key}"
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
        f"path={lock_key} version={version} source=verified_lockfile_download"
    )


def repair_frontend_native_dependencies(
    frontend_root: Path = FRONTEND_ROOT,
    lock_file: Path = LOCK_FILE,
) -> list[str]:
    package_name = _lightningcss_package_name()
    try:
        lock = json.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrontendNativeDependencyError(
            f"Unable to read frontend package lock: {lock_file}"
        ) from exc

    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise FrontendNativeDependencyError("Frontend package lock has no packages map")

    suffix = f"node_modules/{package_name}"
    entries = [
        (str(key), value)
        for key, value in packages.items()
        if str(key).endswith(suffix) and isinstance(value, dict)
    ]
    if not entries:
        raise FrontendNativeDependencyError(
            f"Required native package is absent from package-lock.json: {package_name}"
        )

    messages = [
        _repair_entry(frontend_root, lock_key, metadata)
        for lock_key, metadata in entries
    ]
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
