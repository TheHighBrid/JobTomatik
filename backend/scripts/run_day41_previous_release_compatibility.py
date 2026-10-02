#!/usr/bin/env python3
"""Exercise a real frozen-v1 runtime schema against the current candidate startup path.

JobTomatik v1.00 did not ship Alembic revision files. Its real database bootstrap was
``Base.metadata.create_all`` followed by ``_safe_migrate``. This drill reproduces that
exact historical behavior in an isolated temporary SQLite database, inserts one synthetic
user sentinel, runs the current candidate's real startup schema path against the same
database, and verifies old-data preservation plus full current-ORM schema compatibility.

The live JobTomatik database is never opened, copied, or mutated.
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
    DAY41_RUNTIME_SCHEMA_BOOTSTRAP,
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
    """Return an absolute executable path without dereferencing virtualenv symlinks."""

    return Path(os.path.abspath(os.path.expanduser(raw)))


def _git_revision(checkout: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
    ).strip().lower()


def _alembic_revision_count(backend: Path) -> int:
    versions = backend / "alembic" / "versions"
    if not versions.is_dir():
        return 0
    return sum(
        1
        for path in versions.glob("*.py")
        if path.name != "__init__.py" and path.is_file()
    )


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


def _runtime_schema_bootstrap(
    python_executable: Path,
    backend: Path,
    *,
    database_url: str,
    env: dict[str, str],
) -> dict[str, Any]:
    code = r'''
import json
from app.database import Base, engine
from app.models import *  # noqa: F401,F403
from app.main import _safe_migrate

try:
    Base.metadata.create_all(bind=engine)
    _safe_migrate(engine)
except Exception as exc:
    print(json.dumps({"ok": False, "error_type": type(exc).__name__}, sort_keys=True))
else:
    print(json.dumps({"ok": True, "dialect": engine.dialect.name}, sort_keys=True))
'''
    probe_env = dict(env)
    probe_env["PYTHONPATH"] = str(backend)
    probe_env["DATABASE_URL"] = database_url
    return _run_python(
        python_executable,
        cwd=backend,
        code=code,
        env=probe_env,
    )


def _candidate_expected_schema(
    python_executable: Path,
    backend: Path,
    *,
    database_url: str,
    env: dict[str, str],
) -> dict[str, list[str]]:
    code = r'''
import json
from app.database import Base
from app.models import *  # noqa: F401,F403

schema = {
    table.name: sorted(column.name for column in table.columns)
    for table in Base.metadata.sorted_tables
}
print(json.dumps(schema, sort_keys=True))
'''
    probe_env = dict(env)
    probe_env["PYTHONPATH"] = str(backend)
    probe_env["DATABASE_URL"] = database_url
    result = _run_python(
        python_executable,
        cwd=backend,
        code=code,
        env=probe_env,
    )
    return {
        str(table): [str(column) for column in columns]
        for table, columns in result.items()
    }


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


def _post_upgrade_probe(
    database: Path,
) -> tuple[dict[str, list[str]], dict[str, Any], bool, bool]:
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

try:
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
except Exception:
    passed = False
print(json.dumps({"passed": passed}))
'''
    probe_env = dict(env)
    probe_env["PYTHONPATH"] = str(backend)
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

    previous_alembic_revision_count = _alembic_revision_count(previous_backend)
    candidate_alembic_revision_count = _alembic_revision_count(candidate_backend)

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

        previous_bootstrap = _runtime_schema_bootstrap(
            previous_python,
            previous_backend,
            database_url=database_url,
            env=base_env,
        )
        previous_schema, sentinel_before = _seed_previous_release(database)
        candidate_expected_schema = _candidate_expected_schema(
            candidate_python,
            candidate_backend,
            database_url=database_url,
            env=base_env,
        )
        candidate_upgrade = _runtime_schema_bootstrap(
            candidate_python,
            candidate_backend,
            database_url=database_url,
            env=base_env,
        )
        migrated_schema, sentinel_after, integrity_ok, foreign_keys_ok = _post_upgrade_probe(
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
        previous_bootstrap_method=DAY41_RUNTIME_SCHEMA_BOOTSTRAP,
        candidate_upgrade_method=DAY41_RUNTIME_SCHEMA_BOOTSTRAP,
        previous_alembic_revision_count=previous_alembic_revision_count,
        candidate_alembic_revision_count=candidate_alembic_revision_count,
        previous_bootstrap_ok=previous_bootstrap.get("ok") is True,
        candidate_upgrade_ok=candidate_upgrade.get("ok") is True,
        previous_schema=previous_schema,
        migrated_schema=migrated_schema,
        candidate_expected_schema=candidate_expected_schema,
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
                "previous_table_count": report.get("previous_table_count"),
                "migrated_table_count": report.get("migrated_table_count"),
                "candidate_expected_table_count": report.get("candidate_expected_table_count"),
                "missing_candidate_tables": report.get("missing_candidate_tables"),
                "missing_candidate_columns": report.get("missing_candidate_columns"),
                "report_sha256": report.get("report_sha256"),
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0 if report.get("passed") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
