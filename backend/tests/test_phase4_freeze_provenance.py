from __future__ import annotations

from copy import deepcopy

import app.services.phase4_freeze_provenance as provenance
from app.services.phase4_candidate_gate import ADAPTERS


FREEZE_COMMIT = "a" * 40
VALIDATION_COMMIT = "b" * 40
SOURCE_DIGEST = "1" * 64
LEGACY_FIXTURE_DIGEST = "2" * 64
CURRENT_FIXTURE_DIGEST = "3" * 64
ARTIFACT_DIGEST = "4" * 64


def _freeze(*, migrated: bool) -> dict:
    adapters = {
        adapter: {
            "digests": {
                "adapter_source_sha256": SOURCE_DIGEST,
                "fixture_regression_sha256": (
                    CURRENT_FIXTURE_DIGEST if migrated else LEGACY_FIXTURE_DIGEST
                ),
                **(
                    {
                        "legacy_day28_fixture_regression_sha256": LEGACY_FIXTURE_DIGEST,
                    }
                    if migrated
                    else {}
                ),
            }
        }
        for adapter in ADAPTERS
    }
    payload = {
        "schema_version": "1.1" if migrated else "1.0",
        "freeze_source_commit": FREEZE_COMMIT,
        "adapters": adapters,
        "freeze_policy": {
            "maturity_promotion_is_out_of_scope": True,
            "real_submission_enablement_is_out_of_scope": True,
            "autopilot_enablement_is_out_of_scope": True,
        },
    }
    if migrated:
        payload["fixture_digest_migration"] = {
            "migration": provenance.FIXTURE_REGATE_MIGRATION,
            "validation_source_commit": VALIDATION_COMMIT,
            "validation_workflow_run_id": 12345,
            "validation_artifact_sha256": ARTIFACT_DIGEST,
            "fixture_only_drift_verified": True,
            "legacy_day28_fixture_hashes_preserved": True,
            "adapter_source_drift_observed": False,
            "retained_evidence_drift_observed": False,
            "manifest_live_evidence_drift_observed": False,
            "adapter_version_change_observed": False,
            "adapter_maturity_change_observed": False,
            "real_submission_enablement_changed": False,
            "autopilot_enablement_changed": False,
        }
        payload["freeze_policy"].update(
            {
                "cross_phase_fixture_change_requires_recorded_regate": True,
                "legacy_day28_fixture_hashes_preserved": True,
            }
        )
    return payload


def _stub_historical_git(monkeypatch) -> None:
    monkeypatch.setattr(provenance, "_git_commit_exists", lambda root, commit: True)
    monkeypatch.setattr(
        provenance,
        "_historical_fixture_paths",
        lambda root, commit, adapter: [f"backend/tests/test_{adapter}_historical.py"],
    )

    def fake_digest(root, commit, paths):
        values = list(paths)
        return SOURCE_DIGEST if any("app/services" in value for value in values) else LEGACY_FIXTURE_DIGEST

    monkeypatch.setattr(provenance, "_digest_git_paths", fake_digest)


def test_schema_1_0_keeps_original_historical_digest_contract(monkeypatch, tmp_path):
    _stub_historical_git(monkeypatch)
    report = provenance.verify_freeze_source_provenance(
        root=tmp_path,
        freeze=_freeze(migrated=False),
    )

    assert report["verified"] is True
    assert report["migration_active"] is False
    assert report["errors"] == []
    assert all(row["fixture_matches"] is True for row in report["adapters"].values())


def test_schema_1_1_preserves_day28_hash_and_separates_current_fixture(monkeypatch, tmp_path):
    _stub_historical_git(monkeypatch)
    report = provenance.verify_freeze_source_provenance(
        root=tmp_path,
        freeze=_freeze(migrated=True),
    )

    assert report["verified"] is True
    assert report["migration_active"] is True
    assert report["errors"] == []
    for row in report["adapters"].values():
        assert row["legacy_day28_fixture_digest"] == LEGACY_FIXTURE_DIGEST
        assert row["current_frozen_fixture_digest"] == CURRENT_FIXTURE_DIGEST
        assert row["historical_fixture_hash_preserved"] is True


def test_schema_1_1_fails_closed_when_legacy_hash_is_missing(monkeypatch, tmp_path):
    _stub_historical_git(monkeypatch)
    freeze = _freeze(migrated=True)
    del freeze["adapters"]["lever"]["digests"]["legacy_day28_fixture_regression_sha256"]

    report = provenance.verify_freeze_source_provenance(root=tmp_path, freeze=freeze)

    assert report["verified"] is False
    assert "lever:legacy_fixture_digest_missing_or_invalid" in report["errors"]
    assert "lever:freeze_fixture_digest_mismatch" in report["errors"]


def test_schema_1_1_rejects_migration_that_claims_source_drift(monkeypatch, tmp_path):
    _stub_historical_git(monkeypatch)
    freeze = deepcopy(_freeze(migrated=True))
    freeze["fixture_digest_migration"]["adapter_source_drift_observed"] = True

    report = provenance.verify_freeze_source_provenance(root=tmp_path, freeze=freeze)

    assert report["verified"] is False
    assert (
        "fixture_digest_migration:adapter_source_drift_observed_must_be_false"
        in report["errors"]
    )
