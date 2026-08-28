"""Strict report builder for the Day 41 frozen-v1 compatibility drill."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


DAY41_PREVIOUS_RELEASE_COMPATIBILITY_VERSION = "day41-v1-compatibility-v1"
DAY41_FROZEN_PREVIOUS_RELEASE = "6f7f9fa6a7d3c63516cde381410ac188364dba36"

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


def build_day41_previous_release_compatibility_report(
    *,
    previous_revision: Any,
    candidate_revision: Any,
    previous_database_heads: Any,
    candidate_script_heads: Any,
    candidate_database_heads: Any,
    previous_schema: Any,
    migrated_schema: Any,
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

    previous_heads = tuple(sorted(str(value) for value in (previous_database_heads or []) if str(value)))
    script_heads = tuple(sorted(str(value) for value in (candidate_script_heads or []) if str(value)))
    database_heads = tuple(sorted(str(value) for value in (candidate_database_heads or []) if str(value)))

    missing_tables = sorted(set(before) - set(after))
    missing_columns = {
        table: sorted(set(before[table]) - set(after.get(table, ())))
        for table in sorted(before)
        if set(before[table]) - set(after.get(table, ()))
    }

    sentinel_before_map = dict(sentinel_before) if isinstance(sentinel_before, Mapping) else {}
    sentinel_after_map = dict(sentinel_after) if isinstance(sentinel_after, Mapping) else {}
    sentinel_keys = ("id", "email", "hashed_password", "full_name", "is_active")
    sentinel_preserved = bool(sentinel_before_map) and all(
        sentinel_after_map.get(key) == sentinel_before_map.get(key) for key in sentinel_keys
    )

    checks = {
        "frozen_previous_revision_exact": previous == DAY41_FROZEN_PREVIOUS_RELEASE,
        "candidate_revision_valid": bool(candidate),
        "candidate_differs_from_previous_release": bool(candidate) and candidate != previous,
        "previous_database_revision_present": bool(previous_heads),
        "candidate_script_heads_present": bool(script_heads),
        "candidate_database_reaches_exact_script_heads": bool(script_heads)
        and database_heads == script_heads,
        "previous_schema_present": bool(before),
        "all_previous_tables_preserved": not missing_tables,
        "all_previous_columns_preserved": not missing_columns,
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
        "previous_database_heads": list(previous_heads),
        "candidate_script_heads": list(script_heads),
        "candidate_database_heads": list(database_heads),
        "previous_table_count": len(before),
        "migrated_table_count": len(after),
        "missing_previous_tables": missing_tables,
        "missing_previous_columns": missing_columns,
        "checks": checks,
        "passed": passed,
        "live_database_touched": False,
        "synthetic_data_only": True,
        "row_contents_retained_in_report": False,
    }
    result["report_sha256"] = _canonical_hash(result)
    return result


__all__ = [
    "DAY41_FROZEN_PREVIOUS_RELEASE",
    "DAY41_PREVIOUS_RELEASE_COMPATIBILITY_VERSION",
    "build_day41_previous_release_compatibility_report",
]
