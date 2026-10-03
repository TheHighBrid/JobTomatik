#!/usr/bin/env python3
"""Prepare and verify isolated local state for the Lever promotion-evidence lane.

This module never arms a pilot or authorizes submission. It creates a point-in-time
copy of the frozen Android SQLite database, carries forward the canonical local Lever
Phase B ledger, rewrites mutable filesystem paths into the promotion worktree, and
forces consequential runtime switches off.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil

CHROMIUM_TRANSIENT_SINGLETON_NAMES = {
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
}
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

PROMOTION_DB_NAME = "jobtomatik-promotion.db"
SAFE_ENV_VALUES = {
    "ALLOW_REAL_APPLICATION_SUBMIT": "false",
    "ALLOW_REAL_FOLLOWUP_SEND": "false",
    "AUTOPILOT_ENABLED": "false",
    "GREENHOUSE_SUPERVISED_PILOT_ENABLED": "false",
    "LEVER_SUPERVISED_PILOT_ENABLED": "false",
    "JOBTOMATIK_BROWSER_NODE_ID": "promotion-evidence-node",
}
ISOLATED_ENV_PATHS = {
    "UPLOAD_DIR": ".promotion-state/uploads",
    "HANDOFF_STORAGE_DIR": ".promotion-state/handoff_sessions",
    "APPLICATION_BROWSER_PROFILE_DIR": ".promotion-state/browser_profiles/jobtomatik-operator",
    "GREENHOUSE_PILOT_LEDGER_PATH": ".promotion-state/evidence/greenhouse-pilot-ledger.jsonl",
    "GREENHOUSE_PILOT_READINESS_JSON_PATH": ".promotion-state/evidence/greenhouse-pilot-readiness.json",
    "GREENHOUSE_PILOT_READINESS_MARKDOWN_PATH": ".promotion-state/evidence/greenhouse-pilot-readiness.md",
    "LEVER_PILOT_LEDGER_PATH": ".promotion-state/evidence/lever-pilot-ledger.jsonl",
    "LEVER_PILOT_READINESS_JSON_PATH": ".promotion-state/evidence/lever-pilot-readiness.json",
    "LEVER_PILOT_READINESS_MARKDOWN_PATH": ".promotion-state/evidence/lever-pilot-readiness.md",
}
CANONICAL_READ_ONLY_PATHS = {
    "GREENHOUSE_PILOT_BASELINE_PATH": "evidence/greenhouse-phase-a-baseline.csv",
    "LEVER_PILOT_BASELINE_PATH": "evidence/lever-phase-a-baseline.csv",
    "LEVER_PHASE_B_LAUNCH_PATH": "evidence/lever-phase-b-launch.json",
}
SOURCE_PATH_DEFAULTS = {
    "UPLOAD_DIR": "uploads",
    "HANDOFF_STORAGE_DIR": "handoff_sessions",
    "GREENHOUSE_PILOT_LEDGER_PATH": "evidence/greenhouse-pilot-ledger.jsonl",
    "LEVER_PILOT_LEDGER_PATH": "evidence/lever-pilot-ledger.jsonl",
}
_ENV_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


class PromotionLaneStateError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_prefix(path: Path, size: int) -> str:
    if size <= 0:
        raise PromotionLaneStateError("Promotion ledger inherited-prefix size is invalid")
    digest = hashlib.sha256()
    remaining = size
    with path.open("rb") as handle:
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise PromotionLaneStateError(
                    "Promotion Lever ledger is shorter than its retained inherited prefix"
                )
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_env_value(path: Path, key: str) -> str | None:
    wanted = key.upper()
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = _ENV_RE.match(raw)
        if not match or match.group(1).upper() != wanted:
            continue
        return _unquote(raw.split("=", 1)[1])
    return None


def set_env_value(lines: list[str], key: str, value: str) -> list[str]:
    wanted = key.upper()
    updated: list[str] = []
    replaced = False
    for raw in lines:
        match = _ENV_RE.match(raw)
        if match and match.group(1).upper() == wanted:
            if not replaced:
                updated.append(f"{key}={value}")
                replaced = True
            continue
        updated.append(raw)
    if not replaced:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append(f"{key}={value}")
    return updated


def resolve_runtime_path(backend_root: Path, raw: str | None, fallback: str) -> Path:
    candidate = Path(_unquote(raw or fallback)).expanduser()
    if not candidate.is_absolute():
        candidate = backend_root / candidate
    return candidate.resolve()


def sqlite_database_path(backend_root: Path, database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise PromotionLaneStateError(
            "Promotion lane requires the frozen Android runtime to use a file-backed SQLite database"
        )
    candidate = Path(url.database).expanduser()
    if not candidate.is_absolute():
        candidate = backend_root / candidate
    return candidate.resolve()


def backup_sqlite(source_db: Path, target_db: Path) -> None:
    if not source_db.is_file():
        raise PromotionLaneStateError(f"Frozen SQLite database is missing: {source_db}")
    if target_db.exists():
        raise PromotionLaneStateError(
            f"Refusing to overwrite existing promotion database: {target_db}"
        )
    target_db.parent.mkdir(parents=True, exist_ok=True)
    source_uri = source_db.as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(target_db) as target:
            source.backup(target)
            check = target.execute("PRAGMA quick_check").fetchone()
    except Exception:
        target_db.unlink(missing_ok=True)
        raise
    if not check or check[0] != "ok":
        target_db.unlink(missing_ok=True)
        raise PromotionLaneStateError("Promotion database snapshot failed SQLite quick_check")


def _ignore_transient_browser_singletons(_directory: str, names: list[str]) -> set[str]:
    return CHROMIUM_TRANSIENT_SINGLETON_NAMES.intersection(names)


def _copy_directory_if_present(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    if not source.is_dir():
        raise PromotionLaneStateError(f"Expected directory at {source}")
    if destination.exists():
        raise PromotionLaneStateError(f"Refusing to overwrite isolated directory: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        ignore=_ignore_transient_browser_singletons,
    )
    return True


def _copy_file_if_present(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    if not source.is_file():
        raise PromotionLaneStateError(f"Expected file at {source}")
    if destination.exists():
        raise PromotionLaneStateError(f"Refusing to overwrite isolated file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _validate_runtime_ledger(path: Path) -> list[dict]:
    backend_root = Path(__file__).resolve().parents[1]
    backend_text = str(backend_root)
    if backend_text not in sys.path:
        sys.path.insert(0, backend_text)
    from app.services.lever_pilot_ledger_boundary import validate_phase_b_runtime_ledger

    return validate_phase_b_runtime_ledger(path)


def _validated_lever_ledger(path: Path) -> list[dict]:
    if not path.is_file():
        raise PromotionLaneStateError(
            "Frozen Lever Phase B runtime ledger is missing; refusing to create a promotion lane that loses retained confirmation evidence"
        )
    records = _validate_runtime_ledger(path)
    if not records:
        raise PromotionLaneStateError(
            "Frozen Lever Phase B runtime ledger contains no valid supervised confirmation records"
        )
    return records


def _write_promotion_env(source_env: Path, promotion_env: Path) -> dict[str, str]:
    shutil.copy2(source_env, promotion_env)
    lines = promotion_env.read_text(encoding="utf-8").splitlines()
    values = {
        "DATABASE_URL": f"sqlite:///./{PROMOTION_DB_NAME}",
        **SAFE_ENV_VALUES,
        **ISOLATED_ENV_PATHS,
        **CANONICAL_READ_ONLY_PATHS,
    }
    for key, value in values.items():
        lines = set_env_value(lines, key, value)
    promotion_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    promotion_env.chmod(0o600)
    return values


def _copy_optional_runtime_state(
    source_backend: Path,
    promotion_backend: Path,
    source_env: Path,
) -> dict[str, bool]:
    copied: dict[str, bool] = {}
    source_uploads = resolve_runtime_path(
        source_backend,
        read_env_value(source_env, "UPLOAD_DIR"),
        SOURCE_PATH_DEFAULTS["UPLOAD_DIR"],
    )
    copied["uploads"] = _copy_directory_if_present(
        source_uploads,
        promotion_backend / ISOLATED_ENV_PATHS["UPLOAD_DIR"],
    )
    source_handoffs = resolve_runtime_path(
        source_backend,
        read_env_value(source_env, "HANDOFF_STORAGE_DIR"),
        SOURCE_PATH_DEFAULTS["HANDOFF_STORAGE_DIR"],
    )
    copied["handoffs"] = _copy_directory_if_present(
        source_handoffs,
        promotion_backend / ISOLATED_ENV_PATHS["HANDOFF_STORAGE_DIR"],
    )
    source_greenhouse_ledger = resolve_runtime_path(
        source_backend,
        read_env_value(source_env, "GREENHOUSE_PILOT_LEDGER_PATH"),
        SOURCE_PATH_DEFAULTS["GREENHOUSE_PILOT_LEDGER_PATH"],
    )
    copied["greenhouse_ledger"] = _copy_file_if_present(
        source_greenhouse_ledger,
        promotion_backend / ISOLATED_ENV_PATHS["GREENHOUSE_PILOT_LEDGER_PATH"],
    )
    return copied


def _promotion_paths(source_repo: Path, promotion_repo: Path) -> tuple[Path, Path, Path, Path]:
    source_backend = source_repo.resolve() / "backend"
    promotion_backend = promotion_repo.resolve() / "backend"
    source_env = source_backend / ".env"
    promotion_env = promotion_backend / ".env"
    if not source_env.is_file():
        raise PromotionLaneStateError(f"Frozen backend .env is missing: {source_env}")
    return source_backend, promotion_backend, source_env, promotion_env


def _snapshot_required_state(
    source_backend: Path,
    promotion_backend: Path,
    source_env: Path,
) -> tuple[Path, Path, list[dict]]:
    database_url = read_env_value(source_env, "DATABASE_URL") or "sqlite:///./jobtomatik.db"
    source_db = sqlite_database_path(source_backend, database_url)
    target_db = promotion_backend / PROMOTION_DB_NAME
    backup_sqlite(source_db, target_db)

    source_ledger = resolve_runtime_path(
        source_backend,
        read_env_value(source_env, "LEVER_PILOT_LEDGER_PATH"),
        SOURCE_PATH_DEFAULTS["LEVER_PILOT_LEDGER_PATH"],
    )
    records = _validated_lever_ledger(source_ledger)
    promotion_ledger = promotion_backend / ISOLATED_ENV_PATHS["LEVER_PILOT_LEDGER_PATH"]
    _copy_file_if_present(source_ledger, promotion_ledger)
    return target_db, promotion_ledger, records


def _promotion_marker(
    *,
    source_revision: str,
    target_revision: str,
    target_db: Path,
    promotion_ledger: Path,
    records: list[dict],
    copied_state: dict[str, bool],
    env_values: dict[str, str],
) -> dict:
    return {
        "version": 3,
        "lane": "lever_promotion_evidence",
        "source_frozen_revision": source_revision,
        "target_revision": target_revision,
        "promotion_database": PROMOTION_DB_NAME,
        "promotion_database_sha256": sha256_file(target_db),
        "initial_lever_ledger_record_count": len(records),
        "initial_lever_ledger_size_bytes": promotion_ledger.stat().st_size,
        "initial_lever_ledger_sha256": sha256_file(promotion_ledger),
        "prepared_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "safety_flags": SAFE_ENV_VALUES,
        "isolated_env_paths": ISOLATED_ENV_PATHS,
        "canonical_read_only_paths": CANONICAL_READ_ONLY_PATHS,
        "copied_optional_state": copied_state,
        "browser_profile_policy": "separate_native_profile_required",
        "browser_node_id": env_values["JOBTOMATIK_BROWSER_NODE_ID"],
        "final_submit_authority_created": False,
    }


def prepare_state(
    *,
    source_repo: Path,
    promotion_repo: Path,
    source_revision: str,
    target_revision: str,
) -> dict:
    source_backend, promotion_backend, source_env, promotion_env = _promotion_paths(
        source_repo,
        promotion_repo,
    )
    target_db, promotion_ledger, records = _snapshot_required_state(
        source_backend,
        promotion_backend,
        source_env,
    )
    copied_state = _copy_optional_runtime_state(source_backend, promotion_backend, source_env)
    env_values = _write_promotion_env(source_env, promotion_env)
    runtime_dir = promotion_backend / ".runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    marker = _promotion_marker(
        source_revision=source_revision,
        target_revision=target_revision,
        target_db=target_db,
        promotion_ledger=promotion_ledger,
        records=records,
        copied_state=copied_state,
        env_values=env_values,
    )
    (runtime_dir / "promotion-lane.json").write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return marker


def _assert_env_values(env_file: Path, expected: dict[str, str]) -> None:
    for key, value in expected.items():
        observed = read_env_value(env_file, key)
        if observed != value:
            raise PromotionLaneStateError(
                f"Promotion environment drift for {key}: expected {value!r}, observed {observed!r}"
            )


def _load_promotion_marker(
    promotion_backend: Path,
    expected_frozen_revision: str,
    expected_target_revision: str,
) -> dict:
    marker_path = promotion_backend / ".runtime/promotion-lane.json"
    if not marker_path.is_file():
        raise PromotionLaneStateError("Promotion lane marker is missing")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if marker.get("source_frozen_revision") != expected_frozen_revision:
        raise PromotionLaneStateError(
            "Promotion lane was not derived from the expected frozen revision"
        )
    if marker.get("target_revision") != expected_target_revision:
        raise PromotionLaneStateError(
            "Promotion lane target revision does not match the worktree revision"
        )
    return marker


def _verify_promotion_database(promotion_backend: Path, marker: dict) -> None:
    db = promotion_backend / str(marker.get("promotion_database") or "")
    if not db.is_file():
        raise PromotionLaneStateError("Promotion lane database is missing")
    with sqlite3.connect(db) as connection:
        check = connection.execute("PRAGMA quick_check").fetchone()
    if not check or check[0] != "ok":
        raise PromotionLaneStateError("Promotion lane database failed SQLite quick_check")


def _expected_promotion_env() -> dict[str, str]:
    return {
        "DATABASE_URL": f"sqlite:///./{PROMOTION_DB_NAME}",
        **SAFE_ENV_VALUES,
        **ISOLATED_ENV_PATHS,
        **CANONICAL_READ_ONLY_PATHS,
    }


def _verify_inherited_ledger_prefix(ledger: Path, marker: dict) -> None:
    initial_size = int(marker.get("initial_lever_ledger_size_bytes") or 0)
    expected_digest = str(marker.get("initial_lever_ledger_sha256") or "")
    if initial_size <= 0 or not expected_digest:
        raise PromotionLaneStateError(
            "Promotion lane marker lacks inherited Lever ledger integrity metadata; rebuild the lane"
        )
    observed_digest = _sha256_prefix(ledger, initial_size)
    if observed_digest != expected_digest:
        raise PromotionLaneStateError(
            "Promotion Lever ledger inherited confirmation evidence was replaced or mutated"
        )


def _verify_promotion_ledger(promotion_backend: Path, marker: dict) -> tuple[list[dict], int]:
    ledger = promotion_backend / ISOLATED_ENV_PATHS["LEVER_PILOT_LEDGER_PATH"]
    if not ledger.is_file():
        raise PromotionLaneStateError("Promotion Lever ledger is missing")
    _verify_inherited_ledger_prefix(ledger, marker)
    records = _validated_lever_ledger(ledger)
    initial_count = int(marker.get("initial_lever_ledger_record_count") or 0)
    if len(records) < initial_count:
        raise PromotionLaneStateError(
            "Promotion Lever ledger lost retained confirmation evidence after preparation"
        )
    return records, initial_count


def verify_state(
    *,
    promotion_repo: Path,
    expected_frozen_revision: str,
    expected_target_revision: str,
) -> dict:
    promotion_backend = promotion_repo.resolve() / "backend"
    marker = _load_promotion_marker(
        promotion_backend,
        expected_frozen_revision,
        expected_target_revision,
    )
    _verify_promotion_database(promotion_backend, marker)
    _assert_env_values(promotion_backend / ".env", _expected_promotion_env())
    records, initial_count = _verify_promotion_ledger(promotion_backend, marker)
    return {
        "ok": True,
        "target_revision": expected_target_revision,
        "lever_ledger_record_count": len(records),
        "initial_lever_ledger_record_count": initial_count,
        "database_quick_check": "ok",
        "persistent_submit_flags_off": True,
        "isolated_env_paths_verified": True,
        "inherited_lever_ledger_prefix_verified": True,
    }


def _path(value: str) -> Path:
    return Path(value).expanduser()


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--source-repo", type=_path, required=True)
    prepare.add_argument("--promotion-repo", type=_path, required=True)
    prepare.add_argument("--source-revision", required=True)
    prepare.add_argument("--target-revision", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--promotion-repo", type=_path, required=True)
    verify.add_argument("--expected-frozen-revision", required=True)
    verify.add_argument("--expected-target-revision", required=True)
    args = parser.parse_args()

    if args.command == "prepare":
        result = prepare_state(
            source_repo=args.source_repo,
            promotion_repo=args.promotion_repo,
            source_revision=args.source_revision,
            target_revision=args.target_revision,
        )
    else:
        result = verify_state(
            promotion_repo=args.promotion_repo,
            expected_frozen_revision=args.expected_frozen_revision,
            expected_target_revision=args.expected_target_revision,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
