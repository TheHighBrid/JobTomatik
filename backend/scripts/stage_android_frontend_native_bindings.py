from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = REPO_ROOT / "frontend"
ANDROID_INTEGRITY_RECEIPT = ".jobtomatik-android-native-integrity.json"
ANDROID_INTEGRITY_RECEIPT_VERSION = 1
ANDROID_NATIVE_STAGE_ROOT_ENV = "JOBTOMATIK_ANDROID_NATIVE_STAGE_ROOT"
DEFAULT_ANDROID_NATIVE_STAGE_ROOT = Path(
    "/data/data/com.termux/files/usr/var/lib/jobtomatik/frontend-native"
)
ANDROID_NATIVE_STAGE_OWNER = ".jobtomatik-native-stage-owner.json"
ANDROID_NATIVE_STAGE_OWNER_VERSION = 1
ANDROID_NATIVE_STAGE_OWNER_NAME = "jobtomatik-android-frontend-native-stage"


class AndroidNativeStageError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _receipt_path(frontend_root: Path) -> Path:
    return frontend_root / "node_modules" / ANDROID_INTEGRITY_RECEIPT


def _load_receipt(frontend_root: Path) -> dict[str, dict]:
    path = _receipt_path(frontend_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AndroidNativeStageError(
            f"Android native integrity receipt is missing or unreadable: {path}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("version") != ANDROID_INTEGRITY_RECEIPT_VERSION:
        raise AndroidNativeStageError(
            f"Unsupported Android native integrity receipt: {path}"
        )
    entries = payload.get("entries")
    if not isinstance(entries, dict) or not entries:
        raise AndroidNativeStageError(
            f"Android native integrity receipt contains no package entries: {path}"
        )
    return entries


def _stage_root() -> Path:
    override = str(os.environ.get(ANDROID_NATIVE_STAGE_ROOT_ENV) or "").strip()
    root = Path(override) if override else DEFAULT_ANDROID_NATIVE_STAGE_ROOT
    if not root.is_absolute():
        raise AndroidNativeStageError(
            f"Android native stage root must be absolute: {root}"
        )
    if not override and not str(root).startswith("/data/"):
        raise AndroidNativeStageError(
            f"Default Android native stage root must remain under /data: {root}"
        )
    return root


def _stage_owner_path(stage_root: Path) -> Path:
    return stage_root / ANDROID_NATIVE_STAGE_OWNER


def _stage_owner_payload() -> dict[str, object]:
    return {
        "version": ANDROID_NATIVE_STAGE_OWNER_VERSION,
        "owner": ANDROID_NATIVE_STAGE_OWNER_NAME,
    }


def _stage_root_is_owned(stage_root: Path) -> bool:
    marker = _stage_owner_path(stage_root)
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return payload == _stage_owner_payload()


def _ensure_owned_stage_root(stage_root: Path) -> None:
    if os.path.lexists(stage_root) and not stage_root.is_dir():
        raise AndroidNativeStageError(
            f"Android native stage root is not a directory: {stage_root}"
        )
    if stage_root.is_dir() and _stage_root_is_owned(stage_root):
        return
    if stage_root.is_dir() and any(stage_root.iterdir()):
        raise AndroidNativeStageError(
            "Refusing to claim a non-empty Android native stage root without the "
            f"JobTomatik ownership marker: {stage_root}"
        )

    stage_root.mkdir(parents=True, exist_ok=True)
    marker = _stage_owner_path(stage_root)
    temporary = marker.with_name(f".{marker.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(_stage_owner_payload(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, marker)
    if not _stage_root_is_owned(stage_root):
        raise AndroidNativeStageError(
            f"Unable to establish Android native stage ownership: {stage_root}"
        )


def _safe_lock_destination(frontend_root: Path, lock_key: str) -> Path:
    relative = Path(lock_key)
    if relative.is_absolute() or ".." in relative.parts:
        raise AndroidNativeStageError(f"Unsafe lockfile package path: {lock_key}")
    if not relative.parts or relative.parts[0] != "node_modules":
        raise AndroidNativeStageError(
            f"Android native receipt path is outside node_modules: {lock_key}"
        )
    destination = frontend_root / relative
    node_modules = (frontend_root / "node_modules").resolve()
    parent = destination.parent.resolve()
    try:
        parent.relative_to(node_modules)
    except ValueError as exc:
        raise AndroidNativeStageError(
            f"Android native package destination escapes node_modules: {lock_key}"
        ) from exc
    return destination


def _record_fields(lock_key: str, record: dict) -> tuple[str, str, str, str, str]:
    package = str(record.get("package") or "").strip()
    version = str(record.get("version") or "").strip()
    binary = str(record.get("binary") or "").strip()
    lock_integrity = str(record.get("lock_integrity") or "").strip()
    binary_sha256 = str(record.get("binary_sha256") or "").strip().lower()
    if not package or not version or not binary or not lock_integrity:
        raise AndroidNativeStageError(
            f"Android native receipt entry is incomplete: {lock_key}"
        )
    binary_path = Path(binary)
    if binary_path.is_absolute() or len(binary_path.parts) != 1 or ".." in binary_path.parts:
        raise AndroidNativeStageError(
            f"Android native receipt has unsafe binary name: {lock_key} -> {binary}"
        )
    if len(binary_sha256) != 64 or any(char not in "0123456789abcdef" for char in binary_sha256):
        raise AndroidNativeStageError(
            f"Android native receipt has invalid binary digest: {lock_key}"
        )
    return package, version, binary, lock_integrity, binary_sha256


def _package_is_verified(
    package_dir: Path,
    *,
    package: str,
    version: str,
    binary: str,
    binary_sha256: str,
) -> bool:
    package_json = package_dir / "package.json"
    native_binary = package_dir / binary
    try:
        metadata = json.loads(package_json.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            return False
        if metadata.get("name") != package:
            return False
        if str(metadata.get("version") or "") != version:
            return False
        if not native_binary.is_file() or native_binary.stat().st_size <= 0:
            return False
        return _sha256_file(native_binary) == binary_sha256
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def _remove_path(path: Path) -> None:
    if os.path.lexists(path):
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)


def _stage_container_name(
    lock_key: str,
    package: str,
    version: str,
    lock_integrity: str,
    binary_sha256: str,
) -> str:
    label = package.replace("@", "").replace("/", "-").replace("_", "-")
    token = hashlib.sha256(
        "\0".join(
            [lock_key, package, version, lock_integrity, binary_sha256]
        ).encode("utf-8")
    ).hexdigest()[:20]
    return f"{label}-{version}-{token}"


def _ensure_staged_package(
    source: Path,
    stage_root: Path,
    *,
    lock_key: str,
    package: str,
    version: str,
    binary: str,
    lock_integrity: str,
    binary_sha256: str,
) -> Path:
    if not _package_is_verified(
        source,
        package=package,
        version=version,
        binary=binary,
        binary_sha256=binary_sha256,
    ):
        raise AndroidNativeStageError(
            f"Source Android native package does not match its SRI-backed receipt: {lock_key}"
        )

    container = stage_root / _stage_container_name(
        lock_key,
        package,
        version,
        lock_integrity,
        binary_sha256,
    )
    staged_package = container / "package"
    if _package_is_verified(
        staged_package,
        package=package,
        version=version,
        binary=binary,
        binary_sha256=binary_sha256,
    ):
        return staged_package

    temporary = stage_root / f".{container.name}.tmp-{os.getpid()}"
    backup = stage_root / f".{container.name}.broken-{os.getpid()}"
    _remove_path(temporary)
    _remove_path(backup)
    temporary_package = temporary / "package"
    try:
        shutil.copytree(source, temporary_package, symlinks=False)
        if not _package_is_verified(
            temporary_package,
            package=package,
            version=version,
            binary=binary,
            binary_sha256=binary_sha256,
        ):
            raise AndroidNativeStageError(
                f"Staged Android native package failed receipt verification: {lock_key}"
            )
        if os.path.lexists(container):
            os.replace(container, backup)
        try:
            os.replace(temporary, container)
        except Exception:
            if os.path.lexists(backup) and not os.path.lexists(container):
                os.replace(backup, container)
            raise
    finally:
        _remove_path(temporary)
        _remove_path(backup)

    return staged_package


def _link_package(destination: Path, staged_package: Path) -> None:
    staged_real = staged_package.resolve(strict=True)
    if destination.is_symlink():
        try:
            if destination.resolve(strict=True) == staged_real:
                return
        except OSError:
            pass

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.jobtomatik-link-{os.getpid()}")
    backup = destination.with_name(f".{destination.name}.jobtomatik-backup-{os.getpid()}")
    _remove_path(temporary)
    _remove_path(backup)
    os.symlink(str(staged_real), str(temporary), target_is_directory=True)
    try:
        if os.path.lexists(destination):
            os.replace(destination, backup)
        try:
            os.replace(temporary, destination)
        except Exception:
            if os.path.lexists(backup) and not os.path.lexists(destination):
                os.replace(backup, destination)
            raise
    finally:
        _remove_path(temporary)
        _remove_path(backup)


def _prune_stage_root(stage_root: Path, active_containers: set[Path]) -> int:
    if not _stage_root_is_owned(stage_root):
        raise AndroidNativeStageError(
            f"Refusing to prune unowned Android native stage root: {stage_root}"
        )
    active = {path.resolve() for path in active_containers}
    owner_marker = _stage_owner_path(stage_root)
    removed = 0
    for child in list(stage_root.iterdir()):
        if child == owner_marker:
            continue
        try:
            child_real = child.resolve()
        except OSError:
            child_real = child.absolute()
        if child_real in active:
            continue
        _remove_path(child)
        removed += 1
    return removed


def stage_android_native_bindings(
    frontend_root: Path = FRONTEND_ROOT,
    stage_root: Path | None = None,
) -> list[str]:
    frontend_root = frontend_root.resolve()
    selected_stage_root = (stage_root or _stage_root()).resolve()
    try:
        selected_stage_root.relative_to(frontend_root)
    except ValueError:
        pass
    else:
        raise AndroidNativeStageError(
            "Android native stage root must be outside the frontend checkout"
        )

    _ensure_owned_stage_root(selected_stage_root)
    entries = _load_receipt(frontend_root)
    messages: list[str] = []
    active_containers: set[Path] = set()
    for lock_key, raw_record in sorted(entries.items()):
        if not isinstance(raw_record, dict):
            raise AndroidNativeStageError(
                f"Android native receipt entry is not an object: {lock_key}"
            )
        package, version, binary, lock_integrity, binary_sha256 = _record_fields(
            lock_key, raw_record
        )
        destination = _safe_lock_destination(frontend_root, lock_key)
        staged_package = _ensure_staged_package(
            destination,
            selected_stage_root,
            lock_key=lock_key,
            package=package,
            version=version,
            binary=binary,
            lock_integrity=lock_integrity,
            binary_sha256=binary_sha256,
        )
        active_containers.add(staged_package.parent.resolve(strict=True))
        _link_package(destination, staged_package)
        resolved = destination.resolve(strict=True)
        try:
            resolved.relative_to(selected_stage_root)
        except ValueError as exc:
            raise AndroidNativeStageError(
                f"Android native package did not resolve inside linker-safe stage root: {lock_key}"
            ) from exc
        messages.append(
            "ANDROID_FRONTEND_NATIVE_LINKER_STAGE_READY "
            f"package={package} path={lock_key} version={version} "
            f"native={binary} runtime_path={resolved} sha256={binary_sha256}"
        )

    pruned = _prune_stage_root(selected_stage_root, active_containers)
    messages.append(
        "ANDROID_FRONTEND_NATIVE_LINKER_STAGE_PRUNED "
        f"path={selected_stage_root} removed={pruned}"
    )
    messages.append(
        "ANDROID_FRONTEND_NATIVE_LINKER_STAGE_ROOT_READY "
        f"path={selected_stage_root} entries={len(entries)}"
    )
    return messages


def main() -> int:
    try:
        messages = stage_android_native_bindings()
    except AndroidNativeStageError as exc:
        print(f"ANDROID_FRONTEND_NATIVE_LINKER_STAGE_FAILED detail={exc}", file=sys.stderr)
        return 1

    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
