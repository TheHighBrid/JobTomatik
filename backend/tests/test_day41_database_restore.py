import hashlib
import sqlite3
from pathlib import Path

import pytest

from app.services.day41_database_restore import run_sqlite_restore_drill


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_database(path: Path):
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL, "
            "value TEXT, FOREIGN KEY(parent_id) REFERENCES parent(id))"
        )
        connection.executemany(
            "INSERT INTO parent(id, name) VALUES (?, ?)",
            [(1, "one"), (2, "two")],
        )
        connection.executemany(
            "INSERT INTO child(id, parent_id, value) VALUES (?, ?, ?)",
            [(10, 1, "alpha"), (11, 2, "beta"), (12, 2, "gamma")],
        )
        connection.commit()
    finally:
        connection.close()


def test_day41_restore_drill_is_non_destructive_and_logically_exact(tmp_path):
    source = tmp_path / "jobtomatik.db"
    work = tmp_path / "restore-work"
    _build_database(source)
    before = _sha256(source)

    report = run_sqlite_restore_drill(source, output_directory=work)

    after = _sha256(source)
    assert report["passed"] is True
    assert report["source_mode"] == "read_only"
    assert report["source_database_modified_by_drill"] is False
    assert report["row_contents_retained_in_report"] is False
    assert report["checks"] == {
        "source_opened_read_only": True,
        "snapshot_integrity_ok": True,
        "restored_integrity_ok": True,
        "snapshot_foreign_keys_ok": True,
        "restored_foreign_keys_ok": True,
        "schema_digest_matches": True,
        "table_counts_match": True,
        "logical_dump_digest_matches": True,
    }
    assert report["table_counts"] == {"child": 3, "parent": 2}
    assert report["snapshot_schema_sha256"] == report["restored_schema_sha256"]
    assert report["snapshot_logical_dump_sha256"] == report["restored_logical_dump_sha256"]
    assert len(report["report_sha256"]) == 64
    assert before == after
    assert (work / "snapshot.sqlite3").is_file()
    assert (work / "restored.sqlite3").is_file()


def test_day41_restore_drill_supports_ephemeral_work_directory(tmp_path):
    source = tmp_path / "jobtomatik.db"
    _build_database(source)

    report = run_sqlite_restore_drill(source)

    assert report["passed"] is True
    assert report["source_database_name"] == "jobtomatik.db"


def test_day41_restore_drill_rejects_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_sqlite_restore_drill(tmp_path / "missing.db")


def test_day41_restore_report_never_contains_database_row_values(tmp_path):
    source = tmp_path / "jobtomatik.db"
    work = tmp_path / "restore-work"
    _build_database(source)

    report = run_sqlite_restore_drill(source, output_directory=work)
    serialized = repr(report)

    assert "alpha" not in serialized
    assert "beta" not in serialized
    assert "gamma" not in serialized
