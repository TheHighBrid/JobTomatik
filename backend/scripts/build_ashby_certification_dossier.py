#!/usr/bin/env python3
"""Generate the canonical Ashby dry-run certification dossier from locked inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.ashby_readiness import build_ashby_certification_dossier


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-junit", required=True)
    parser.add_argument("--handoff-junit", required=True)
    parser.add_argument("--live-smoke", required=True)
    parser.add_argument("--synthetic-live", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--adapter-version", required=True)
    parser.add_argument(
        "--repository",
        default="TheHighBrid/JobTomatik",
    )
    parser.add_argument(
        "--output",
        default="evidence/ashby-certification-dossier.json",
    )
    args = parser.parse_args()

    dossier = build_ashby_certification_dossier(
        fixture_junit=Path(args.fixture_junit),
        handoff_junit=Path(args.handoff_junit),
        live_smoke_json=Path(args.live_smoke),
        synthetic_live_json=Path(args.synthetic_live),
        source_commit=args.source_commit,
        generated_at=args.generated_at,
        adapter_version=args.adapter_version,
        repository=args.repository,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(dossier, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(dossier, indent=2, sort_keys=True))
    return 0 if dossier["readiness"]["dry_run_certification_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
