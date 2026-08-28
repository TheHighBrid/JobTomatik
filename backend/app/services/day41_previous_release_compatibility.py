"""Strict report builder for the Day 41 frozen-v1 runtime-schema compatibility drill."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


DAY41_PREVIOUS_RELEASE_COMPATIBILITY_VERSION = "day41-v1-runtime-schema-compatibility-v2"
DAY41_FROZEN_PREVIOUS_RELEASE = "6f7f9fa6a7d3c63516cde381410ac188364dba36"
DAY41_RUNTIME_SCHEMA_BOOTSTRAP = "orm_create_all_plus_safe_migrate"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _sha40(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _SHA40.fullmatch(text) else ""


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _schema(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for table, columns in value.items():
        if not isinstance(columns, Sequence) or isinstance(columns, (str, bytes)):
            continue
        result[str(table)] = tuple(sorted({str(column) for column in columns}))
    return result


def _missing_schema(
    required: Mapping[str, tuple[str, ...]],
    actual: Mapping[str, tuple[str, ...]],
) -> tuple[list[str], dict[str, list[str]]]:
    missing_tables = sorted(set(required) - set(actual))
    missing_columns = {
        table: sorted(set(required[table]) - set(actual.get(table, ())))
        for table in sorted(required)
        if set(required[table]) - set(actual.get(table, ()))
    }
    return missing_tables, missing_columns


def build_day41_previous_release_compatibility_report(
    *,
    previous_revision: Any,
    candidate_revision: Any,
    previous_bootstrap_method: Any,
    candidate_upgrade_method: Any,
    previous_alembic_revision_count: Any,
    candidate_alembic_revision_count: Any,
    previous_bootstrap_ok: Any,
    candidate_upgrade_ok: Any,
    previous_schema: Any,
    migrated_schema: Any,
    candidate_expected_schema: Any,
    sentinel_before: Any,
    sentinel_after: Any,
    sqlite_integrity_ok: Any,
    foreign_keys_ok: Any,
    current_orm_probe_ok: Any,
) -> dict[str, Any]:
    previous = _sha40(previous_revision)
    candidate = _sha40(candidate_revision)
    before = _schema(previous_schema)
    after = _schema(migrated_schema)
    expected = _schema(candidate_expected_schema)

    missing_previous_tables, missing_previous_columns = _missing_schema(before, after)
    missing_candidate_tables, missing_candidate_columns = _missing_schema(expected, after)

    sentinel_before_map = dict(sentinel_before) if isinstance(sentinel_before, Mapping) else {}
    sentinel_after_map = dict(sentinel_after) if isinstance(sentinel_after, Mapping) else {}
    sentinel_keys = ("id", "email", "hashed_password", "full_name", "is_active")
    sentinel_preserved = bool(sentinel_before_map) and all(
        sentinel_after_map.get(key) == sentinel_before_map.get(key) for key in sentinel_keys
    )

    previous_method = str(previous_bootstrap_method or "").strip()
    candidate_method = str(candidate_upgrade_method or "").strip()
    try:
        previous_revision_count = int(previous_alembic_revision_count)
    except (TypeError, ValueError):
        previous_revision_count = -1
    try:
        candidate_revision_count = int(candidate_alembic_revision_count)
    except (TypeError, ValueError):
        candidate_revision_count = -1

    checks = {
        "frozen_previous_revision_exact": previous == DAY41_FROZEN_PREVIOUS_RELEASE,
        "candidate_revision_valid": bool(candidate),
        "candidate_differs_from_previous_release": bool(candidate) and candidate != previous,
        "previous_runtime_bootstrap_exact": previous_method == DAY41_RUNTIME_SCHEMA_BOOTSTRAP,
        "candidate_runtime_upgrade_exact": candidate_method == DAY41_RUNTIME_SCHEMA_BOOTSTRAP,
        "previous_release_has_no_alembic_revisions": previous_revision_count == 0,
        "candidate_has_no_alembic_revisions": candidate_revision_count == 0,
        "previous_runtime_bootstrap_completed": previous_bootstrap_ok is True,
        "candidate_runtime_upgrade_completed": candidate_upgrade_ok is True,
        "previous_schema_present": bool(before),
        "candidate_expected_schema_present": bool(expected),
        "all_previous_tables_preserved": not missing_previous_tables,
        "all_previous_columns_preserved": not missing_previous_columns,
        "all_candidate_tables_present": not missing_candidate_tables,
        "all_candidate_columns_present": not missing_candidate_columns,
        "synthetic_user_sentinel_preserved": sentinel_preserved,
        "sqlite_integrity_ok": sqlite_integrity_ok is True,
        "foreign_keys_ok": foreign_keys_ok is True,
        "current_orm_can_read_migrated_v1_row": current_orm_probe_ok is True,
    }
    passed = all(checks.values())

    result: dict[str, Any] = {
        "version": DAY41_PREVIOUS_RELEASE_COMPATIBILITY_VERSION,
        "previous_release_revision": previous or None,
        "candidate_revision": candidate or None,
        "previous_schema_bootstrap_method": previous_method or None,
        "candidate_schema_upgrade_method": candidate_method or None,
        "previous_alembic_revision_count": previous_revision_count,
        "candidate_alembic_revision_count": candidate_revision_count,
        "previous_table_count": len(before),
        "migrated_table_count": len(after),
        "candidate_expected_table_count": len(expected),
        "missing_previous_tables": missing_previous_tables,
        "missing_previous_columns": missing_previous_columns,
        "missing_candidate_tables": missing_candidate_tables,
        "missing_candidate_columns": missing_candidate_columns,
        "checks": checks,
        "passed": passed,
        "live_database_touched": False,
        "synthetic_data_only": True,
        "row_contents_retained_in_report": False,
        "alembic_revision_chain_claimed": False,
    }
    result["report_sha256"] = _canonical_hash(result)
    return result


__all__ = [
    "DAY41_FROZEN_PREVIOUS_RELEASE",
    "DAY41_PREVIOUS_RELEASE_COMPATIBILITY_VERSION",
    "DAY41_RUNTIME_SCHEMA_BOOTSTRAP",
    "build_day41_previous_release_compatibility_report",
]
