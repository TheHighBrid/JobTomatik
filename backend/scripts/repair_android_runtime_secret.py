from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.config import DEFAULT_SECRET_KEY, PLACEHOLDER_SECRET_MARKERS


MIN_SECRET_BYTES = 32
MAX_ENV_BACKUPS = 3


def _read_env_value(env_file: Path, key: str) -> str | None:
    if not env_file.exists():
        return None

    value: str | None = None
    prefix = f"{key}="
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        candidate = line[len(prefix):].strip()
        if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"'", '"'}:
            try:
                if candidate[0] == '"':
                    candidate = json.loads(candidate)
                else:
                    candidate = candidate[1:-1]
            except (TypeError, ValueError, json.JSONDecodeError):
                candidate = candidate[1:-1]
        value = candidate
    return value


def _secret_is_unsafe(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    encoded = str(value or "").encode("utf-8")
    return bool(
        len(encoded) < MIN_SECRET_BYTES
        or normalized == DEFAULT_SECRET_KEY
        or any(marker in normalized for marker in PLACEHOLDER_SECRET_MARKERS)
    )


def _encode_env_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:+\-=]+", value):
        return value
    return json.dumps(value)


def _atomic_set_env_values(env_file: Path, updates: dict[str, str]) -> None:
    env_file.parent.mkdir(parents=True, exist_ok=True)
    original = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    keys = set(updates)
    seen: set[str] = set()
    output: list[str] = []

    for raw_line in original.splitlines(keepends=True):
        stripped = raw_line.rstrip("\r\n")
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", stripped)
        key = match.group(1) if match else None
        if key not in keys:
            output.append(raw_line)
            continue
        if key in seen:
            continue
        ending = "\n" if raw_line.endswith("\n") else ""
        output.append(f"{key}={_encode_env_value(updates[key])}{ending}")
        seen.add(key)

    if output and not output[-1].endswith("\n"):
        output[-1] += "\n"
    for key in updates:
        if key not in seen:
            output.append(f"{key}={_encode_env_value(updates[key])}\n")

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{env_file.name}.",
        suffix=".tmp",
        dir=str(env_file.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(output)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, env_file)
        directory_fd = os.open(str(env_file.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _backup_env(env_file: Path, runtime_dir: Path) -> Path | None:
    if not env_file.exists():
        return None
    backup_dir = runtime_dir / "env-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / (
        f"backend.env.before-secret-migration-{timestamp}-{os.getpid()}"
    )
    shutil.copy2(env_file, backup_path)
    os.chmod(backup_path, 0o600)

    backups = sorted(
        backup_dir.glob("backend.env.before-secret-migration-*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for stale in backups[MAX_ENV_BACKUPS:]:
        stale.unlink(missing_ok=True)
    return backup_path


def repair_android_runtime_secret(
    env_file: Path,
    runtime_dir: Path,
    *,
    token_factory: Callable[[int], str] = secrets.token_urlsafe,
) -> dict[str, object]:
    configured_secret = _read_env_value(env_file, "SECRET_KEY")
    effective_secret = configured_secret or DEFAULT_SECRET_KEY
    current_vault_key = _read_env_value(env_file, "ANSWER_VAULT_KEY") or ""

    if not _secret_is_unsafe(effective_secret):
        return {
            "changed": False,
            "backup_path": None,
            "vault_key_preserved": bool(current_vault_key),
            "secret_key_safe": True,
        }

    generated_secret = token_factory(48)
    if _secret_is_unsafe(generated_secret):
        raise RuntimeError("ANDROID_RUNTIME_SECRET_GENERATION_FAILED")

    updates = {"SECRET_KEY": generated_secret}
    vault_key_preserved = bool(current_vault_key)
    if not current_vault_key:
        # Answer Policy Vault and retained handoff encryption both fall back to
        # SECRET_KEY. Freeze the old effective value into ANSWER_VAULT_KEY before
        # rotating authentication/runtime signing so existing ciphertext remains
        # decryptable after the restart.
        updates["ANSWER_VAULT_KEY"] = effective_secret
        vault_key_preserved = True

    backup_path = _backup_env(env_file, runtime_dir)
    _atomic_set_env_values(env_file, updates)

    selected_secret = _read_env_value(env_file, "SECRET_KEY") or ""
    selected_vault_key = _read_env_value(env_file, "ANSWER_VAULT_KEY") or ""
    if _secret_is_unsafe(selected_secret):
        raise RuntimeError("ANDROID_RUNTIME_SECRET_MIGRATION_FAILED")
    if not selected_vault_key:
        raise RuntimeError("ANDROID_RUNTIME_VAULT_KEY_PRESERVATION_FAILED")

    return {
        "changed": True,
        "backup_path": backup_path,
        "vault_key_preserved": vault_key_preserved,
        "secret_key_safe": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Safely migrate an old Android placeholder SECRET_KEY while preserving "
            "the effective Answer Vault/handoff encryption key."
        )
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()

    result = repair_android_runtime_secret(args.env_file, args.runtime_dir)
    if result["changed"]:
        print("ANDROID_RUNTIME_SECRET_MIGRATED")
        if result["backup_path"]:
            print(f"Environment backup: {result['backup_path']}")
        print("Existing vault/handoff encryption key preserved: yes")
        print("Existing login tokens may require re-authentication after restart.")
    else:
        print("ANDROID_RUNTIME_SECRET_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
