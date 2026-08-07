import os

from sqlalchemy import create_engine, inspect as sa_inspect

from scripts import prepare_android_runtime
from scripts.prepare_android_runtime import MAX_RUNTIME_BACKUPS, _prune_runtime_backups


def test_runtime_backup_pruning_keeps_only_newest_three(tmp_path):
    backups = []
    for index in range(5):
        backup = tmp_path / f"jobtomatik.db.before-schema-20260806T00000{index}Z"
        backup.write_text(str(index), encoding="utf-8")
        os.utime(backup, (100 + index, 100 + index))
        backups.append(backup)

    _prune_runtime_backups(tmp_path, "jobtomatik.db")

    remaining = sorted(tmp_path.glob("jobtomatik.db.before-schema-*"))
    assert len(remaining) == MAX_RUNTIME_BACKUPS
    assert {path.name for path in remaining} == {path.name for path in backups[-3:]}


def test_runtime_preflight_creates_critical_tables(tmp_path, monkeypatch, capsys):
    runtime_engine = create_engine(f"sqlite:///{tmp_path / 'runtime.db'}")
    monkeypatch.setattr(prepare_android_runtime, "engine", runtime_engine)
    monkeypatch.setattr(
        prepare_android_runtime,
        "_browser_status",
        lambda: (True, "http://127.0.0.1:9222"),
    )

    assert prepare_android_runtime.main() == 0

    tables = set(sa_inspect(runtime_engine).get_table_names())
    assert prepare_android_runtime.CRITICAL_TABLES <= tables
    output = capsys.readouterr().out
    assert "JOBTOMATIK_RUNTIME_SCHEMA_READY" in output
    assert "ANDROID_BROWSER_CDP_CONNECTED" in output
