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

    assert 'versionCode 210' in build_gradle
    assert 'versionName "2.1.0"' in build_gradle
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


def test_owner_command_v2_publisher_is_authorized_and_narrowly_scoped():
    workflow_path = (
        REPO_ROOT / ".github" / "workflows" / "publish-v1-command.yml"
    )
    workflow = workflow_path.read_text(encoding="utf-8")

    assert workflow_path.is_file()
    assert not (
        REPO_ROOT / ".github" / "workflows" / "publish-v1-authorized.yml"
    ).exists()
    assert "name: Publish JobTomatik v2 by authorized command" in workflow
    assert "issue_comment:" in workflow
    assert "github.event.issue.number == 470" in workflow
    assert "github.event.comment.body == '/publish-jobtomatik-v2.1.0'" in workflow
    assert "github.event.comment.user.login == 'TheHighBrid'" in workflow
    assert "chatgpt-codex-connector[bot]" not in workflow
    assert 'AUTHORIZED_PR_NUMBER: "470"' in workflow
    assert "Record authorized publication request" in workflow
    assert "Write publication result to workflow summary" in workflow
    assert "GITHUB_STEP_SUMMARY" in workflow
    assert "github.rest.issues.createComment" not in workflow
    assert "ref: main" in workflow
    assert "Freeze exact release source" in workflow
    assert 'echo "RELEASE_SOURCE_SHA=$SOURCE_SHA" >> "$GITHUB_ENV"' in workflow
    assert "Verify main has not moved since build" in workflow
    assert 'target_commitish: ${{ env.RELEASE_SOURCE_SHA }}' in workflow
    assert "release/SOURCE-COMMIT.txt" in workflow
    assert "versionCode='210'" in workflow
    assert "versionName='2.1.0'" in workflow
    assert "tag_name: v2.1.0" in workflow
    assert "JobTomatik-v2.1.0.apk" in workflow
    assert "group: publish-jobtomatik-v2.1.0" in workflow
    assert "group: publish-jobtomatik-v2.1.0" not in workflow.split("jobs:", 1)[0]
    assert (
        "  build-and-publish:\n"
        "    needs: authorize\n"
        "    concurrency:\n"
        "      group: publish-jobtomatik-v2.1.0\n"
        "      cancel-in-progress: false"
    ) in workflow
    assert "Refuse to overwrite an existing tag or release" in workflow
    assert "github.rest.git.getRef" in workflow
    assert "github.rest.repos.getReleaseByTag" in workflow
    assert "if (error.status !== 404) throw error" in workflow
    assert "core.setFailed" in workflow
    assert "overwrite_files: false" in workflow
    assert "overwrite_files: true" not in workflow
    assert "github.event.pull_request.head.sha" not in workflow
    assert "github.event.pull_request.merge_commit_sha" not in workflow


def test_android_apk_workflow_is_build_only_and_cannot_publish():
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "android-apk.yml"
    ).read_text(encoding="utf-8")

    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "versionCode='210'" in workflow
    assert "versionName='2.1.0'" in workflow
    assert "JobTomatik-v2.1.0-debug.apk" in workflow
    assert "publish-v2-release" not in workflow
    assert "softprops/action-gh-release" not in workflow
    assert "tag_name:" not in workflow
    assert "overwrite_files:" not in workflow
