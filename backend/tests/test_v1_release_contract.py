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


def test_release_documentation_is_present():
    required = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "CHANGELOG.md",
        REPO_ROOT / "SECURITY.md",
        REPO_ROOT / "docs" / "SETUP_TUTORIAL.md",
    ]

    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()]
    assert not missing, f"Missing release documentation: {missing}"
