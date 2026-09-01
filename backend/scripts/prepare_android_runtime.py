from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import models as _models  # noqa: E402,F401
from app.config import get_settings  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.services.application_recovery import recover_interrupted_application_attempts  # noqa: E402
from scripts.repair_android_runtime_secret import repair_android_runtime_secret  # noqa: E402

CRITICAL_TABLES = {
    "users",
    "jobs",
    "applications",
    "agent_runs",
    "agent_tasks",
    "opportunity_evaluations",
}
MAX_RUNTIME_BACKUPS = 3


def _sqlite_database_path() -> Path | None:
    if engine.dialect.name != "sqlite":
        return None
    database = str(engine.url.database or "").strip()
    if not database or database == ":memory:":
        return None
    path = Path(database)
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    return path.resolve()


def _prune_runtime_backups(backup_dir: Path, database_name: str) -> None:
    backups = sorted(
        backup_dir.glob(f"{database_name}.before-schema-*"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for stale_backup in backups[MAX_RUNTIME_BACKUPS:]:
        stale_backup.unlink(missing_ok=True)


def _backup_database_if_needed(missing_tables: set[str]) -> Path | None:
    database_path = _sqlite_database_path()
    if database_path is None or not database_path.exists() or not missing_tables:
        return None

    backup_dir = BACKEND_ROOT / "runtime_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{database_path.name}.before-schema-{stamp}"
    shutil.copy2(database_path, backup_path)
    _prune_runtime_backups(backup_dir, database_path.name)
    return backup_path


def _table_names() -> set[str]:
    return set(sa_inspect(engine).get_table_names())


def _browser_status() -> tuple[bool, str]:
    endpoint = (get_settings().application_browser_cdp_endpoint or "").strip().rstrip("/")
    if not endpoint:
        return False, "APPLICATION_BROWSER_CDP_ENDPOINT is not configured"
    try:
        response = httpx.get(f"{endpoint}/json/version", timeout=2)
        response.raise_for_status()
        payload = response.json()
        if payload.get("webSocketDebuggerUrl"):
            return True, endpoint
        return False, "CDP response did not include webSocketDebuggerUrl"
    except Exception as exc:
        return False, str(exc)


def _recover_abandoned_application_attempts() -> dict:
    """Recover every attempt whose owning Android worker was replaced.

    The manager stops/retires old workers before this preflight runs. Any row still in
    ``applying`` therefore has no worker that can legitimately finish it, regardless
    of age. Dry runs remain fail-closed in review; live/unknown attempts remain
    submission-uncertain.
    """
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    try:
        result = recover_interrupted_application_attempts(db)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    secret_migration = repair_android_runtime_secret(
        BACKEND_ROOT / ".env",
        BACKEND_ROOT / ".runtime",
    )

    before = _table_names()
    missing_before = CRITICAL_TABLES - before
    backup_path = _backup_database_if_needed(missing_before)

    Base.metadata.create_all(bind=engine)

    after = _table_names()
    missing_after = CRITICAL_TABLES - after
    if missing_after:
        missing = ", ".join(sorted(missing_after))
        raise RuntimeError(f"Runtime schema repair did not create required tables: {missing}")

    recovery = _recover_abandoned_application_attempts()

    if secret_migration["changed"]:
        print("ANDROID_RUNTIME_SECRET_MIGRATED")
        print("ANDROID_RUNTIME_VAULT_KEY_PRESERVED")
        print("ANDROID_RUNTIME_REAUTHENTICATION_MAY_BE_REQUIRED")
    else:
        print("ANDROID_RUNTIME_SECRET_READY")
    print("JOBTOMATIK_RUNTIME_SCHEMA_READY")
    print(f"Database: {engine.url.render_as_string(hide_password=True)}")
    if backup_path is not None:
        print(f"Backup: {backup_path}")
    if missing_before:
        print("Created tables: " + ", ".join(sorted(missing_before)))
    else:
        print("Schema changes: none")
    print(f"ANDROID_INTERRUPTED_APPLICATIONS_RECOVERED={int(recovery.get('recovered') or 0)}")

    browser_ready, browser_detail = _browser_status()
    if browser_ready:
        print("ANDROID_BROWSER_CDP_CONNECTED")
        print(f"Endpoint: {browser_detail}")
    else:
        print("ANDROID_BROWSER_CDP_DISCONNECTED")
        print(f"Browser detail: {browser_detail}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
