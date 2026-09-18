from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts/verify_python_environment_requirements.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_python_environment_requirements", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_requirement_drift_rejects_installed_version_mismatch(tmp_path, monkeypatch):
    module = _load_module()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("playwright==1.61.0\n", encoding="utf-8")
    monkeypatch.setattr(module.metadata, "version", lambda _name: "1.44.0")

    assert module.requirement_drift(requirements) == [
        "playwright: required ==1.61.0, installed=1.44.0"
    ]


def test_requirement_drift_accepts_exact_runtime_pin(tmp_path, monkeypatch):
    module = _load_module()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("playwright==1.61.0\n", encoding="utf-8")
    monkeypatch.setattr(module.metadata, "version", lambda _name: "1.61.0")

    assert module.requirement_drift(requirements) == []


def test_verify_environment_fails_when_pip_check_reports_broken_dependency(tmp_path, monkeypatch):
    module = _load_module()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("playwright==1.61.0\n", encoding="utf-8")
    monkeypatch.setattr(module.metadata, "version", lambda _name: "1.61.0")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="broken-package has requirement missing-package\n",
            stderr="",
        ),
    )

    with pytest.raises(module.EnvironmentRequirementError, match="broken-package"):
        module.verify_environment(requirements)
