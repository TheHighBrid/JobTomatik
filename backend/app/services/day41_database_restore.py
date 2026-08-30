"""Non-destructive SQLite backup/restore verification for Day 41.

The source database is opened read-only. The drill creates a point-in-time SQLite backup,
restores that backup into a separate file, and compares integrity, schema, row counts, and
a hashed logical dump without exposing row contents in the retained report.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


DAY41_DATABASE_RESTORE_VERSION = "day41-sqlite-restore-drill-v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _logical_dump_sha256(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for statement in connection.iterdump():
        digest.update(statement.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _schema_sha256(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT type, name, tbl_name, COALESCE(sql, '') "
        "FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name, tbl_name"
    ).fetchall()
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    result: dict[str, int] = {}
    for name in names:
        escaped = name.replace('"', '""')
        result[name] = int(connection.execute(f'SELECT COUNT(*) FROM "{escaped}"').fetchone()[0])
    return result


def _integrity_ok(connection: sqlite3.Connection) -> bool:
    rows = connection.execute("PRAGMA integrity_check").fetchall()
    return rows == [("ok",)]


def _foreign_keys_ok(connection: sqlite3.Connection) -> bool:
    return connection.execute("PRAGMA foreign_key_check").fetchall() == []


def run_sqlite_restore_drill(
    source_database: str | Path,
    *,
    output_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Create and restore a read-only point-in-time backup of one SQLite database."""

    source = Path(source_database).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {source}")

    own_temp = output_directory is None
    temp_handle = tempfile.TemporaryDirectory(prefix="jobtomatik-day41-restore-") if own_temp else None
    root = Path(temp_handle.name if temp_handle else output_directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    snapshot = root / "snapshot.sqlite3"
    restored = root / "restored.sqlite3"

    for path in (snapshot, restored):
        if path.exists():
            path.unlink()

    source_uri = f"file:{source.as_posix()}?mode=ro"
    source_connection = sqlite3.connect(source_uri, uri=True)
    snapshot_connection = sqlite3.connect(snapshot)
    try:
        source_connection.backup(snapshot_connection)
    finally:
        snapshot_connection.close()
        source_connection.close()

    snapshot_connection = sqlite3.connect(snapshot)
    restored_connection = sqlite3.connect(restored)
    try:
        snapshot_connection.backup(restored_connection)
    finally:
        restored_connection.close()
        snapshot_connection.close()

    snapshot_connection = sqlite3.connect(f"file:{snapshot.as_posix()}?mode=ro", uri=True)
    restored_connection = sqlite3.connect(f"file:{restored.as_posix()}?mode=ro", uri=True)
    try:
        snapshot_integrity = _integrity_ok(snapshot_connection)
        restored_integrity = _integrity_ok(restored_connection)
        snapshot_fk = _foreign_keys_ok(snapshot_connection)
        restored_fk = _foreign_keys_ok(restored_connection)
        snapshot_schema = _schema_sha256(snapshot_connection)
        restored_schema = _schema_sha256(restored_connection)
        snapshot_counts = _table_counts(snapshot_connection)
        restored_counts = _table_counts(restored_connection)
        snapshot_logical = _logical_dump_sha256(snapshot_connection)
        restored_logical = _logical_dump_sha256(restored_connection)
    finally:
        snapshot_connection.close()
        restored_connection.close()

    checks = {
        "source_opened_read_only": True,
        "snapshot_integrity_ok": snapshot_integrity,
        "restored_integrity_ok": restored_integrity,
        "snapshot_foreign_keys_ok": snapshot_fk,
        "restored_foreign_keys_ok": restored_fk,
        "schema_digest_matches": snapshot_schema == restored_schema,
        "table_counts_match": snapshot_counts == restored_counts,
        "logical_dump_digest_matches": snapshot_logical == restored_logical,
    }
    passed = all(checks.values())
    report: dict[str, Any] = {
        "version": DAY41_DATABASE_RESTORE_VERSION,
        "source_database_name": source.name,
        "source_mode": "read_only",
        "sqlite_version": sqlite3.sqlite_version,
        "snapshot_sha256": _sha256_file(snapshot),
        "restored_sha256": _sha256_file(restored),
        "snapshot_schema_sha256": snapshot_schema,
        "restored_schema_sha256": restored_schema,
        "snapshot_logical_dump_sha256": snapshot_logical,
        "restored_logical_dump_sha256": restored_logical,
        "table_counts": snapshot_counts,
        "checks": checks,
        "passed": passed,
        "source_database_modified_by_drill": False,
        "row_contents_retained_in_report": False,
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    report["report_sha256"] = hashlib.sha256(canonical).hexdigest()

    if temp_handle is not None:
        temp_handle.cleanup()
    return report


__all__ = ["DAY41_DATABASE_RESTORE_VERSION", "run_sqlite_restore_drill"]
