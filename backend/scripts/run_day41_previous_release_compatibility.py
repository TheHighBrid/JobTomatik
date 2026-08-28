#!/usr/bin/env python3
"""Exercise a frozen v1 SQLite database against the current candidate migrations.

This drill never opens the live JobTomatik database. It creates a temporary database from
the frozen v1 source, inserts one synthetic user sentinel, migrates the database with the
candidate source, and verifies schema/data/ORM compatibility.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.services.day41_previous_release_compatibility import (
    DAY41_FROZEN_PREVIOUS_RELEASE,
    build_day41_previous_release_compatibility_report,
)


SENTINEL = {
    "id": 987654321,
    "email": "day41-v1-compatibility@example.invalid",
    "hashed_password": "synthetic-day41-compatibility-hash",
    "full_name": "Day41 Compatibility Sentinel",
    "is_active": 1,
}


def _python_executable_path(raw: str) -> Path:
    """Return an absolute executable path without dereferencing virtualenv symlinks.

    ``venv/bin/python`` is commonly a symlink to the base interpreter. ``Path.resolve()``
    follows that symlink and silently discards the virtualenv's ``pyvenv.cfg`` context,
    causing subprocesses to lose the environment's installed packages. ``abspath`` keeps
    the invocation path intact while still removing relative-path ambiguity.
    """

    return Path(os.path.abspath(os.path.expanduser(raw)))


def _git_revision(checkout: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
    ).strip().lower()


def _run_python(
    python_executable: Path,
    *,
    cwd: Path,
    code: str,
    env: dict[str, str],
) -> Any:
    completed = subprocess.run(
        [str(python_executable), "-c", code],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Compatibility probe failed in {cwd}:\n{completed.stderr.strip()}"
        )
    text = completed.stdout.strip().splitlines()
    if not text:
        raise RuntimeError(f"Compatibility probe produced no output in {cwd}")
    return json.loads(text[-1])


def _migration_probe(
    python_executable: Path,
    backend: Path,
    *,
    database_url: str,
    env: dict[str, str],
) -> dict[str, Any]:
    # Import Alembic while cwd is outside ``backend`` and without an inherited
    # PYTHONPATH so neither checkout's local ``backend/alembic`` migration
    # directory can shadow the installed Alembic package.
    code = r'''
import json
import os
import sys
from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

backend = Path(os.environ["COMPAT_BACKEND"]).resolve()
url = os.environ["COMPAT_DATABASE_URL"]
sys.path.insert(0, str(backend))
cfg = Config(str(backend / "alembic.ini"))
cfg.set_main_option("script_location", str(backend / "alembic"))
cfg.set_main_option("sqlalchemy.url", url)
command.upgrade(cfg, "head")
script = ScriptDirectory.from_config(cfg)
script_heads = sorted(script.get_heads())
engine = create_engine(url)
with engine.connect() as connection:
    database_heads = sorted(MigrationContext.configure(connection).get_current_heads())
print(json.dumps({"script_heads": script_heads, "database_heads": database_heads}, sort_keys=True))
'''
    probe_env = dict(env)
    probe_env.pop("PYTHONPATH", None)
    probe_env["COMPAT_BACKEND"] = str(backend)
    probe_env["COMPAT_DATABASE_URL"] = database_url
    probe_env["DATABASE_URL"] = database_url
    return _run_python(
        python_executable,
        cwd=backend.parent,
        code=code,
        env=probe_env,
    )


def _schema_snapshot(connection: sqlite3.Connection) -> dict[str, list[str]]:
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    result: dict[str, list[str]] = {}
    for table in tables:
        escaped = table.replace('"', '""')
        result[table] = sorted(
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{escaped}")').fetchall()
        )
    return result


def _read_sentinel(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        "SELECT id, email, hashed_password, full_name, is_active FROM users WHERE id = ?",
        (SENTINEL["id"],),
    ).fetchone()
    if row is None:
        return {}
    return {
        "id": int(row[0]),
        "email": str(row[1]),
        "hashed_password": str(row[2]),
        "full_name": str(row[3]),
        "is_active": int(row[4]),
    }


def _seed_previous_release(database: Path) -> tuple[dict[str, list[str]], dict[str, Any]]:
    connection = sqlite3.connect(database)
    try:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        required = {"id", "email", "hashed_password", "full_name", "is_active"}
        missing = required - columns
        if missing:
            raise RuntimeError(f"Frozen v1 users schema missing expected columns: {sorted(missing)}")
        connection.execute(
            "INSERT INTO users (id, email, hashed_password, full_name, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                SENTINEL["id"],
                SENTINEL["email"],
                SENTINEL["hashed_password"],
                SENTINEL["full_name"],
                SENTINEL["is_active"],
            ),
        )
        connection.commit()
        return _schema_snapshot(connection), _read_sentinel(connection)
    finally:
        connection.close()


def _post_migration_probe(database: Path) -> tuple[dict[str, list[str]], dict[str, Any], bool, bool]:
    connection = sqlite3.connect(database)
    try:
        schema = _schema_snapshot(connection)
        sentinel = _read_sentinel(connection)
        integrity_ok = connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        foreign_keys_ok = connection.execute("PRAGMA foreign_key_check").fetchall() == []
        return schema, sentinel, integrity_ok, foreign_keys_ok
    finally:
        connection.close()


def _orm_probe(
    python_executable: Path,
    backend: Path,
    *,
    database_url: str,
    env: dict[str, str],
) -> bool:
    code = r'''
import json
from app.database import SessionLocal
from app.models import User

db = SessionLocal()
try:
    row = db.query(User).filter(User.id == 987654321).one_or_none()
    passed = bool(
        row is not None
        and row.email == "day41-v1-compatibility@example.invalid"
        and row.hashed_password == "synthetic-day41-compatibility-hash"
        and row.full_name == "Day41 Compatibility Sentinel"
        and row.is_active is True
    )
finally:
    db.close()
print(json.dumps({"passed": passed}))
'''
    probe_env = dict(env)
    probe_env["DATABASE_URL"] = database_url
    result = _run_python(
        python_executable,
        cwd=backend,
        code=code,
        env=probe_env,
    )
    return result.get("passed") is True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-checkout", required=True)
    parser.add_argument("--candidate-checkout", required=True)
    parser.add_argument("--previous-python", required=True)
    parser.add_argument("--candidate-python", required=True)
    parser.add_argument(
        "--output",
        default="evidence/day41-previous-release-compatibility.json",
    )
    args = parser.parse_args()

    previous_checkout = Path(args.previous_checkout).resolve()
    candidate_checkout = Path(args.candidate_checkout).resolve()
    previous_backend = previous_checkout / "backend"
    candidate_backend = candidate_checkout / "backend"
    previous_python = _python_executable_path(args.previous_python)
    candidate_python = _python_executable_path(args.candidate_python)

    previous_revision = _git_revision(previous_checkout)
    candidate_revision = _git_revision(candidate_checkout)
    if previous_revision != DAY41_FROZEN_PREVIOUS_RELEASE:
        raise RuntimeError(
            f"Previous checkout {previous_revision} is not frozen v1 {DAY41_FROZEN_PREVIOUS_RELEASE}"
        )

    source_manifest = (candidate_checkout / "RELEASE_SOURCE.txt").read_text(encoding="utf-8")
    if f"Frozen release source commit: {DAY41_FROZEN_PREVIOUS_RELEASE}" not in source_manifest:
        raise RuntimeError("Current RELEASE_SOURCE.txt does not attest the frozen v1 source commit")

    base_env = dict(os.environ)
    base_env.update(
        {
            "SECRET_KEY": "day41-previous-release-compatibility-ci-only-secret-key",
            "REDIS_URL": "redis://localhost:6379/0",
            "AI_PROVIDER": "template",
            "DEV_MOCK_JOBS": "false",
            "ALLOW_REAL_APPLICATION_SUBMIT": "false",
            "ALLOW_REAL_FOLLOWUP_SEND": "false",
            "AUTOPILOT_ENABLED": "false",
        }
    )

    with tempfile.TemporaryDirectory(prefix="jobtomatik-day41-v1-compat-") as tmp:
        database = Path(tmp) / "v1-to-v2.sqlite3"
        database_url = f"sqlite:///{database.as_posix()}"

        previous_probe = _migration_probe(
            previous_python,
            previous_backend,
            database_url=database_url,
            env=base_env,
        )
        previous_schema, sentinel_before = _seed_previous_release(database)

        candidate_probe = _migration_probe(
            candidate_python,
            candidate_backend,
            database_url=database_url,
            env=base_env,
        )
        migrated_schema, sentinel_after, integrity_ok, foreign_keys_ok = _post_migration_probe(
            database
        )
        orm_probe_ok = _orm_probe(
            candidate_python,
            candidate_backend,
            database_url=database_url,
            env=base_env,
        )

    report = build_day41_previous_release_compatibility_report(
        previous_revision=previous_revision,
        candidate_revision=candidate_revision,
        previous_database_heads=previous_probe.get("database_heads"),
        candidate_script_heads=candidate_probe.get("script_heads"),
        candidate_database_heads=candidate_probe.get("database_heads"),
        previous_schema=previous_schema,
        migrated_schema=migrated_schema,
        sentinel_before=sentinel_before,
        sentinel_after=sentinel_after,
        sqlite_integrity_ok=integrity_ok,
        foreign_keys_ok=foreign_keys_ok,
        current_orm_probe_ok=orm_probe_ok,
    )

    output = Path(args.output)
    if not output.is_absolute():
        output = candidate_backend / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": report.get("passed"),
                "previous_release_revision": report.get("previous_release_revision"),
                "candidate_revision": report.get("candidate_revision"),
                "report_sha256": report.get("report_sha256"),
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0 if report.get("passed") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
