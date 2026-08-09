from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.services.certification_scale import current_revision as certification_revision
from app.services.runtime_identity import current_revision, runtime_identity_manifest


REVISION = "a" * 40
OTHER_REVISION = "b" * 40


def _clear_identity_env(monkeypatch):
    for name in (
        "JOBTOMATIK_RUNTIME_REVISION",
        "JOBTOMATIK_EXPECTED_REVISION",
        "JOBTOMATIK_RUNTIME_ROLE",
        "JOBTOMATIK_OPERATIONS_ENV_FILE",
        "GITHUB_SHA",
        "APP_ENV",
        "APP_ENVIRONMENT",
        "SECRET_KEY",
        "AUTOPILOT_ENABLED",
        "ALLOW_REAL_APPLICATION_SUBMIT",
        "ALLOW_REAL_FOLLOWUP_SEND",
        "GREENHOUSE_SUPERVISED_PILOT_ENABLED",
        "LEVER_SUPERVISED_PILOT_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_explicit_revision_and_expected_revision_attest(monkeypatch):
    _clear_identity_env(monkeypatch)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")

    manifest = runtime_identity_manifest()

    assert current_revision() == REVISION
    assert certification_revision() == REVISION
    assert manifest["revision"] == REVISION
    assert manifest["source"] == "JOBTOMATIK_RUNTIME_REVISION"
    assert manifest["role"] == "worker"
    assert manifest["known"] is True
    assert manifest["expected_valid"] is True
    assert manifest["matches_expected"] is True
    assert manifest["deployment_attested"] is True
    assert len(manifest["identity_sha256"]) == 64
    assert manifest["submission_authorized"] is False
    assert manifest["outreach_authorized"] is False


def test_mismatched_expected_revision_fails_attestation(monkeypatch):
    _clear_identity_env(monkeypatch)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", OTHER_REVISION)

    manifest = runtime_identity_manifest()

    assert certification_revision() == REVISION
    assert manifest["known"] is True
    assert manifest["expected_valid"] is True
    assert manifest["matches_expected"] is False
    assert manifest["deployment_attested"] is False


def test_malformed_expected_revision_fails_attestation(monkeypatch):
    _clear_identity_env(monkeypatch)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", "not-a-commit")

    manifest = runtime_identity_manifest()

    assert manifest["expected_configured"] is True
    assert manifest["expected_valid"] is False
    assert manifest["expected_revision"] is None
    assert manifest["deployment_attested"] is False


def test_github_sha_is_used_when_explicit_revision_is_absent(monkeypatch):
    _clear_identity_env(monkeypatch)
    monkeypatch.setenv("GITHUB_SHA", REVISION)

    manifest = runtime_identity_manifest()

    assert current_revision() == certification_revision() == REVISION
    assert manifest["revision"] == REVISION
    assert manifest["source"] == "GITHUB_SHA"
    assert manifest["deployment_attested"] is False


def test_unknown_runtime_role_is_sanitized(monkeypatch):
    _clear_identity_env(monkeypatch)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "attacker-controlled-role")

    assert runtime_identity_manifest()["role"] == "unknown"


def test_app_env_alias_drives_pydantic_production_mode(monkeypatch):
    _clear_identity_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "production-secret-key-for-runtime-tests-2026")

    settings = Settings(_env_file=None)

    assert settings.app_environment == "production"
    assert settings.is_production is True


def test_app_environment_compatibility_alias_remains_supported(monkeypatch):
    _clear_identity_env(monkeypatch)
    monkeypatch.setenv("APP_ENVIRONMENT", "test")

    settings = Settings(_env_file=None)

    assert settings.app_environment == "test"


def test_app_env_production_rejects_placeholder_secret(monkeypatch):
    _clear_identity_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "short-placeholder")

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def _run_checker(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_runtime_identity.py"
    merged = dict(os.environ)
    merged.update(env)
    for name in (
        "JOBTOMATIK_RUNTIME_REVISION",
        "JOBTOMATIK_EXPECTED_REVISION",
        "JOBTOMATIK_RUNTIME_ROLE",
        "JOBTOMATIK_OPERATIONS_ENV_FILE",
        "GITHUB_SHA",
        "APP_ENV",
        "APP_ENVIRONMENT",
        "SECRET_KEY",
        "AUTOPILOT_ENABLED",
        "ALLOW_REAL_APPLICATION_SUBMIT",
        "ALLOW_REAL_FOLLOWUP_SEND",
        "GREENHOUSE_SUPERVISED_PILOT_ENABLED",
        "LEVER_SUPERVISED_PILOT_ENABLED",
    ):
        if name not in env:
            merged.pop(name, None)
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=script.parents[1],
        env=merged,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def test_sensitive_autopilot_runtime_requires_attestation():
    result = _run_checker({"AUTOPILOT_ENABLED": "true"}, "--require-sensitive")
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["sensitive_runtime_requested"] is True
    assert payload["attestation_required"] is True
    assert payload["configuration_valid"] is True
    assert payload["deployment_attested"] is False


def test_sensitive_runtime_reads_autopilot_from_operations_env_file(tmp_path):
    env_file = tmp_path / "jobtomatik.env"
    env_file.write_text("AUTOPILOT_ENABLED=true\n", encoding="utf-8")

    result = _run_checker(
        {"JOBTOMATIK_OPERATIONS_ENV_FILE": str(env_file)},
        "--require-sensitive",
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["sensitive_runtime_requested"] is True
    assert payload["attestation_required"] is True
    assert payload["configuration_valid"] is True
    assert payload["deployment_attested"] is False


def test_sensitive_runtime_accepts_matching_attestation():
    result = _run_checker(
        {
            "AUTOPILOT_ENABLED": "true",
            "JOBTOMATIK_RUNTIME_REVISION": REVISION,
            "JOBTOMATIK_EXPECTED_REVISION": REVISION,
            "JOBTOMATIK_RUNTIME_ROLE": "api",
        },
        "--require-sensitive",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["configuration_valid"] is True
    assert payload["deployment_attested"] is True
    assert payload["revision"] == REVISION
    assert payload["role"] == "api"


def test_invalid_sensitive_configuration_fails_closed_before_launch():
    result = _run_checker(
        {
            "APP_ENV": "production",
            "SECRET_KEY": "short-placeholder",
            "JOBTOMATIK_RUNTIME_REVISION": REVISION,
            "JOBTOMATIK_EXPECTED_REVISION": REVISION,
            "JOBTOMATIK_RUNTIME_ROLE": "api",
        },
        "--require-sensitive",
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["configuration_valid"] is False
    assert payload["configuration_error"] == "ValidationError"
    assert "short-placeholder" not in result.stdout
    assert "short-placeholder" not in result.stderr


def test_non_sensitive_development_runtime_remains_usable_without_attestation():
    result = _run_checker({}, "--require-sensitive")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["sensitive_runtime_requested"] is False
    assert payload["attestation_required"] is False
    assert payload["configuration_valid"] is True
