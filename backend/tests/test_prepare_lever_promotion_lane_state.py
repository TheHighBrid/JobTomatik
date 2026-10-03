from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts/prepare_lever_promotion_lane_state.py"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _require_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def _load_module():
    spec = importlib.util.spec_from_file_location("prepare_lever_promotion_lane_state", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load promotion lane state module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_db(path: Path, value: str = "frozen") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE proof (value TEXT NOT NULL)")
        connection.execute("INSERT INTO proof(value) VALUES (?)", (value,))
        connection.commit()


def _read_db_value(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT value FROM proof").fetchone()
    if row is None:
        raise AssertionError(f"Expected proof row in {path}")
    return str(row[0])


def _write_source_env(source_backend: Path, paths: dict[str, Path]) -> Path:
    source_env = source_backend / ".env"
    source_env.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite:///./jobtomatik.db",
                f"UPLOAD_DIR={paths['uploads']}",
                f"HANDOFF_STORAGE_DIR={paths['handoffs']}",
                f"LEVER_PILOT_LEDGER_PATH={paths['lever_ledger']}",
                f"GREENHOUSE_PILOT_LEDGER_PATH={paths['greenhouse_ledger']}",
                "ALLOW_REAL_APPLICATION_SUBMIT=true",
                "ALLOW_REAL_FOLLOWUP_SEND=true",
                "AUTOPILOT_ENABLED=true",
                "GREENHOUSE_SUPERVISED_PILOT_ENABLED=true",
                "LEVER_SUPERVISED_PILOT_ENABLED=true",
                "JOBTOMATIK_BROWSER_NODE_ID=local-node",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return source_env


def _create_source_state(tmp_path: Path, source_backend: Path) -> tuple[dict[str, Path], Path]:
    uploads = tmp_path / "absolute-source-uploads"
    uploads.mkdir()
    (uploads / "resume_1.pdf").write_bytes(b"pdf")
    handoffs = tmp_path / "absolute-source-handoffs"
    handoffs.mkdir()
    (handoffs / "retained.json").write_text("{}\n", encoding="utf-8")
    lever_ledger = tmp_path / "absolute-source-lever-ledger.jsonl"
    lever_ledger.write_text('{"mode":"supervised","specimen":"maple"}\n', encoding="utf-8")
    greenhouse_ledger = tmp_path / "absolute-source-greenhouse-ledger.jsonl"
    greenhouse_ledger.write_text('{"mode":"supervised"}\n', encoding="utf-8")
    paths = {
        "uploads": uploads,
        "handoffs": handoffs,
        "lever_ledger": lever_ledger,
        "greenhouse_ledger": greenhouse_ledger,
    }
    return paths, _write_source_env(source_backend, paths)


def _verify_prepared_state(module, source_env: Path, promotion_backend: Path, paths: dict[str, Path], marker: dict) -> Path:
    promotion_db = promotion_backend / module.PROMOTION_DB_NAME
    _require_equal(_read_db_value(promotion_db), "frozen", "promotion database snapshot")
    _require_equal(marker["initial_lever_ledger_record_count"], 1, "initial Lever ledger count")
    _require(marker["initial_lever_ledger_size_bytes"] > 0, "Initial ledger byte size must be retained")
    _require_equal(marker["final_submit_authority_created"], False, "submit authority marker")

    promotion_env = promotion_backend / ".env"
    _require_equal(module.read_env_value(promotion_env, "ALLOW_REAL_APPLICATION_SUBMIT"), "false", "real submit flag")
    _require_equal(module.read_env_value(promotion_env, "ALLOW_REAL_FOLLOWUP_SEND"), "false", "follow-up flag")
    _require_equal(module.read_env_value(promotion_env, "AUTOPILOT_ENABLED"), "false", "autopilot flag")
    _require_equal(module.read_env_value(promotion_env, "LEVER_SUPERVISED_PILOT_ENABLED"), "false", "Lever pilot flag")
    _require_equal(module.read_env_value(promotion_env, "JOBTOMATIK_BROWSER_NODE_ID"), "promotion-evidence-node", "browser node")
    _require_equal(module.read_env_value(promotion_env, "UPLOAD_DIR"), ".promotion-state/uploads", "upload path")
    _require_equal(module.read_env_value(promotion_env, "HANDOFF_STORAGE_DIR"), ".promotion-state/handoff_sessions", "handoff path")
    _require_equal(module.read_env_value(promotion_env, "LEVER_PILOT_LEDGER_PATH"), ".promotion-state/evidence/lever-pilot-ledger.jsonl", "Lever ledger path")

    _require_equal((promotion_backend / ".promotion-state/uploads/resume_1.pdf").read_bytes(), b"pdf", "copied upload")
    _require((promotion_backend / ".promotion-state/handoff_sessions/retained.json").is_file(), "Retained handoff must be copied")
    copied_ledger = promotion_backend / ".promotion-state/evidence/lever-pilot-ledger.jsonl"
    _require_equal(copied_ledger.read_bytes(), paths["lever_ledger"].read_bytes(), "copied Lever ledger")
    _require_equal(module.read_env_value(source_env, "ALLOW_REAL_APPLICATION_SUBMIT"), "true", "frozen submit flag")
    _require_equal(module.read_env_value(source_env, "UPLOAD_DIR"), str(paths["uploads"]), "frozen upload path")
    return copied_ledger


def _prepared_lane(tmp_path: Path, monkeypatch):
    module = _load_module()
    source_repo = tmp_path / "frozen"
    promotion_repo = tmp_path / "promotion"
    source_backend = source_repo / "backend"
    promotion_backend = promotion_repo / "backend"
    source_backend.mkdir(parents=True)
    promotion_backend.mkdir(parents=True)
    source_db = source_backend / "jobtomatik.db"
    _write_db(source_db)
    paths, source_env = _create_source_state(tmp_path, source_backend)
    monkeypatch.setattr(
        module,
        "_validate_runtime_ledger",
        lambda path: [{"mode": "supervised"} for line in path.read_text().splitlines() if line],
    )
    marker = module.prepare_state(
        source_repo=source_repo,
        promotion_repo=promotion_repo,
        source_revision="a" * 40,
        target_revision="b" * 40,
    )
    copied_ledger = _verify_prepared_state(module, source_env, promotion_backend, paths, marker)
    return module, source_db, promotion_repo, copied_ledger


def test_copy_directory_skips_transient_chromium_singletons_but_keeps_session_data(tmp_path):
    module = _load_module()
    source = tmp_path / "handoffs"
    destination = tmp_path / "promotion-handoffs"
    profile = source / "session-1" / "profile"
    profile.mkdir(parents=True)
    (source / "session-1" / "metadata.json").write_text('{"kept": true}\n', encoding="utf-8")
    (profile / "Preferences").write_text('{"profile": true}\n', encoding="utf-8")

    for name in module.CHROMIUM_TRANSIENT_SINGLETON_NAMES:
        (profile / name).symlink_to(tmp_path / f"missing-{name}")

    _require_equal(
        module._copy_directory_if_present(source, destination),
        True,
        "handoff directory copied",
    )
    _require((destination / "session-1/metadata.json").is_file(), "Handoff metadata must be retained")
    _require((destination / "session-1/profile/Preferences").is_file(), "Durable browser profile data must be retained")
    for name in module.CHROMIUM_TRANSIENT_SINGLETON_NAMES:
        _require(
            not (destination / "session-1/profile" / name).exists(),
            f"Transient Chromium singleton {name} must not be copied",
        )


def test_prepare_state_snapshots_sqlite_and_rehomes_mutable_paths(tmp_path, monkeypatch):
    module, source_db, promotion_repo, copied_ledger = _prepared_lane(tmp_path, monkeypatch)
    _require_equal(_read_db_value(source_db), "frozen", "source database")
    copied_ledger.write_text(
        copied_ledger.read_text(encoding="utf-8") + '{"mode":"supervised","specimen":"second"}\n',
        encoding="utf-8",
    )
    verified = module.verify_state(
        promotion_repo=promotion_repo,
        expected_frozen_revision="a" * 40,
        expected_target_revision="b" * 40,
    )
    _require_equal(verified["ok"], True, "verification result")
    _require_equal(verified["lever_ledger_record_count"], 2, "verified Lever ledger count")
    _require_equal(verified["initial_lever_ledger_record_count"], 1, "verified initial count")
    _require_equal(verified["inherited_lever_ledger_prefix_verified"], True, "inherited prefix proof")


def test_verify_state_rejects_replaced_inherited_lever_confirmation_prefix(tmp_path, monkeypatch):
    module, _, promotion_repo, copied_ledger = _prepared_lane(tmp_path, monkeypatch)
    copied_ledger.write_text(
        '{"mode":"supervised","specimen":"replacement"}\n'
        '{"mode":"supervised","specimen":"second"}\n',
        encoding="utf-8",
    )

    with pytest.raises(module.PromotionLaneStateError, match="inherited confirmation evidence"):
        module.verify_state(
            promotion_repo=promotion_repo,
            expected_frozen_revision="a" * 40,
            expected_target_revision="b" * 40,
        )


def test_prepare_state_refuses_to_drop_missing_lever_confirmation_ledger(tmp_path, monkeypatch):
    module = _load_module()
    source_repo = tmp_path / "frozen"
    promotion_repo = tmp_path / "promotion"
    source_backend = source_repo / "backend"
    promotion_backend = promotion_repo / "backend"
    source_backend.mkdir(parents=True)
    promotion_backend.mkdir(parents=True)
    _write_db(source_backend / "jobtomatik.db")
    (source_backend / ".env").write_text(
        "DATABASE_URL=sqlite:///./jobtomatik.db\n"
        "LEVER_PILOT_LEDGER_PATH=evidence/missing-ledger.jsonl\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_validate_runtime_ledger", lambda path: [])

    with pytest.raises(module.PromotionLaneStateError, match="ledger is missing"):
        module.prepare_state(
            source_repo=source_repo,
            promotion_repo=promotion_repo,
            source_revision="a" * 40,
            target_revision="b" * 40,
        )


def test_backup_sqlite_refuses_to_overwrite_existing_promotion_database(tmp_path):
    module = _load_module()
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _write_db(source, "source")
    _write_db(target, "existing")

    with pytest.raises(module.PromotionLaneStateError, match="Refusing to overwrite"):
        module.backup_sqlite(source, target)
    _require_equal(_read_db_value(target), "existing", "existing promotion database")
