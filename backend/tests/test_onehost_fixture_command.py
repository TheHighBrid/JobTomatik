"""Execute the proof command against isolated committed and dirty checkouts."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMAND = "scripts/verify-onehost-fixture.sh"


def _git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def command_checkout(tmp_path):
    repo = tmp_path / "checkout"
    (repo / "scripts").mkdir(parents=True)
    (repo / "backend").mkdir()
    shutil.copy2(PROJECT_ROOT / COMMAND, repo / COMMAND)
    (repo / "backend/Dockerfile").write_text("FROM python:3.11-slim\n")
    (repo / "backend/requirements.txt").write_text("committed requirements\n")
    (repo / "docker-compose.onehost-fixture.yml").write_text("services: {}\n")
    (repo / ".gitignore").write_text("verification-artifacts/\nbackend/ignored.py\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture")
    return repo


@pytest.fixture
def command_environment(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text('''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log = Path(os.environ["FIXTURE_DOCKER_LOG"])
with log.open("a") as output:
    output.write(json.dumps(args) + "\\n")
if "config" in args:
    print("{}")
elif "build" in args:
    root = Path(args[args.index("--project-directory") + 1])
    Path(os.environ["FIXTURE_BUILD_OBSERVATION"]).write_text(json.dumps({
        "context": str(root),
        "requirements": (root / "backend/requirements.txt").read_text(),
        "ignored_input_present": (root / "backend/ignored.py").exists(),
    }))
    sys.exit(42)
''')
    docker.chmod(0o755)
    return {
        **os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "FIXTURE_DOCKER_LOG": str(tmp_path / "docker.jsonl"),
        "FIXTURE_BUILD_OBSERVATION": str(tmp_path / "build.json"),
    }


@pytest.mark.parametrize("path", [
    "backend/Dockerfile", "backend/requirements.txt", "docker-compose.onehost-fixture.yml",
])
@pytest.mark.parametrize("staged", [False, True])
def test_dirty_build_inputs_are_rejected_before_docker(command_checkout, command_environment, path, staged):
    (command_checkout / path).write_text("uncommitted input\n")
    if staged:
        _git(command_checkout, "add", path)
    result = subprocess.run(["bash", str(command_checkout / COMMAND)], env=command_environment,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 2, result.stderr
    assert "clean committed checkout" in result.stderr
    assert not Path(command_environment["FIXTURE_DOCKER_LOG"]).exists()
    assert not (command_checkout / "verification-artifacts").exists()


def test_untracked_source_is_rejected_before_docker(command_checkout, command_environment):
    (command_checkout / "backend/extra.py").write_text("untracked source\n")
    result = subprocess.run(["bash", str(command_checkout / COMMAND)], env=command_environment,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 2, result.stderr
    assert "clean committed checkout" in result.stderr
    assert not Path(command_environment["FIXTURE_DOCKER_LOG"]).exists()


@pytest.mark.parametrize("ignored_input", [False, True])
def test_clean_build_uses_only_committed_inputs(command_checkout, command_environment, ignored_input):
    if ignored_input:
        (command_checkout / "backend/ignored.py").write_text("uncommitted ignored source\n")
    result = subprocess.run(["bash", str(command_checkout / COMMAND)], env=command_environment,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 42, result.stderr
    observation = json.loads(Path(command_environment["FIXTURE_BUILD_OBSERVATION"]).read_text())
    assert observation["requirements"] == "committed requirements\n"
    assert observation["ignored_input_present"] is False
    assert observation["context"] != str(command_checkout)
    assert not Path(observation["context"]).exists()
    manifest = next((command_checkout / "verification-artifacts").glob("*/committed-inputs.txt"))
    assert "backend/Dockerfile" in manifest.read_text()
    assert "backend/requirements.txt" in manifest.read_text()
    assert _git(command_checkout, "status", "--porcelain").stdout == ""
