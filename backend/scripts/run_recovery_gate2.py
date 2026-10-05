"""Execute one synthetic-identity public Greenhouse dry-run, or review its evidence."""
import argparse
import asyncio
import json
import subprocess
from pathlib import Path

from app.services.recovery_gate2 import ROOT, digest, evaluate, run_gate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--review", action="store_true")
    args = parser.parse_args()
    if args.review:
        record = json.loads((args.evidence / "summary.json").read_text())
        errors = evaluate(record, args.evidence)
    else:
        if not args.url or not args.ledger:
            parser.error("--url and --ledger are required for a run")
        record = asyncio.run(run_gate(args.url, args.evidence, args.ledger))
        errors = record["violations"]
    if record.get("evidence_kind") != "public_greenhouse":
        errors.append("Synthetic runner verification cannot prove the public Gate 2")
    if not errors:
        for path, expected in record["source"]["inputs"].items():
            try:
                payload = subprocess.check_output(
                    ["git", "-C", str(ROOT), "show", f'{record["source"]["git_sha"]}:{path}'])
                if digest(payload) != expected:
                    errors.append(f"Executed source differs from recorded Git revision: {path}")
            except subprocess.CalledProcessError:
                errors.append(f"Recorded Git source is unavailable: {path}")
    print(json.dumps({"gate": 2, "verdict": "NOT_PROVEN" if errors else "PASS", "violations": errors}))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
