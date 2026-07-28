from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLCHAIN_PATH = ROOT / ".jobtomatik-toolchain.env"
VERIFY_SCRIPT = ROOT / "scripts" / "verify.sh"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "reproducible-verification.yml"
ANDROID_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "android-apk.yml"
README_PATH = ROOT / "README.md"


def _toolchain() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in TOOLCHAIN_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_verification_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(VERIFY_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_canonical_toolchain_matches_repository_files() -> None:
    toolchain = _toolchain()
    wrapper = (
        ROOT
        / "frontend"
        / "android"
        / "gradle"
        / "wrapper"
        / "gradle-wrapper.properties"
    ).read_text(encoding="utf-8")
    android_build = (ROOT / "frontend" / "android" / "build.gradle").read_text(
        encoding="utf-8"
    )
    android_variables = (
        ROOT / "frontend" / "android" / "variables.gradle"
    ).read_text(encoding="utf-8")

    assert toolchain["JOBTOMATIK_PYTHON_MAJOR_MINOR"] == "3.11"
    assert toolchain["JOBTOMATIK_NODE_MAJOR"] == "20"
    assert toolchain["JOBTOMATIK_JAVA_MAJOR"] == "21"
    assert (
        f"gradle-{toolchain['JOBTOMATIK_GRADLE_VERSION']}-bin.zip" in wrapper
    )
    assert (
        "com.android.tools.build:gradle:"
        f"{toolchain['JOBTOMATIK_ANDROID_GRADLE_PLUGIN_VERSION']}"
        in android_build
    )
    api = toolchain["JOBTOMATIK_ANDROID_API"]
    assert f"compileSdkVersion = {api}" in android_variables
    assert f"targetSdkVersion = {api}" in android_variables


def test_verification_modes_and_fail_safe_environment_are_explicit() -> None:
    script = VERIFY_SCRIPT.read_text(encoding="utf-8")

    for mode in (
        "bootstrap",
        "toolchain",
        "fast",
        "backend-tests",
        "migration",
        "safety",
        "backend",
        "frontend",
        "deployment",
        "android",
        "full",
    ):
        assert f"  {mode})" in script

    for assignment in (
        "ALLOW_REAL_APPLICATION_SUBMIT=false",
        "AUTOPILOT_ENABLED=false",
        "ENABLE_RESUMABLE_HANDOFFS=false",
    ):
        assert f"export {assignment}" in script

    assert "GREENHOUSE_SUPERVISED_PILOT_ENABLED=false" in script
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in script
    assert "verification-pytest-output.txt" in script


def test_reproducible_workflow_executes_every_verification_lane() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert 'python-version: "3.11"' in workflow
    assert 'node-version: "20"' in workflow
    assert 'java-version: "21"' in workflow
    for mode in (
        "fast",
        "backend-tests",
        "migration",
        "safety",
        "frontend",
        "deployment",
        "android",
    ):
        assert f"bash scripts/verify.sh {mode}" in workflow
    assert "Run full backend and browser tests" in workflow
    assert "Upload backend verification report" in workflow
    assert "Run migration smoke test" in workflow
    assert "Verify safety and adapter maturity" in workflow
    assert "Assert every reproducibility gate passed" in workflow


def test_android_workflow_and_readme_use_canonical_versions() -> None:
    android_workflow = ANDROID_WORKFLOW_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert 'node-version: "20"' in android_workflow
    assert 'node-version: "22"' not in android_workflow
    assert "Gradle 9.5.1" in readme
    assert "Android Gradle Plugin 8.13.2" in readme
    assert "Gradle 8.11.1" not in readme
    assert "Android Gradle Plugin 8.7.2" not in readme
    assert "bash scripts/verify.sh full" in readme
