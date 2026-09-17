from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts/prepare_lever_promotion_lane_state.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("prepare_lever_promotion_lane_state", SCRIPT)
    assert spec and spec.loader
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
    assert row
    return str(row[0])


def test_prepare_state_snapshots_sqlite_and_rehomes_mutable_paths(tmp_path, monkeypatch):
    module = _load_module()
    source_repo = tmp_path / "frozen"
    promotion_repo = tmp_path / "promotion"
    source_backend = source_repo / "backend"
    promotion_backend = promotion_repo / "backend"
    source_backend.mkdir(parents=True)
    promotion_backend.mkdir(parents=True)

    source_db = source_backend / "jobtomatik.db"
    _write_db(source_db)

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

    source_env = source_backend / ".env"
    source_env.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite:///./jobtomatik.db",
                f"UPLOAD_DIR={uploads}",
                f"HANDOFF_STORAGE_DIR={handoffs}",
                f"LEVER_PILOT_LEDGER_PATH={lever_ledger}",
                f"GREENHOUSE_PILOT_LEDGER_PATH={greenhouse_ledger}",
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

    promotion_db = promotion_backend / module.PROMOTION_DB_NAME
    assert _read_db_value(source_db) == "frozen"
    assert _read_db_value(promotion_db) == "frozen"
    assert marker["initial_lever_ledger_record_count"] == 1
    assert marker["final_submit_authority_created"] is False

    promotion_env = promotion_backend / ".env"
    assert module.read_env_value(promotion_env, "ALLOW_REAL_APPLICATION_SUBMIT") == "false"
    assert module.read_env_value(promotion_env, "ALLOW_REAL_FOLLOWUP_SEND") == "false"
    assert module.read_env_value(promotion_env, "AUTOPILOT_ENABLED") == "false"
    assert module.read_env_value(promotion_env, "LEVER_SUPERVISED_PILOT_ENABLED") == "false"
    assert module.read_env_value(promotion_env, "JOBTOMATIK_BROWSER_NODE_ID") == "promotion-evidence-node"
    assert module.read_env_value(promotion_env, "UPLOAD_DIR") == ".promotion-state/uploads"
    assert module.read_env_value(promotion_env, "HANDOFF_STORAGE_DIR") == ".promotion-state/handoff_sessions"
    assert module.read_env_value(promotion_env, "LEVER_PILOT_LEDGER_PATH") == ".promotion-state/evidence/lever-pilot-ledger.jsonl"

    assert (promotion_backend / ".promotion-state/uploads/resume_1.pdf").read_bytes() == b"pdf"
    assert (promotion_backend / ".promotion-state/handoff_sessions/retained.json").is_file()
    copied_ledger = promotion_backend / ".promotion-state/evidence/lever-pilot-ledger.jsonl"
    assert copied_ledger.read_bytes() == lever_ledger.read_bytes()
    assert module.read_env_value(source_env, "ALLOW_REAL_APPLICATION_SUBMIT") == "true"
    assert module.read_env_value(source_env, "UPLOAD_DIR") == str(uploads)

    copied_ledger.write_text(
        copied_ledger.read_text(encoding="utf-8") + '{"mode":"supervised","specimen":"second"}\n',
        encoding="utf-8",
    )
    verified = module.verify_state(
        promotion_repo=promotion_repo,
        expected_frozen_revision="a" * 40,
        expected_target_revision="b" * 40,
    )
    assert verified["ok"] is True
    assert verified["lever_ledger_record_count"] == 2
    assert verified["initial_lever_ledger_record_count"] == 1


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
    assert _read_db_value(target) == "existing"
