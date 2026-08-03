"""Regression coverage for the Android Gradle toolchain compatibility boundary."""

from pathlib import Path
from typing import Any

import yaml


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


def _dependabot_config() -> dict[str, Any]:
    config = yaml.safe_load(DEPENDABOT_PATH.read_text(encoding="utf-8"))
    assert isinstance(config, dict)
    return config


def _android_gradle_update(config: dict[str, Any]) -> dict[str, Any]:
    updates = config.get("updates")
    assert isinstance(updates, list)
    matches = [
        update
        for update in updates
        if isinstance(update, dict)
        and update.get("package-ecosystem") == "gradle"
        and update.get("directory") == "/frontend/android"
    ]
    assert len(matches) == 1
    return matches[0]


def test_agp_8_toolchain_stays_below_gradle_9_6() -> None:
    toolchain = _toolchain()
    gradle_version = _version_tuple(toolchain["JOBTOMATIK_GRADLE_VERSION"])
    agp_major = int(
        toolchain["JOBTOMATIK_ANDROID_GRADLE_PLUGIN_VERSION"].split(".", 1)[0]
    )

    if agp_major == 8:
        assert gradle_version < (9, 6), (
            "Android Gradle Plugin 8.x is incompatible with Gradle 9.6 and later "
            "because Gradle removed Problems API internals used by the plugin."
        )


def test_dependabot_blocks_gradle_9_6_and_later_for_agp_8() -> None:
    toolchain = _toolchain()
    agp_major = int(
        toolchain["JOBTOMATIK_ANDROID_GRADLE_PLUGIN_VERSION"].split(".", 1)[0]
    )
    assert agp_major == 8, "Revisit the Gradle ignore when upgrading beyond AGP 8.x."

    gradle_update = _android_gradle_update(_dependabot_config())
    ignore = gradle_update.get("ignore")
    assert isinstance(ignore, list)

    wrapper_rules = [
        rule
        for rule in ignore
        if isinstance(rule, dict) and rule.get("dependency-name") == "gradle-wrapper"
    ]
    assert wrapper_rules == [
        {"dependency-name": "gradle-wrapper", "versions": ["[9.6,)"]}
    ]
    assert not any(
        isinstance(rule, dict) and rule.get("dependency-name") == "*"
        for rule in ignore
    )
