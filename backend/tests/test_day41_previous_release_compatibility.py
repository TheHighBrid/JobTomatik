from copy import deepcopy
from pathlib import Path

from app.services.day41_previous_release_compatibility import (
    DAY41_FROZEN_PREVIOUS_RELEASE,
    build_day41_previous_release_compatibility_report,
)
from scripts.run_day41_previous_release_compatibility import _python_executable_path


CANDIDATE = "a" * 40


def _inputs():
    previous_schema = {
        "alembic_version": ["version_num"],
        "users": ["id", "email", "hashed_password", "full_name", "is_active"],
        "applications": ["id", "user_id", "status"],
    }
    migrated_schema = {
        **previous_schema,
        "users": [
            *previous_schema["users"],
            "automation_settings",
            "updated_at",
        ],
        "live_pilot_authorizations": ["id", "status"],
    }
    sentinel = {
        "id": 987654321,
        "email": "day41-v1-compatibility@example.invalid",
        "hashed_password": "synthetic-day41-compatibility-hash",
        "full_name": "Day41 Compatibility Sentinel",
        "is_active": 1,
    }
    return {
        "previous_revision": DAY41_FROZEN_PREVIOUS_RELEASE,
        "candidate_revision": CANDIDATE,
        "previous_database_heads": ["v1_head"],
        "candidate_script_heads": ["v2_head"],
        "candidate_database_heads": ["v2_head"],
        "previous_schema": previous_schema,
        "migrated_schema": migrated_schema,
        "sentinel_before": sentinel,
        "sentinel_after": deepcopy(sentinel),
        "sqlite_integrity_ok": True,
        "foreign_keys_ok": True,
        "current_orm_probe_ok": True,
    }


def _report(**overrides):
    values = _inputs()
    values.update(overrides)
    return build_day41_previous_release_compatibility_report(**values)


def test_python_executable_path_preserves_virtualenv_symlink(tmp_path: Path):
    real_python = tmp_path / "base-python"
    real_python.write_text("", encoding="utf-8")
    venv_bin = tmp_path / ".venv-v1" / "bin"
    venv_bin.mkdir(parents=True)
    venv_python = venv_bin / "python"
    venv_python.symlink_to(real_python)

    selected = _python_executable_path(str(venv_python))

    assert selected == venv_python.absolute()
    assert selected != real_python.resolve()
    assert selected.is_symlink()


def test_clean_frozen_v1_to_candidate_migration_passes():
    report = _report()

    assert report["passed"] is True
    assert report["previous_release_revision"] == DAY41_FROZEN_PREVIOUS_RELEASE
    assert report["candidate_revision"] == CANDIDATE
    assert report["missing_previous_tables"] == []
    assert report["missing_previous_columns"] == {}
    assert report["live_database_touched"] is False
    assert report["synthetic_data_only"] is True
    assert report["row_contents_retained_in_report"] is False
    assert len(report["report_sha256"]) == 64


def test_wrong_previous_revision_is_rejected():
    report = _report(previous_revision="b" * 40)

    assert report["passed"] is False
    assert report["checks"]["frozen_previous_revision_exact"] is False


def test_missing_previous_table_is_rejected():
    values = _inputs()
    migrated = deepcopy(values["migrated_schema"])
    migrated.pop("applications")

    report = _report(migrated_schema=migrated)

    assert report["passed"] is False
    assert report["missing_previous_tables"] == ["applications"]
    assert report["checks"]["all_previous_tables_preserved"] is False


def test_missing_previous_column_is_rejected():
    values = _inputs()
    migrated = deepcopy(values["migrated_schema"])
    migrated["users"].remove("hashed_password")

    report = _report(migrated_schema=migrated)

    assert report["passed"] is False
    assert report["missing_previous_columns"] == {"users": ["hashed_password"]}
    assert report["checks"]["all_previous_columns_preserved"] is False


def test_sentinel_mutation_is_rejected():
    values = _inputs()
    sentinel = deepcopy(values["sentinel_after"])
    sentinel["email"] = "changed@example.invalid"

    report = _report(sentinel_after=sentinel)

    assert report["passed"] is False
    assert report["checks"]["synthetic_user_sentinel_preserved"] is False


def test_candidate_database_must_reach_candidate_script_heads():
    report = _report(candidate_database_heads=["stale_head"])

    assert report["passed"] is False
    assert report["checks"]["candidate_database_reaches_exact_script_heads"] is False


def test_integrity_foreign_key_and_orm_failures_are_all_blocking():
    report = _report(
        sqlite_integrity_ok=False,
        foreign_keys_ok=False,
        current_orm_probe_ok=False,
    )

    assert report["passed"] is False
    assert report["checks"]["sqlite_integrity_ok"] is False
    assert report["checks"]["foreign_keys_ok"] is False
    assert report["checks"]["current_orm_can_read_migrated_v1_row"] is False


def test_report_is_deterministic():
    first = _report()
    second = _report()

    assert first == second
    assert first["report_sha256"] == second["report_sha256"]
