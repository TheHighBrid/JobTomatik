"""Normalize retained Greenhouse dry-run reports into the M2 pilot ledger.

The command is deliberately evidence-only. It cannot enable live submission or
promote adapter maturity.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from app.services.greenhouse_pilot import (
    PilotEvidenceError,
    build_readiness_summary,
    load_ledger,
    merge_records,
    normalize_dry_run_report,
    render_readiness_markdown,
    write_ledger,
)


def _load_report(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PilotEvidenceError(f"report not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PilotEvidenceError(f"invalid JSON report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PilotEvidenceError(f"report must be a JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Retained greenhouse-live-certification.json file. Repeat as needed.",
    )
    parser.add_argument("--operator", required=True)
    parser.add_argument("--source-reference", required=True)
    parser.add_argument(
        "--ledger",
        default="greenhouse-pilot-ledger.jsonl",
    )
    parser.add_argument(
        "--summary-json",
        default="greenhouse-pilot-readiness.json",
    )
    parser.add_argument(
        "--summary-markdown",
        default="greenhouse-pilot-readiness.md",
    )
    parser.add_argument("--release-approval-reference", default="")
    args = parser.parse_args()

    ledger_path = Path(args.ledger)
    existing = load_ledger(ledger_path)
    incoming: List[Dict[str, Any]] = []

    for index, raw_path in enumerate(args.input, start=1):
        report_path = Path(raw_path)
        source_reference = args.source_reference
        if len(args.input) > 1:
            source_reference = f"{source_reference}:input-{index}"
        incoming.extend(
            normalize_dry_run_report(
                _load_report(report_path),
                operator=args.operator,
                source_reference=source_reference,
            )
        )

    merged = merge_records(existing, incoming)
    write_ledger(ledger_path, merged)
    summary = build_readiness_summary(
        merged,
        release_approval_reference=args.release_approval_reference or None,
    )

    summary_json_path = Path(args.summary_json)
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    summary_json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary_markdown_path = Path(args.summary_markdown)
    summary_markdown_path.parent.mkdir(parents=True, exist_ok=True)
    summary_markdown_path.write_text(
        render_readiness_markdown(summary),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
