from pathlib import Path

from scripts.repair_android_database_url import (
    DEFAULT_ANDROID_DATABASE_URL,
    read_env_value,
    repair_android_database_url,
)


def _refuse_connection(*_args, **_kwargs):
    raise ConnectionRefusedError("connection refused")


class _OpenConnection:
    def close(self):
        return None


def _accept_connection(*_args, **_kwargs):
    return _OpenConnection()


def test_missing_database_url_is_created_as_sqlite(tmp_path):
    env_file = tmp_path / ".env"
    runtime_dir = tmp_path / ".runtime"

    selected, backup, changed = repair_android_database_url(
        env_file,
        runtime_dir,
        connector=_refuse_connection,
    )

    assert selected == DEFAULT_ANDROID_DATABASE_URL
    assert backup is None
    assert changed is True
    assert read_env_value(env_file, "DATABASE_URL") == DEFAULT_ANDROID_DATABASE_URL


def test_unavailable_local_postgres_falls_back_to_sqlite_with_backup(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SECRET_KEY=keep-me\n"
        "DATABASE_URL=postgresql://jobtomatik:secret@localhost:5432/jobtomatik\n",
        encoding="utf-8",
    )
    runtime_dir = tmp_path / ".runtime"

    selected, backup, changed = repair_android_database_url(
        env_file,
        runtime_dir,
        connector=_refuse_connection,
    )

    assert selected == DEFAULT_ANDROID_DATABASE_URL
    assert changed is True
    assert backup is not None and backup.is_file()
    assert "postgresql://jobtomatik:secret@localhost:5432/jobtomatik" in backup.read_text(
        encoding="utf-8"
    )
    assert read_env_value(env_file, "DATABASE_URL") == DEFAULT_ANDROID_DATABASE_URL
    assert read_env_value(env_file, "SECRET_KEY") == "keep-me"


def test_reachable_local_postgres_is_preserved(tmp_path):
    env_file = tmp_path / ".env"
    configured = "postgresql://jobtomatik:secret@127.0.0.1:5432/jobtomatik"
    env_file.write_text(f"DATABASE_URL={configured}\n", encoding="utf-8")

    selected, backup, changed = repair_android_database_url(
        env_file,
        tmp_path / ".runtime",
        connector=_accept_connection,
    )

    assert selected == configured
    assert backup is None
    assert changed is False
    assert read_env_value(env_file, "DATABASE_URL") == configured


def test_remote_postgres_is_never_rewritten_by_android_repair(tmp_path):
    env_file = tmp_path / ".env"
    configured = "postgresql://jobtomatik:secret@db.example.com:5432/jobtomatik"
    env_file.write_text(f"DATABASE_URL={configured}\n", encoding="utf-8")

    def connector_must_not_run(*_args, **_kwargs):
        raise AssertionError("remote database reachability must not be probed")

    selected, backup, changed = repair_android_database_url(
        env_file,
        tmp_path / ".runtime",
        connector=connector_must_not_run,
    )

    assert selected == configured
    assert backup is None
    assert changed is False
