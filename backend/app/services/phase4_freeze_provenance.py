"""Verify that the Phase 4 freeze digests are reproducible from its source commit."""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.services.phase4_candidate_gate import (
    ADAPTERS,
    COMMON_FIXTURE_PATHS,
    SOURCE_PATHS,
)


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _git_bytes(root: Path, commit: str, relative_path: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(
            f"unable to read {relative_path} from freeze_source_commit {commit}"
        ) from exc


def _git_tree_paths(root: Path, commit: str, prefix: str) -> list[str]:
    try:
        output = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", commit, "--", prefix],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(
            f"unable to inspect freeze_source_commit {commit}"
        ) from exc
    return [line.strip() for line in output.splitlines() if line.strip()]


def _digest_git_paths(root: Path, commit: str, paths: Iterable[str]) -> str:
    digest = hashlib.sha256()
    seen = False
    for relative_path in sorted(set(paths)):
        seen = True
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_git_bytes(root, commit, relative_path))
        digest.update(b"\0")
    if not seen:
        raise ValueError("historical digest input set is empty")
    return digest.hexdigest()


def _historical_fixture_paths(root: Path, commit: str, adapter: str) -> list[str]:
    test_prefix = f"backend/tests/test_{adapter}"
    adapter_tests = [
        path
        for path in _git_tree_paths(root, commit, "backend/tests")
        if path.startswith(test_prefix) and path.endswith(".py")
    ]
    if not adapter_tests:
        raise ValueError(
            f"no historical fixture/regression tests found for {adapter} at {commit}"
        )
    return [*adapter_tests, *COMMON_FIXTURE_PATHS]


def verify_freeze_source_provenance(
    *,
    root: Path,
    freeze: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute frozen source/fixture digests from the claimed historical commit."""
    commit = str(freeze.get("freeze_source_commit") or "").strip().lower()
    report: dict[str, Any] = {
        "commit": commit or None,
        "verified": False,
        "adapters": {},
        "errors": [],
    }
    if not COMMIT_RE.fullmatch(commit):
        report["errors"].append("freeze_source_commit_invalid")
        return report

    frozen_adapters = (
        freeze.get("adapters") if isinstance(freeze.get("adapters"), Mapping) else {}
    )
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        report["errors"].append("freeze_source_commit_unavailable")
        return report

    for adapter in ADAPTERS:
        frozen = frozen_adapters.get(adapter)
        if not isinstance(frozen, Mapping):
            report["errors"].append(f"{adapter}:missing_freeze")
            continue
        frozen_digests = frozen.get("digests")
        if not isinstance(frozen_digests, Mapping):
            report["errors"].append(f"{adapter}:missing_frozen_digests")
            continue

        try:
            source_digest = _digest_git_paths(root, commit, SOURCE_PATHS[adapter])
            fixture_paths = _historical_fixture_paths(root, commit, adapter)
            fixture_digest = _digest_git_paths(root, commit, fixture_paths)
        except ValueError as exc:
            report["errors"].append(f"{adapter}:historical_digest_unavailable")
            report["adapters"][adapter] = {"error": str(exc)}
            continue

        expected_source = str(frozen_digests.get("adapter_source_sha256") or "")
        expected_fixture = str(frozen_digests.get("fixture_regression_sha256") or "")
        source_matches = source_digest == expected_source
        fixture_matches = fixture_digest == expected_fixture
        if not source_matches:
            report["errors"].append(f"{adapter}:freeze_source_digest_mismatch")
        if not fixture_matches:
            report["errors"].append(f"{adapter}:freeze_fixture_digest_mismatch")

        report["adapters"][adapter] = {
            "source_digest": source_digest,
            "frozen_source_digest": expected_source,
            "source_matches": source_matches,
            "fixture_digest": fixture_digest,
            "frozen_fixture_digest": expected_fixture,
            "fixture_matches": fixture_matches,
            "source_paths": list(SOURCE_PATHS[adapter]),
            "fixture_paths": fixture_paths,
        }

    report["verified"] = not report["errors"]
    return report
