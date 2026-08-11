import json
from pathlib import Path

import pytest

from app.models.certification import ShadowRunSession, _require_android_shadow_admission
from app.services import runtime_acceptance
from scripts import install_android_static_frontend_artifact as static_installer
from scripts.build_frontend_artifact_manifest import build_manifest, sha256_tree
from scripts.install_android_static_frontend_artifact import _verify_payload


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def test_static_frontend_manifest_binds_revision_lockfile_and_dist(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    lock = tmp_path / "package-lock.json"
    lock.write_text('{"lockfileVersion":3}', encoding="utf-8")
    revision = "a" * 40

    manifest = build_manifest(dist=dist, revision=revision, package_lock=lock)

    assert manifest["artifact_type"] == "jobtomatik-static-frontend"
    assert manifest["revision"] == revision
    assert manifest["dist_tree_sha256"] == sha256_tree(dist)
    assert manifest["package_lock_sha256"]
    assert manifest["build_api_url"] == "http://127.0.0.1:8010"


def test_static_frontend_installer_rejects_revision_drift(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    lock = tmp_path / "package-lock.json"
    lock.write_text('{"lockfileVersion":3}', encoding="utf-8")
    manifest = build_manifest(dist=dist, revision="b" * 40, package_lock=lock)
    manifest_path = tmp_path / "jobtomatik-frontend-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="revision"):
        _verify_payload(
            manifest_path=manifest_path,
            dist=dist,
            revision="c" * 40,
            package_lock=lock,
        )


def test_published_ref_requires_exact_marker_and_manifest_revision(monkeypatch):
    revision = "c" * 40
    observed_fetches = []

    monkeypatch.setattr(
        static_installer,
        "_fetch_branch",
        lambda branch: observed_fetches.append(branch),
    )

    def fake_show(ref, path):
        assert ref == "refs/remotes/origin/android-static-frontend-runtime"
        if path == static_installer.REVISION_MARKER:
            return revision + "\n"
        if path == static_installer.MANIFEST_NAME:
            return json.dumps({"revision": revision})
        raise AssertionError(path)

    monkeypatch.setattr(static_installer, "_show_text", fake_show)

    ref = static_installer._published_ref_for_revision(
        "android-static-frontend-runtime",
        revision,
        timeout_seconds=0,
    )

    assert ref == "refs/remotes/origin/android-static-frontend-runtime"
    assert observed_fetches == ["android-static-frontend-runtime"]


def test_published_ref_fails_closed_on_stale_runtime_branch(monkeypatch):
    revision = "d" * 40
    monkeypatch.setattr(static_installer, "_fetch_branch", lambda _branch: None)

    def fake_show(_ref, path):
        if path == static_installer.REVISION_MARKER:
            return ("e" * 40) + "\n"
        return json.dumps({"revision": "e" * 40})

    monkeypatch.setattr(static_installer, "_show_text", fake_show)

    with pytest.raises(RuntimeError, match="published_revision_mismatch"):
        static_installer._published_ref_for_revision(
            "android-static-frontend-runtime",
            revision,
            timeout_seconds=0,
        )


def test_android_canonical_runtime_never_launches_node_or_vite():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(encoding="utf-8")
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(encoding="utf-8")

    assert "npm run dev" not in manager
    assert "npm run dev" not in wrapper
    assert "serve_static_frontend.py" in manager
    assert "install_android_static_frontend_artifact.py" in wrapper
    assert "repair_android_frontend_native_deps.py" not in wrapper
    assert "stage_android_frontend_native_bindings.py" not in wrapper
    assert "ANDROID_RUNTIME_ACCEPTANCE=PASS" in (
        BACKEND_ROOT / "scripts/android_runtime_acceptance.py"
    ).read_text(encoding="utf-8")


def test_static_artifact_workflow_builds_every_main_revision_and_publishes_git_runtime():
    workflow = (
        REPO_ROOT / ".github/workflows/android-static-frontend-artifact.yml"
    ).read_text(encoding="utf-8")
    installer = (
        BACKEND_ROOT / "scripts/install_android_static_frontend_artifact.py"
    ).read_text(encoding="utf-8")

    assert "push:" in workflow
    assert "- main" in workflow
    assert "contents: write" in workflow
    assert "jobtomatik-frontend-dist-${{ github.sha }}" in workflow
    assert "npm ci --prefix frontend" in workflow
    assert "npm run build --prefix frontend" in workflow
    assert "serve_static_frontend.py" in workflow
    assert "android-static-frontend-runtime" in workflow
    assert "git checkout --orphan" in workflow
    assert "git push --force origin" in workflow
    assert 'GITHUB_EVENT_NAME" == "push"' in workflow
    assert 'GITHUB_REF" == "refs/heads/main"' in workflow

    assert '"fetch",' in installer
    assert '"archive",' in installer
    assert "DEFAULT_ARTIFACT_BRANCH = \"android-static-frontend-runtime\"" in installer
    assert "api.github.com" not in installer
    assert "archive_download_url" not in installer
    assert "JOBTOMATIK_GITHUB_TOKEN" not in installer
    assert "GITHUB_TOKEN" not in installer


def test_qualification_canary_uses_real_scheduler_and_one_application_limit():
    canary = (
        BACKEND_ROOT / "scripts/run_shadow_qualification_canary.py"
    ).read_text(encoding="utf-8")
    scheduler = (BACKEND_ROOT / "app/tasks/scraping.py").read_text(encoding="utf-8")

    assert "run_job_search.apply_async" in canary
    assert "_run_scheduler_cycle_for_user" in canary
    assert "shadow_application_limit=1" in canary
    assert "Mock Company" not in canary
    assert "mock_candidate" not in canary
    assert "bounded_shadow_limit = max(0, min(1, int(shadow_application_limit)))" in scheduler
    assert '"source": source' in scheduler


def test_android_four_hour_insert_requires_current_canary(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.setattr(
        runtime_acceptance,
        "canary_receipt_status",
        lambda *_args, **_kwargs: {
            "ok": False,
            "blockers": ["application_path_observed"],
            "receipt": {},
        },
    )
    session = ShadowRunSession(
        user_id=7,
        candidate_revision="d" * 40,
        target_evidence_type="shadow_run_4h",
        requested_duration_seconds=4 * 60 * 60,
        started_at=None,
        expected_end_at=None,
    )

    with pytest.raises(ValueError, match="requires a fresh exact-runtime"):
        _require_android_shadow_admission(session)


def test_android_four_hour_insert_accepts_exact_noncertifying_canary(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    revision = "e" * 40
    monkeypatch.setattr(
        runtime_acceptance,
        "canary_receipt_status",
        lambda *_args, **_kwargs: {
            "ok": True,
            "blockers": [],
            "receipt": {
                "type": "shadow_qualification_canary",
                "revision": revision,
                "certification_eligible": False,
            },
        },
    )
    session = ShadowRunSession(
        user_id=8,
        candidate_revision=revision,
        target_evidence_type="shadow_run_4h",
        requested_duration_seconds=4 * 60 * 60,
        started_at=None,
        expected_end_at=None,
    )

    _require_android_shadow_admission(session)


def test_android_eight_and_twenty_four_hour_stages_remain_locked(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    for evidence_type in ("shadow_run_8h", "shadow_run_24h"):
        session = ShadowRunSession(
            user_id=9,
            candidate_revision="f" * 40,
            target_evidence_type=evidence_type,
            requested_duration_seconds=1,
            started_at=None,
            expected_end_at=None,
        )
        with pytest.raises(ValueError, match="intentionally locked"):
            _require_android_shadow_admission(session)


def test_non_android_shadow_tests_do_not_require_physical_device_receipt(monkeypatch):
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_MODE", raising=False)
    session = ShadowRunSession(
        user_id=10,
        candidate_revision="1" * 40,
        target_evidence_type="shadow_run_4h",
        requested_duration_seconds=4 * 60 * 60,
        started_at=None,
        expected_end_at=None,
    )

    _require_android_shadow_admission(session)
