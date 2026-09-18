import json
from pathlib import Path

from app.config import Settings


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_android_gradle_wrapper_is_portable():
    wrapper = (
        REPO_ROOT / "frontend" / "android" / "gradle" / "wrapper" / "gradle-wrapper.properties"
    ).read_text(encoding="utf-8")
    assert "distributionUrl=https\\://services.gradle.org/distributions/gradle-" in wrapper
    assert "-bin.zip" in wrapper
    assert r"file\:///tmp/" not in wrapper
    assert "validateDistributionUrl=true" in wrapper


def test_android_release_config_contains_no_committed_signing_secret_and_fails_closed():
    build_gradle = (REPO_ROOT / "frontend" / "android" / "app" / "build.gradle").read_text(encoding="utf-8")
    assert "versionCode 210" in build_gradle
    assert 'versionName "2.1.0"' in build_gradle
    assert "JOBTOMATIK_KEYSTORE_PATH" in build_gradle
    assert "JOBTOMATIK_KEYSTORE_PASSWORD" in build_gradle
    assert "JOBTOMATIK_KEY_ALIAS" in build_gradle
    assert "JOBTOMATIK_KEY_PASSWORD" in build_gradle
    assert "Persistent JobTomatik release signing is required" in build_gradle
    assert "distributionReleaseTaskRequested" in build_gradle
    assert "assemble|bundle|package|publish" in build_gradle
    assert "signingConfig signingConfigs.release" in build_gradle
    assert "contains('release')" not in build_gradle
    assert "/home/user/JobTomatik" not in build_gradle
    assert "jobtomatik123" not in build_gradle


