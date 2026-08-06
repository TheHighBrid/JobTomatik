from __future__ import annotations

import argparse
import shutil
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

DEFAULT_ANDROID_DATABASE_URL = "sqlite:///./jobtomatik.db"
LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}
MAX_ENV_BACKUPS = 3


def read_env_value(env_file: Path, key: str) -> str | None:
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
            candidate = candidate[1:-1]
        value = candidate
    return value


def write_env_value(env_file: Path, key: str, value: str) -> None:
    env_file.parent.mkdir(parents=True, exist_ok=True)
    existing = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    prefix = f"{key}="
    rewritten: list[str] = []
    inserted = False

    for line in existing:
        if line.strip().startswith(prefix) and not line.lstrip().startswith("#"):
            if not inserted:
                rewritten.append(f"{key}={value}")
                inserted = True
            continue
        rewritten.append(line)

    if not inserted:
        if rewritten and rewritten[-1].strip():
            rewritten.append("")
        rewritten.append(f"{key}={value}")

    env_file.write_text("\n".join(rewritten).rstrip() + "\n", encoding="utf-8")


def local_postgres_is_unavailable(
    database_url: str,
    *,
    connector: Callable[..., socket.socket] = socket.create_connection,
) -> bool:
    parsed = urlparse(database_url)
    scheme = parsed.scheme.lower()
    if not scheme.startswith(("postgres", "postgresql")):
        return False

    host = (parsed.hostname or "").lower()
    if host not in LOCAL_DATABASE_HOSTS:
        return False

    port = parsed.port or 5432
    try:
        connection = connector((host, port), timeout=1.0)
    except OSError:
        return True
    else:
        connection.close()
        return False


def _prune_env_backups(backup_dir: Path) -> None:
    backups = sorted(
        backup_dir.glob("backend.env.before-local-postgres-fallback-*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for stale in backups[MAX_ENV_BACKUPS:]:
        stale.unlink(missing_ok=True)


def repair_android_database_url(
    env_file: Path,
    runtime_dir: Path,
    *,
    connector: Callable[..., socket.socket] = socket.create_connection,
) -> tuple[str, Path | None, bool]:
    current = read_env_value(env_file, "DATABASE_URL")
    if not current:
        write_env_value(env_file, "DATABASE_URL", DEFAULT_ANDROID_DATABASE_URL)
        return DEFAULT_ANDROID_DATABASE_URL, None, True

    if not local_postgres_is_unavailable(current, connector=connector):
        return current, None, False

    backup_dir = runtime_dir / "env-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"backend.env.before-local-postgres-fallback-{timestamp}"
    shutil.copy2(env_file, backup_path)
    _prune_env_backups(backup_dir)

    write_env_value(env_file, "DATABASE_URL", DEFAULT_ANDROID_DATABASE_URL)
    return DEFAULT_ANDROID_DATABASE_URL, backup_path, True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair an unavailable localhost PostgreSQL URL for Android-only operation."
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()

    selected_url, backup_path, changed = repair_android_database_url(
        args.env_file,
        args.runtime_dir,
    )

    if changed and backup_path is not None:
        print("ANDROID_DATABASE_URL_REPAIRED")
        print(f"Environment backup: {backup_path}")
    elif changed:
        print("ANDROID_DATABASE_URL_CREATED")
    else:
        print("ANDROID_DATABASE_URL_READY")

    parsed = urlparse(selected_url)
    backend = "sqlite" if parsed.scheme == "sqlite" else parsed.scheme or "configured"
    print(f"Database backend: {backend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
