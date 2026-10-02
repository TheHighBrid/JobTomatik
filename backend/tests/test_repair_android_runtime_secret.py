from __future__ import annotations

import stat
from pathlib import Path

from app.config import DEFAULT_SECRET_KEY
from scripts import repair_android_runtime_secret as repair


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_safe_secret_is_left_unchanged(tmp_path):
    env_file = tmp_path / ".env"
    runtime_dir = tmp_path / ".runtime"
    original = (
        "SECRET_KEY=" + ("s" * 48) + "\n"
        "ANSWER_VAULT_KEY=vault-key-already-separated\n"
        "CUSTOM_SETTING=preserve-me\n"
    )
    env_file.write_text(original, encoding="utf-8")

    result = repair.repair_android_runtime_secret(
        env_file,
        runtime_dir,
        token_factory=lambda _size: "n" * 64,
    )

    assert result["changed"] is False
    assert result["secret_key_safe"] is True
    assert env_file.read_text(encoding="utf-8") == original
    assert not (runtime_dir / "env-backups").exists()


def test_placeholder_secret_is_rotated_and_old_effective_key_is_frozen_for_vault(tmp_path):
    env_file = tmp_path / ".env"
    runtime_dir = tmp_path / ".runtime"
    original = (
        "SECRET_KEY=dev-secret-change-later\n"
        "ANSWER_VAULT_KEY=\n"
        "ALLOW_REAL_APPLICATION_SUBMIT=false\n"
        "LEVER_SUPERVISED_PILOT_ENABLED=false\n"
        "CUSTOM_SETTING=preserve-me\n"
    )
    env_file.write_text(original, encoding="utf-8")
    env_file.chmod(0o644)

    result = repair.repair_android_runtime_secret(
        env_file,
        runtime_dir,
        token_factory=lambda _size: "n" * 64,
    )

    content = env_file.read_text(encoding="utf-8")
    assert result["changed"] is True
    assert "SECRET_KEY=" + ("n" * 64) in content
    assert "ANSWER_VAULT_KEY=dev-secret-change-later" in content
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in content
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in content
    assert "CUSTOM_SETTING=preserve-me" in content
    assert _mode(env_file) == 0o600

    backup_path = result["backup_path"]
    assert isinstance(backup_path, Path)
    assert backup_path.is_file()
    assert backup_path.read_text(encoding="utf-8") == original
    assert _mode(backup_path) == 0o600


def test_existing_answer_vault_key_is_never_replaced(tmp_path):
    env_file = tmp_path / ".env"
    runtime_dir = tmp_path / ".runtime"
    env_file.write_text(
        "SECRET_KEY=supersecretkey-change-in-production\n"
        "ANSWER_VAULT_KEY=keep-this-existing-vault-key\n",
        encoding="utf-8",
    )

    repair.repair_android_runtime_secret(
        env_file,
        runtime_dir,
        token_factory=lambda _size: "z" * 64,
    )

    content = env_file.read_text(encoding="utf-8")
    assert "SECRET_KEY=" + ("z" * 64) in content
    assert "ANSWER_VAULT_KEY=keep-this-existing-vault-key" in content


def test_missing_env_preserves_the_historical_default_as_effective_vault_key(tmp_path):
    env_file = tmp_path / ".env"
    runtime_dir = tmp_path / ".runtime"

    result = repair.repair_android_runtime_secret(
        env_file,
        runtime_dir,
        token_factory=lambda _size: "q" * 64,
    )

    content = env_file.read_text(encoding="utf-8")
    assert result["changed"] is True
    assert "SECRET_KEY=" + ("q" * 64) in content
    assert f"ANSWER_VAULT_KEY={DEFAULT_SECRET_KEY}" in content
    assert _mode(env_file) == 0o600


def test_migration_is_idempotent_after_first_rotation(tmp_path):
    env_file = tmp_path / ".env"
    runtime_dir = tmp_path / ".runtime"
    env_file.write_text(
        "SECRET_KEY=dev-secret-change-later\nANSWER_VAULT_KEY=\n",
        encoding="utf-8",
    )

    first = repair.repair_android_runtime_secret(
        env_file,
        runtime_dir,
        token_factory=lambda _size: "r" * 64,
    )
    after_first = env_file.read_text(encoding="utf-8")
    second = repair.repair_android_runtime_secret(
        env_file,
        runtime_dir,
        token_factory=lambda _size: "x" * 64,
    )

    assert first["changed"] is True
    assert second["changed"] is False
    assert env_file.read_text(encoding="utf-8") == after_first
    assert "SECRET_KEY=" + ("r" * 64) in after_first
    assert "ANSWER_VAULT_KEY=dev-secret-change-later" in after_first


def test_generated_secret_must_itself_be_safe(tmp_path):
    env_file = tmp_path / ".env"
    runtime_dir = tmp_path / ".runtime"
    env_file.write_text("SECRET_KEY=dev-secret-change-later\n", encoding="utf-8")

    try:
        repair.repair_android_runtime_secret(
            env_file,
            runtime_dir,
            token_factory=lambda _size: "short",
        )
    except RuntimeError as exc:
        assert str(exc) == "ANDROID_RUNTIME_SECRET_GENERATION_FAILED"
    else:
        raise AssertionError("unsafe generated secret was accepted")

    assert env_file.read_text(encoding="utf-8") == "SECRET_KEY=dev-secret-change-later\n"
