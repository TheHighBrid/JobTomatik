#!/usr/bin/env python3
"""Fail on npm production vulnerabilities outside reviewed, inapplicable findings."""

from __future__ import annotations

import json
import sys
from pathlib import Path


# JobTomatik is a client-rendered Vite SPA and does not enable React Router RSC
# mode or server actions. No patched React Router release exists as of 2026-07-31.
# Remove this exception as soon as an upstream patched release is available.
ALLOWED_ADVISORY_URLS = {
    "https://github.com/advisories/GHSA-qwww-vcr4-c8h2",
}


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

    unapproved: list[str] = []
    observed_urls: set[str] = set()
    for package, finding in vulnerabilities.items():
        if not isinstance(finding, dict):
            unapproved.append(str(package))
            continue
        via = finding.get("via") or []
        detailed = [item for item in via if isinstance(item, dict)]
        if detailed:
            urls = {str(item.get("url") or "") for item in detailed}
            observed_urls.update(urls)
            if not urls or not urls.issubset(ALLOWED_ADVISORY_URLS):
                unapproved.append(str(package))
        elif not all(str(item) in vulnerabilities for item in via):
            unapproved.append(str(package))

    if unapproved:
        print(
            "Unapproved production npm vulnerabilities: "
            + ", ".join(sorted(unapproved)),
            file=sys.stderr,
        )
        return 1

    unused = ALLOWED_ADVISORY_URLS - observed_urls
    if vulnerabilities and unused == ALLOWED_ADVISORY_URLS:
        print("Audit findings did not resolve to the reviewed advisory", file=sys.stderr)
        return 1

    if vulnerabilities:
        print(
            "Production npm audit passed with reviewed RSC-only exception: "
            + ", ".join(sorted(observed_urls))
        )
    else:
        print("Production npm audit passed with no vulnerabilities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
