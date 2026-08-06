import os

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
