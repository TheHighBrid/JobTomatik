"""Verify that the Phase 4 freeze digests are reproducible from Git history."""

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
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MIGRATED_FREEZE_SCHEMA_VERSION = "1.1"
FIXTURE_REGATE_MIGRATION = "day39_post_phase_b_fixture_regate_v1"


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


def _git_commit_exists(root: Path, commit: str) -> bool:
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


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


def _validate_fixture_regate_migration(
    *,
    root: Path,
    freeze: Mapping[str, Any],
    report: dict[str, Any],
) -> bool:
    """Validate the schema-1.1 fixture-only regate before trusting legacy hashes.

    The migration may update the exact-head fixture digest used by the Phase 4 gate,
    but it may not rewrite the historical Day 28 provenance. The old digest must be
    retained separately and the migration must explicitly assert that no source,
    retained-evidence, maturity, or consequential-runtime boundary moved with it.
    """

    migration = freeze.get("fixture_digest_migration")
    if not isinstance(migration, Mapping):
        report["errors"].append("fixture_digest_migration_missing")
        return False

    report["fixture_digest_migration"] = {
        "migration": migration.get("migration"),
        "validation_source_commit": migration.get("validation_source_commit"),
        "validation_workflow_run_id": migration.get("validation_workflow_run_id"),
        "validation_artifact_sha256": migration.get("validation_artifact_sha256"),
    }

    if migration.get("migration") != FIXTURE_REGATE_MIGRATION:
        report["errors"].append("fixture_digest_migration_identifier_invalid")

    validation_commit = str(migration.get("validation_source_commit") or "").strip().lower()
    if not COMMIT_RE.fullmatch(validation_commit):
        report["errors"].append("fixture_digest_migration_validation_commit_invalid")
    elif not _git_commit_exists(root, validation_commit):
        report["errors"].append("fixture_digest_migration_validation_commit_unavailable")

    run_id = migration.get("validation_workflow_run_id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        report["errors"].append("fixture_digest_migration_workflow_run_invalid")

    artifact_digest = str(migration.get("validation_artifact_sha256") or "").strip().lower()
    if not SHA256_RE.fullmatch(artifact_digest):
        report["errors"].append("fixture_digest_migration_artifact_digest_invalid")

    required_true = (
        "fixture_only_drift_verified",
        "legacy_day28_fixture_hashes_preserved",
    )
    required_false = (
        "adapter_source_drift_observed",
        "retained_evidence_drift_observed",
        "manifest_live_evidence_drift_observed",
        "adapter_version_change_observed",
        "adapter_maturity_change_observed",
        "real_submission_enablement_changed",
        "autopilot_enablement_changed",
    )
    for key in required_true:
        if migration.get(key) is not True:
            report["errors"].append(f"fixture_digest_migration:{key}_must_be_true")
    for key in required_false:
        if migration.get(key) is not False:
            report["errors"].append(f"fixture_digest_migration:{key}_must_be_false")

    freeze_policy = freeze.get("freeze_policy")
    if not isinstance(freeze_policy, Mapping):
        report["errors"].append("fixture_digest_migration_freeze_policy_missing")
    else:
        if freeze_policy.get("cross_phase_fixture_change_requires_recorded_regate") is not True:
            report["errors"].append(
                "fixture_digest_migration:recorded_regate_policy_missing"
            )
        if freeze_policy.get("legacy_day28_fixture_hashes_preserved") is not True:
            report["errors"].append(
                "fixture_digest_migration:legacy_hash_policy_missing"
            )
        for key in (
            "maturity_promotion_is_out_of_scope",
            "real_submission_enablement_is_out_of_scope",
            "autopilot_enablement_is_out_of_scope",
        ):
            if freeze_policy.get(key) is not True:
                report["errors"].append(f"fixture_digest_migration:{key}_must_be_true")

    return not report["errors"]


def verify_freeze_source_provenance(
    *,
    root: Path,
    freeze: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute historical source/fixture digests without erasing later regates.

    Schema 1.0 retains the original behavior: both source and fixture digests are
    compared directly with the Day 28 source commit.

    Schema 1.1 permits one recorded Day 39 fixture-only regate. Source provenance
    still compares directly with Day 28. Historical fixture provenance compares with
    ``legacy_day28_fixture_regression_sha256`` while the current exact-head fixture
    digest remains in ``fixture_regression_sha256`` for the Phase 4/Day 35 gates.
    """

    commit = str(freeze.get("freeze_source_commit") or "").strip().lower()
    schema_version = str(freeze.get("schema_version") or "").strip()
    report: dict[str, Any] = {
        "schema_version": schema_version or None,
        "commit": commit or None,
        "verified": False,
        "migration_active": False,
        "adapters": {},
        "errors": [],
    }
    if not COMMIT_RE.fullmatch(commit):
        report["errors"].append("freeze_source_commit_invalid")
        return report
    if not _git_commit_exists(root, commit):
        report["errors"].append("freeze_source_commit_unavailable")
        return report

    if schema_version == "1.0":
        migration_active = False
    elif schema_version == MIGRATED_FREEZE_SCHEMA_VERSION:
        migration_active = True
        report["migration_active"] = True
        _validate_fixture_regate_migration(root=root, freeze=freeze, report=report)
    else:
        report["errors"].append("freeze_schema_version_unsupported")
        return report

    frozen_adapters = (
        freeze.get("adapters") if isinstance(freeze.get("adapters"), Mapping) else {}
    )

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
        current_fixture = str(frozen_digests.get("fixture_regression_sha256") or "")
        if migration_active:
            expected_fixture = str(
                frozen_digests.get("legacy_day28_fixture_regression_sha256") or ""
            )
            if not SHA256_RE.fullmatch(current_fixture):
                report["errors"].append(f"{adapter}:current_fixture_digest_invalid")
            if not SHA256_RE.fullmatch(expected_fixture):
                report["errors"].append(f"{adapter}:legacy_fixture_digest_missing_or_invalid")
        else:
            expected_fixture = current_fixture

        source_matches = source_digest == expected_source
        fixture_matches = fixture_digest == expected_fixture
        if not source_matches:
            report["errors"].append(f"{adapter}:freeze_source_digest_mismatch")
        if not fixture_matches:
            report["errors"].append(f"{adapter}:freeze_fixture_digest_mismatch")

        adapter_report = {
            "source_digest": source_digest,
            "frozen_source_digest": expected_source,
            "source_matches": source_matches,
            "fixture_digest": fixture_digest,
            "frozen_fixture_digest": expected_fixture,
            "fixture_matches": fixture_matches,
            "source_paths": list(SOURCE_PATHS[adapter]),
            "fixture_paths": fixture_paths,
        }
        if migration_active:
            adapter_report.update(
                {
                    "legacy_day28_fixture_digest": expected_fixture,
                    "current_frozen_fixture_digest": current_fixture,
                    "historical_fixture_hash_preserved": fixture_matches,
                }
            )
        report["adapters"][adapter] = adapter_report

    report["verified"] = not report["errors"]
    return report
