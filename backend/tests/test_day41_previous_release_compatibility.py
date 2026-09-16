from copy import deepcopy
from pathlib import Path

from app.services.day41_previous_release_compatibility import (
    DAY41_FROZEN_PREVIOUS_RELEASE,
    DAY41_RUNTIME_SCHEMA_BOOTSTRAP,
    build_day41_previous_release_compatibility_report,
)
from scripts.run_day41_previous_release_compatibility import _python_executable_path


CANDIDATE = "a" * 40


def _inputs():
    previous_schema = {
        "users": ["id", "email", "hashed_password", "full_name", "is_active"],
        "applications": ["id", "user_id", "status"],
    }
    candidate_expected_schema = {
        "users": [
            "id",
            "email",
            "hashed_password",
            "full_name",
            "is_active",
            "automation_settings",
        ],
        "applications": ["id", "user_id", "status", "automation_state"],
        "live_pilot_authorizations": ["id", "status"],
    }
    migrated_schema = deepcopy(candidate_expected_schema)
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
        "previous_bootstrap_method": DAY41_RUNTIME_SCHEMA_BOOTSTRAP,
        "candidate_upgrade_method": DAY41_RUNTIME_SCHEMA_BOOTSTRAP,
        "previous_alembic_revision_count": 0,
        "candidate_alembic_revision_count": 0,
        "previous_bootstrap_ok": True,
        "candidate_upgrade_ok": True,
        "previous_schema": previous_schema,
        "migrated_schema": migrated_schema,
        "candidate_expected_schema": candidate_expected_schema,
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


def test_clean_frozen_v1_to_candidate_runtime_upgrade_passes():
    report = _report()

    assert report["passed"] is True
    assert report["previous_release_revision"] == DAY41_FROZEN_PREVIOUS_RELEASE
    assert report["candidate_revision"] == CANDIDATE
    assert report["previous_schema_bootstrap_method"] == DAY41_RUNTIME_SCHEMA_BOOTSTRAP
    assert report["candidate_schema_upgrade_method"] == DAY41_RUNTIME_SCHEMA_BOOTSTRAP
    assert report["previous_alembic_revision_count"] == 0
    assert report["candidate_alembic_revision_count"] == 0
    assert report["alembic_revision_chain_claimed"] is False
    assert report["missing_previous_tables"] == []
    assert report["missing_previous_columns"] == {}
    assert report["missing_candidate_tables"] == []
    assert report["missing_candidate_columns"] == {}
    assert report["live_database_touched"] is False
    assert report["synthetic_data_only"] is True
    assert report["row_contents_retained_in_report"] is False
    assert len(report["report_sha256"]) == 64


def test_wrong_previous_revision_is_rejected():
    report = _report(previous_revision="b" * 40)

    assert report["passed"] is False
    assert report["checks"]["frozen_previous_revision_exact"] is False


def test_runtime_bootstrap_contract_is_required():
    report = _report(candidate_upgrade_method="alembic_upgrade_head")

    assert report["passed"] is False
    assert report["checks"]["candidate_runtime_upgrade_exact"] is False


def test_unexpected_alembic_revision_files_are_not_silently_claimed():
    report = _report(candidate_alembic_revision_count=1)

    assert report["passed"] is False
    assert report["checks"]["candidate_has_no_alembic_revisions"] is False


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


def test_missing_candidate_table_is_rejected():
    values = _inputs()
    migrated = deepcopy(values["migrated_schema"])
    migrated.pop("live_pilot_authorizations")

    report = _report(migrated_schema=migrated)

    assert report["passed"] is False
    assert report["missing_candidate_tables"] == ["live_pilot_authorizations"]
    assert report["checks"]["all_candidate_tables_present"] is False


def test_missing_candidate_column_is_rejected():
    values = _inputs()
    migrated = deepcopy(values["migrated_schema"])
    migrated["applications"].remove("automation_state")

    report = _report(migrated_schema=migrated)

    assert report["passed"] is False
    assert report["missing_candidate_columns"] == {"applications": ["automation_state"]}
    assert report["checks"]["all_candidate_columns_present"] is False


def test_sentinel_mutation_is_rejected():
    values = _inputs()
    sentinel = deepcopy(values["sentinel_after"])
    sentinel["email"] = "changed@example.invalid"

    report = _report(sentinel_after=sentinel)

    assert report["passed"] is False
    assert report["checks"]["synthetic_user_sentinel_preserved"] is False


def test_runtime_upgrade_failure_is_blocking():
    report = _report(candidate_upgrade_ok=False)

    assert report["passed"] is False
    assert report["checks"]["candidate_runtime_upgrade_completed"] is False


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