def test_android_manifest_protects_local_app_data():
    manifest = (REPO_ROOT / "frontend" / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'android:allowBackup="false"' in manifest
    assert 'android:usesCleartextTraffic="true"' in manifest
    assert "android.permission.INTERNET" in manifest


def test_frontend_apk_scripts_run_gradle_assembly():
    package = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == "1.0.0"
    assert "assembleDebug" in package["scripts"]["build:apk:debug"]
    assert "assembleRelease" in package["scripts"]["build:apk:release"]
    assert "lintDebug" in package["scripts"]["android:lint"]
    assert package["scripts"]["test"] == "node --test"


def test_default_cors_origins_are_explicit_and_capacitor_compatible():
    settings = Settings(_env_file=None)
    assert "*" not in settings.cors_origin_list
    assert "http://127.0.0.1:3000" in settings.cors_origin_list
    assert "https://localhost" in settings.cors_origin_list
    assert "capacitor://localhost" in settings.cors_origin_list


def test_local_runtime_contract_uses_sqlite_and_port_8010_everywhere():
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    active_lines = {
        line.strip()
        for line in env_example.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    client = (REPO_ROOT / "frontend" / "src" / "api" / "client.js").read_text(encoding="utf-8")
    launcher = (REPO_ROOT / "termux-start.sh").read_text(encoding="utf-8")
    assert "DATABASE_URL=sqlite:///./jobtomatik.db" in active_lines
    assert not any(line.startswith("DATABASE_URL=postgresql://") for line in active_lines)
    assert "VITE_API_URL=http://127.0.0.1:8010" in active_lines
    assert "import.meta.env.VITE_API_URL || 'http://127.0.0.1:8010'" in client
    assert "uvicorn app.main:app --host 127.0.0.1 --port 8010" in launcher
    assert "http://127.0.0.1:8010/health" in launcher
    assert "--port 8000" not in launcher


def test_docker_build_contexts_exclude_secrets_and_runtime_data():
    backend_ignore = (REPO_ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8")
    frontend_ignore = (REPO_ROOT / "frontend" / ".dockerignore").read_text(encoding="utf-8")
    frontend_dockerfile = (REPO_ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    for token in (".env", "uploads/", "browser_profiles/", "handoff_sessions/"):
        assert token in backend_ignore
    for token in (".env", "node_modules/", "android/app/build/", "*.jks"):
        assert token in frontend_ignore
    assert "RUN npm ci" in frontend_dockerfile
    assert "RUN npm install" not in frontend_dockerfile


def test_release_documentation_is_present():
    required = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "CHANGELOG.md",
        REPO_ROOT / "SECURITY.md",
        REPO_ROOT / "docs" / "SETUP_TUTORIAL.md",
        REPO_ROOT / "docs" / "FULL_AUDIT_2026-07-27.md",
        REPO_ROOT / "docs" / "ANDROID_RELEASE_SIGNING.md",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()]
    assert not missing, f"Missing release documentation: {missing}"


def test_android_production_release_workflow_is_fail_closed_and_deterministic():
    workflow_path = REPO_ROOT / ".github" / "workflows" / "android-production-release.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    assert workflow_path.is_file()
    assert "workflow_dispatch:" in workflow
    assert "inputs:" not in workflow
    assert "github.actor == 'TheHighBrid'" in workflow
    assert "environment: android-production-release" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "ref: main" in workflow
    assert "persist-credentials: false" in workflow
    assert "git rev-parse origin/main" in workflow
    assert "JOBTOMATIK_ANDROID_SIGNING_BUNDLE_BASE64" in workflow
    assert "JOBTOMATIK_RELEASE_CERT_SHA256" in workflow
    assert "vars.JOBTOMATIK_RELEASE_CERT_SHA256" in workflow
    assert "./.github/actions/android-signing-material" in workflow
    assert "GITHUB_ENV" not in workflow
    assert "secrets.JOBTOMATIK_KEYSTORE_PASSWORD" not in workflow
    assert "secrets.JOBTOMATIK_KEY_PASSWORD" not in workflow
    assert "keystore_password:" not in workflow
    assert "key_password:" not in workflow
    assert "password" not in workflow.lower()
    assert "apksigner" in workflow
    assert "SIGNING_CERT_SHA256" in workflow
    assert 'test "$SIGNING_CERT_SHA256" = "$EXPECTED_CERT_SHA256"' in workflow
    assert 'test "$VERSION_CODE" -gt 210' in workflow
    assert "MAX_PREVIOUS_VERSION_CODE" in workflow
    assert 'test "$VERSION_CODE" -gt "$MAX_PREVIOUS_VERSION_CODE"' in workflow
    assert "assembleRelease" not in workflow
    assert "assembleDebug" not in workflow
    assert "softprops/action-gh-release" not in workflow
    assert "Publication: not performed by this workflow" in workflow
    assert "create-release" not in workflow




def test_android_signing_material_action_writes_only_ephemeral_mode_0600_files():
    action = (REPO_ROOT / ".github" / "actions" / "android-signing-material" / "action.yml").read_text(encoding="utf-8")
    script = (REPO_ROOT / ".github" / "actions" / "android-signing-material" / "index.js").read_text(encoding="utf-8")
    assert "using: node20" in action
    assert "signing_bundle_base64:" in action
    assert "keystore_password:" not in action
    assert "key_password:" not in action
    assert "RUNNER_TEMP" in script
    assert "jobtomatik-signing" in script
    assert "mode: 0o600" in script
    assert "::add-mask::" in script
    assert "GITHUB_ENV" not in script
    assert "GITHUB_OUTPUT" not in script
    assert "spawnSync" in script
    assert "keytool" in script
    assert "assembleRelease" in script
    assert "JOBTOMATIK_KEYSTORE_PASSWORD" in script
    assert "fs.rmSync" in script


def test_exact_artifact_v21_publisher_is_owner_scoped_and_does_not_rebuild():
    workflow_path = REPO_ROOT / ".github" / "workflows" / "publish-v1-command.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    assert workflow_path.is_file()
    assert "name: Publish JobTomatik v2.1.0 by owner-authorized exact artifact" in workflow
    assert "workflow_dispatch:" in workflow
    assert "issue_comment:" not in workflow
    assert "github.actor == 'TheHighBrid'" in workflow
    assert "source_commit:" in workflow
    assert "candidate_run_id:" in workflow
    assert "approved_apk_sha256:" in workflow
    assert "day42_readiness_sha256:" in workflow
    assert "authorization_reference:" in workflow
    assert "acknowledgment:" in workflow
    assert "PUBLISH JOBTOMATIK V2.1.0" in workflow
    assert ".github/workflows/build-v2-release-candidate.yml" in workflow
    assert "actions/download-artifact@v8" in workflow
    assert "JobTomatik-v2.1.0-candidate-" in workflow
    assert "versionCode='210'" in workflow
    assert "versionName='2.1.0'" in workflow
    assert "tag_name: v2.1.0" in workflow
    assert "target_commitish: ${{ needs.authorize-exact-release.outputs.source_commit }}" in workflow
    assert "overwrite_files: false" in workflow
    assert "overwrite_files: true" not in workflow
    assert "assembleRelease" not in workflow
    assert "assembleDebug" not in workflow
    assert "npm run android:prepare" not in workflow
    assert "git fetch origin main --no-tags" in workflow
    assert "Release tag $RELEASE_TAG already exists" in workflow
    assert "github.rest.repos.getReleaseByTag" in workflow
    assert "Recheck GitHub release absence immediately before publication" in workflow
    assert "build_identity_sha256" in workflow
    assert "signing_certificate_sha256" in workflow
    assert "workflow_conclusion" in workflow
    assert "reproducible_build" in workflow
    assert "DAY42-READINESS-SHA256.txt" in workflow


def test_exact_commit_v21_candidate_builder_is_build_only():
    workflow = (REPO_ROOT / ".github" / "workflows" / "build-v2-release-candidate.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "github.actor == 'TheHighBrid'" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "source_commit:" in workflow
    assert "day41_audit_reference:" in workflow
    assert "git rev-parse origin/main" in workflow
    assert "versionCode='210'" in workflow
    assert "versionName='2.1.0'" in workflow
    assert "SIGNING_MODE=release_signed" in workflow
    assert "SIGNING_MODE=development_signed" in workflow
    assert "publication_authorized\": False" in workflow
    assert "build_identity_sha256" in workflow
    assert "signing_certificate_sha256" in workflow
    assert "workflow_path" in workflow
    assert "workflow_conclusion" in workflow
    assert "reproducible_build" in workflow
    assert "CANDIDATE-METADATA.json" in workflow
    assert "softprops/action-gh-release" not in workflow


def test_android_apk_workflow_is_build_only_and_cannot_publish():
    workflow = (REPO_ROOT / ".github" / "workflows" / "android-apk.yml").read_text(encoding="utf-8")
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "packages: platform-tools" in workflow
    assert "versionCode='210'" in workflow
    assert "versionName='2.1.0'" in workflow
    assert "JobTomatik-v2.1.0-debug.apk" in workflow
    assert "publish-v2-release" not in workflow
    assert "softprops/action-gh-release" not in workflow
    assert "tag_name:" not in workflow
    assert "overwrite_files:" not in workflow
