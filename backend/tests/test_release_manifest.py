from __future__ import annotations

import pytest

from app.services.release_manifest import ReleaseManifestError, build_release_manifest, rollback_is_safe


SHA = "8d785ef0a1b2c3d4e5f60718293a4b5c6d7e8f90"
OTHER = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DIGEST = "ab" * 32


def _payload(**overrides):
    payload = {
        "source_sha": SHA,
        "version": "2.1.1",
        "android_version_code": 211,
        "apk_sha256": DIGEST,
        "signing_cert_sha256": "cd" * 32,
        "backend_revision": SHA,
        "frontend_revision": SHA,
        "database_schema_revision": "head",
        "verification_runs": ["local-release-manifest"],
        "build_timestamp": "2026-10-06T20:00:00Z",
        "rollback_tested": True,
        "upgrade_tested": True,
    }
    payload.update(overrides)
    return payload


def test_manifest_binds_exact_source_and_does_not_grant_submit():
    manifest = build_release_manifest(_payload())
    assert manifest["source_sha"] == SHA
    assert manifest["android_version_code"] == 211
    assert manifest["grants_submit"] is False
    assert manifest["rollback_tested"] is True


def test_missing_apk_hash_fails_closed():
    with pytest.raises(ReleaseManifestError) as caught:
        build_release_manifest(_payload(apk_sha256=""))
    assert caught.value.code == "apk_sha256_invalid"


def test_backend_revision_must_match_source():
    with pytest.raises(ReleaseManifestError) as caught:
        build_release_manifest(_payload(backend_revision=OTHER))
    assert caught.value.code == "backend_revision_mismatch"


def test_destructive_rollback_is_blocked():
    decision = rollback_is_safe(from_schema="head", to_schema="previous", destructive=True)
    assert decision["safe"] is False
    assert decision["reason"] == "destructive_migration_blocks_rollback"


def test_same_schema_rollback_is_safe():
    assert rollback_is_safe(from_schema="head", to_schema="head", destructive=False)["safe"] is True
