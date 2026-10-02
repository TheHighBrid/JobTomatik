#!/usr/bin/env python3
"""Fail on any production npm vulnerability reported by npm audit."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_npm_audit.py <npm-audit.json>", file=sys.stderr)
        return 2

    try:
        payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Invalid npm audit report: {exc}", file=sys.stderr)
        return 2

    vulnerabilities = payload.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        print("Invalid npm audit report: vulnerabilities object missing", file=sys.stderr)
        return 2

    if vulnerabilities:
        print(
            "Unapproved production npm vulnerabilities: "
            + ", ".join(sorted(str(package) for package in vulnerabilities)),
            file=sys.stderr,
        )
        return 1

    print("Production npm audit passed with no vulnerabilities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
