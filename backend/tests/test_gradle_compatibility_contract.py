"""Regression coverage for the Android Gradle toolchain compatibility boundary."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLCHAIN_PATH = ROOT / ".jobtomatik-toolchain.env"
DEPENDABOT_PATH = ROOT / ".github" / "dependabot.yml"


def _toolchain() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in TOOLCHAIN_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_agp_8_toolchain_stays_below_gradle_9_6() -> None:
    toolchain = _toolchain()
    gradle_version = _version_tuple(toolchain["JOBTOMATIK_GRADLE_VERSION"])
    agp_major = int(
        toolchain["JOBTOMATIK_ANDROID_GRADLE_PLUGIN_VERSION"].split(".", 1)[0]
    )

    if agp_major < 9:
        assert gradle_version < (9, 6), (
            "Android Gradle Plugin 8.x uses a Gradle internal API removed in "
            "Gradle 9.6. Upgrade AGP before raising the wrapper to 9.6 or newer."
        )


def test_dependabot_blocks_only_the_incompatible_gradle_9_6_line() -> None:
    config = DEPENDABOT_PATH.read_text(encoding="utf-8")
    gradle_section = config.split("  - package-ecosystem: gradle", 1)[1].split(
        "\n  - package-ecosystem:", 1
    )[0]

    assert 'dependency-name: "gradle-wrapper"' in gradle_section
    assert '"[9.6,9.7)"' in gradle_section
    assert 'dependency-name: "*"' not in gradle_section
