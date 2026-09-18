#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import subprocess
import sys
from pathlib import Path

try:
    from packaging.requirements import Requirement
except ImportError:  # pragma: no cover - pip vendors packaging in supported runtimes
    from pip._vendor.packaging.requirements import Requirement


class EnvironmentRequirementError(RuntimeError):
    pass


def active_requirements(path: Path) -> list[Requirement]:
    requirements: list[Requirement] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-", "--")):
            raise EnvironmentRequirementError(
                f"Unsupported requirements directive in runtime contract: {line}"
            )
        requirement = Requirement(line)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        requirements.append(requirement)
    return requirements


def requirement_drift(path: Path) -> list[str]:
    failures: list[str] = []
    for requirement in active_requirements(path):
        try:
            installed = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            failures.append(f"{requirement.name}: required {requirement.specifier}, installed=MISSING")
            continue
        if requirement.specifier and not requirement.specifier.contains(
            installed,
            prereleases=True,
        ):
            failures.append(
                f"{requirement.name}: required {requirement.specifier}, installed={installed}"
            )
    return failures


def pip_check_failures() -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return []
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return [line for line in output.splitlines() if line.strip()]


def verify_environment(path: Path) -> dict[str, object]:
    drift = requirement_drift(path)
    dependency_failures = pip_check_failures()
    if drift or dependency_failures:
        details = [*drift, *dependency_failures]
        raise EnvironmentRequirementError("; ".join(details))
    return {
        "ok": True,
        "requirements": str(path),
        "checked": len(active_requirements(path)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_environment(args.requirements)
    except (EnvironmentRequirementError, ValueError) as exc:
        print(f"PYTHON_ENV_REQUIREMENTS_DRIFT {exc}", file=sys.stderr)
        return 1
    print(
        "PYTHON_ENV_REQUIREMENTS_OK "
        f"requirements={result['requirements']} checked={result['checked']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
