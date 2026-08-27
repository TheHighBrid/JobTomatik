import json
from pathlib import Path

from app.config import Settings


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_android_gradle_wrapper_is_portable():
    wrapper = (
        REPO_ROOT
        / "frontend"
        / "android"
        / "gradle"
        / "wrapper"
        / "gradle-wrapper.properties"
    ).read_text(encoding="utf-8")

    assert "distributionUrl=https\\://services.gradle.org/distributions/gradle-" in wrapper
    assert "-bin.zip" in wrapper
    assert r"file\:///tmp/" not in wrapper
    assert "validateDistributionUrl=true" in wrapper


def test_android_release_config_contains_no_committed_signing_secret():
    build_gradle = (
        REPO_ROOT / "frontend" / "android" / "app" / "build.gradle"
    ).read_text(encoding="utf-8")

    assert 'versionCode 200' in build_gradle
    assert 'versionName "2.0.0"' in build_gradle
    assert "JOBTOMATIK_KEYSTORE_PATH" in build_gradle
    assert "/home/user/JobTomatik" not in build_gradle
    assert "jobtomatik123" not in build_gradle


def test_android_manifest_protects_local_app_data():
    manifest = (
        REPO_ROOT
        / "frontend"
        / "android"
        / "app"
        / "src"
        / "main"
        / "AndroidManifest.xml"
    ).read_text(encoding="utf-8")

    assert 'android:allowBackup="false"' in manifest
    assert 'android:usesCleartextTraffic="true"' in manifest
    assert 'android.permission.INTERNET' in manifest


def test_frontend_apk_scripts_run_gradle_assembly():
    package = json.loads(
        (REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )

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
    client = (
        REPO_ROOT / "frontend" / "src" / "api" / "client.js"
    ).read_text(encoding="utf-8")
    launcher = (REPO_ROOT / "termux-start.sh").read_text(encoding="utf-8")

    assert "DATABASE_URL=sqlite:///./jobtomatik.db" in active_lines
    assert not any(line.startswith("DATABASE_URL=postgresql://") for line in active_lines)
    assert "VITE_API_URL=http://127.0.0.1:8010" in active_lines
    assert "import.meta.env.VITE_API_URL || 'http://127.0.0.1:8010'" in client
    assert "import.meta.env.VITE_API_URL || 'http://localhost:8000'" not in client
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
    ]

    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()]
    assert not missing, f"Missing release documentation: {missing}"


def test_owner_v2_publisher_is_exact_commit_authorized_and_narrowly_scoped():
    workflow_path = (
        REPO_ROOT / ".github" / "workflows" / "publish-v1-command.yml"
    )
    workflow = workflow_path.read_text(encoding="utf-8")

    assert workflow_path.is_file()
    assert not (
        REPO_ROOT / ".github" / "workflows" / "publish-v1-authorized.yml"
    ).exists()
    assert "name: Publish JobTomatik v2 by owner-authorized exact commit" in workflow
    assert "workflow_dispatch:" in workflow
    assert "source_commit:" in workflow
    assert "authorization_reference:" in workflow
    assert "github.actor == 'TheHighBrid'" in workflow
    assert "issue_comment:" not in workflow
    assert "chatgpt-codex-connector[bot]" not in workflow
    assert '[[ "$EXPECTED_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]' in workflow
    assert 'test "$EXPECTED_SOURCE_COMMIT" = "$MAIN_HEAD"' in workflow
    assert "ref: ${{ needs.authorize-exact-release.outputs.source_commit }}" in workflow
    assert 'test "$(git rev-parse origin/main)" = "$SOURCE_COMMIT"' in workflow
    assert "versionCode='200'" in workflow
    assert "versionName='2.0.0'" in workflow
    assert "tag_name: v2.0.0" in workflow
    assert "target_commitish: ${{ needs.authorize-exact-release.outputs.source_commit }}" in workflow
    assert "target_commitish: main" not in workflow
    assert "overwrite_files: false" in workflow
    assert "JobTomatik-v2.00.apk" in workflow
    assert "JobTomatik-v2.00.sha256" in workflow
    assert "SOURCE-COMMIT.txt" in workflow
    assert "APK-SIGNING.txt" in workflow
