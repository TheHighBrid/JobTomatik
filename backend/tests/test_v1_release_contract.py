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

    assert "services.gradle.org/distributions/gradle-8.11.1-bin.zip" in wrapper
    assert "file\\:///tmp/" not in wrapper
    assert "validateDistributionUrl=true" in wrapper


def test_android_release_config_contains_no_committed_signing_secret():
    build_gradle = (
        REPO_ROOT / "frontend" / "android" / "app" / "build.gradle"
    ).read_text(encoding="utf-8")

    assert 'versionCode 100' in build_gradle
    assert 'versionName "1.0.0"' in build_gradle
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


def test_release_documentation_is_present():
    required = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "CHANGELOG.md",
        REPO_ROOT / "SECURITY.md",
        REPO_ROOT / "docs" / "SETUP_TUTORIAL.md",
    ]

    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()]
    assert not missing, f"Missing release documentation: {missing}"


def test_owner_command_v1_publisher_is_frozen_and_narrowly_scoped():
    workflow_path = (
        REPO_ROOT / ".github" / "workflows" / "publish-v1-command.yml"
    )
    workflow = workflow_path.read_text(encoding="utf-8")

    frozen_sha = "6f7f9fa6a7d3c63516cde381410ac188364dba36"
    request_sha = "6a176eeacd7cc413b0456a6e204735459fc12313"

    assert workflow_path.is_file()
    assert not (
        REPO_ROOT / ".github" / "workflows" / "publish-v1-authorized.yml"
    ).exists()
    assert "issue_comment:" in workflow
    assert "github.event.issue.number == 81" in workflow
    assert "github.event.comment.body == '/publish-jobtomatik-v1.0.0'" in workflow
    assert "github.event.comment.user.login == 'TheHighBrid'" in workflow
    assert "chatgpt-codex-connector[bot]" in workflow
    assert "AUTHORIZED_HEAD_BRANCH: release/publish-v1.0.0" in workflow
    assert f"AUTHORIZED_REQUEST_SHA: {request_sha}" in workflow
    assert frozen_sha in workflow
    assert "files.length !== 1" in workflow
    assert "files[0].filename !== 'RELEASE_PUBLISH_REQUEST.txt'" in workflow
    assert "persist-credentials: false" in workflow
    assert "ref: ${{ env.RELEASE_SOURCE_SHA }}" in workflow
    assert "test \"$(git rev-parse HEAD)\" = \"$RELEASE_SOURCE_SHA\"" in workflow
    assert "github.event.pull_request.head.sha" not in workflow
    assert "github.event.pull_request.merge_commit_sha" not in workflow
