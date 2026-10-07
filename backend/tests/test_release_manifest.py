"""Regression coverage for exact-source release manifests and rollback gates."""

from __future__ import annotations

import json

import pytest

from app.services.release_manifest import (
    ReleaseManifestError,
    build_release_manifest,
    render_release_manifest,
    rollback_is_safe,
)


SHA = "8d785ef0a1b2c3d4e5f60718293a4b5c6d7e8f90"
OTHER = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DIGEST = "ab" * 32


def _payload(**overrides):
    payload = {
        "source_sha": SHA,
        "version": "4.0.0",
        "android_version_code": 400,
        "apk_sha256": DIGEST,
        "signing_cert_sha256": "cd" * 32,
        "backend_revision": SHA,
        "frontend_revision": SHA,
        "database_schema_revision": "head",
        "verification_runs": ["exact-head", "reproducible-verification"],
        "build_timestamp": "2026-10-07T05:00:00Z",
        "rollback_tested": True,
        "upgrade_tested": True,
    }
    payload.update(overrides)
    return payload


def test_manifest_binds_exact_source_and_does_not_grant_submit():
    manifest = build_release_manifest(_payload())

    assert manifest["source_sha"] == SHA
    assert manifest["android_version_code"] == 400
    assert manifest["grants_submit"] is False
    assert manifest["rollback_tested"] is True


def test_missing_apk_hash_fails_closed():
    with pytest.raises(ReleaseManifestError) as caught:
        build_release_manifest(_payload(apk_sha256=""))

    assert caught.value.code == "apk_sha256_missing"


def test_backend_revision_must_be_explicit_and_match_source():
    with pytest.raises(ReleaseManifestError) as missing:
        build_release_manifest(_payload(backend_revision=""))
    with pytest.raises(ReleaseManifestError) as mismatch:
        build_release_manifest(_payload(backend_revision=OTHER))

    assert missing.value.code == "backend_revision_missing"
    assert mismatch.value.code == "backend_revision_mismatch"


def test_frontend_revision_and_build_timestamp_are_explicit():
    with pytest.raises(ReleaseManifestError) as missing_frontend:
        build_release_manifest(_payload(frontend_revision=""))
    with pytest.raises(ReleaseManifestError) as missing_timestamp:
        build_release_manifest(_payload(build_timestamp=""))

    assert missing_frontend.value.code == "frontend_revision_missing"
    assert missing_timestamp.value.code == "build_timestamp_missing"


def test_build_timestamp_requires_timezone():
    with pytest.raises(ReleaseManifestError) as caught:
        build_release_manifest(_payload(build_timestamp="2026-10-07T05:00:00"))

    assert caught.value.code == "build_timestamp_invalid"


def test_hashes_require_exact_hexadecimal_lengths():
    with pytest.raises(ReleaseManifestError) as source:
        build_release_manifest(_payload(source_sha=SHA + "0"))
    with pytest.raises(ReleaseManifestError) as digest:
        build_release_manifest(_payload(apk_sha256=DIGEST + "0"))

    assert source.value.code == "source_sha_invalid"
    assert digest.value.code == "apk_sha256_invalid"


def test_rendered_manifest_is_deterministic_json():
    manifest = build_release_manifest(_payload())
    rendered = render_release_manifest(manifest)

    assert rendered.endswith("\n")
    assert json.loads(rendered) == manifest


def test_destructive_rollback_is_blocked():
    decision = rollback_is_safe(
        from_schema="head",
        to_schema="previous",
        destructive=True,
    )

    assert decision["safe"] is False
    assert decision["reason"] == "destructive_migration_blocks_rollback"


def test_same_schema_rollback_is_safe():
    decision = rollback_is_safe(
        from_schema="head",
        to_schema="head",
        destructive=False,
    )

    assert decision["safe"] is True
    assert decision["reason"] == "same_schema"
