"""Execute or review the separately authorized Recovery Gate 2 public proof-v2."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path

from app.services.recovery_gate2 import digest, evaluate, identity, provenance, run_gate

PROOF_SCHEMA = "jobtomatik.recovery.gate2.public-proof.v2"
AUTHORIZED_PROOF_ID = "gate2-public-proof-v2-20261004"
AUTHORIZED_TARGET_URL = "https://job-boards.greenhouse.io/gitlab/jobs/8860302002"
WORKFLOW_PATH = ".github/workflows/recovery-gate2-public-v2.yml"
REQUIRED_CHECKS = (
    "synthetic-controls",
    "proof-v2-controls",
    "exact-head-acceptance",
    "pytest",
    "owned-browser-compose-proof",
    "phase0-fastapi-celery-proof",
    "backend-browser-migration",
    "integrated-backend",
    "fast-gate",
    "dependency-audit",
    "Analyze python",
    "Analyze javascript-typescript",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _append_error(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def validate_authorized_inputs(proof_id: str, target_url: str) -> None:
    """Reject substitutions before any browser or external network activity."""
    _require(proof_id == AUTHORIZED_PROOF_ID, "Unapproved Gate 2 proof identity")
    _require(target_url == AUTHORIZED_TARGET_URL, "Unapproved Gate 2 target")
    _require(identity(target_url) == identity(AUTHORIZED_TARGET_URL), "Gate 2 target identity changed")


def proof_target_key(proof_id: str, target_url: str) -> str:
    validate_authorized_inputs(proof_id, target_url)
    payload = {"proof_id": proof_id, "target": identity(target_url)}
    return digest(json.dumps(payload, sort_keys=True).encode())


def reserve_proof(path: Path, proof_id: str, target_url: str) -> dict:
    """Reserve the code-reviewed proof identity independently of the v1 target/profile attempt key."""
    target_key = proof_target_key(proof_id, target_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=5) as database:
        database.execute(
            "CREATE TABLE IF NOT EXISTS proof_runs ("
            "proof_id TEXT PRIMARY KEY, target_key TEXT NOT NULL, created REAL NOT NULL)"
        )
        database.execute(
            "INSERT INTO proof_runs (proof_id, target_key, created) VALUES (?, ?, ?)",
            (proof_id, target_key, time.time()),
        )
    return {"proof_id": proof_id, "target_key": target_key, "ledger": str(path)}


def workflow_context(execution_sha: str) -> dict:
    """Bind accepted proof-v2 evidence to a first-attempt GitHub Actions run on main."""
    _require(os.getenv("GITHUB_ACTIONS") == "true", "Gate 2 proof-v2 must run in GitHub Actions")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", execution_sha or "")), "Invalid execution SHA")
    _require(os.getenv("GITHUB_SHA") == execution_sha, "Workflow SHA differs from approved execution SHA")
    _require(os.getenv("GITHUB_REF") == "refs/heads/main", "Gate 2 proof-v2 must dispatch from main")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "")
    workflow_ref = os.getenv("GITHUB_WORKFLOW_REF", "")
    _require(run_id.isdigit() and int(run_id) > 0, "GitHub run ID missing")
    _require(run_attempt == "1", "Gate 2 proof-v2 reruns are prohibited")
    _require(
        workflow_ref.endswith(f"/{WORKFLOW_PATH}@refs/heads/main"),
        "Unexpected Gate 2 proof-v2 workflow ref",
    )
    source = provenance()
    _require(source.get("git_sha") == execution_sha, "Checked-out source differs from approved execution SHA")
    return {
        "run_id": int(run_id),
        "run_attempt": 1,
        "workflow_ref": workflow_ref,
        "execution_sha": execution_sha,
        "source_sha256": source.get("source_sha256"),
    }


def load_ci_receipts(path: Path, execution_sha: str, proof_id: str, target_url: str, run_id: int) -> dict:
    """Validate and retain the exact-head prerequisite receipts supplied by the workflow."""
    data = json.loads(path.read_text())
    _require(data.get("schema") == PROOF_SCHEMA, "CI receipt schema mismatch")
    _require(data.get("sha") == execution_sha, "CI receipts are not for the execution SHA")
    _require(data.get("proof_id") == proof_id, "CI receipts use a different proof identity")
    _require(data.get("target_url") == target_url, "CI receipts use a different target")
    _require(data.get("run_id") == run_id, "CI receipts use a different workflow run")
    receipts = data.get("receipts")
    _require(isinstance(receipts, list), "CI receipts missing")
    by_name = {item.get("name"): item for item in receipts if isinstance(item, dict)}
    _require(len(by_name) == len(receipts), "CI receipt names are duplicate or missing")
    _require(set(by_name) == set(REQUIRED_CHECKS), "Canonical exact-head CI receipt set is incomplete")
    for name in REQUIRED_CHECKS:
        receipt = by_name[name]
        _require(receipt.get("head_sha") == execution_sha, f"Wrong exact-head receipt: {name}")
        _require(receipt.get("status") == "completed", f"Incomplete exact-head receipt: {name}")
        _require(receipt.get("conclusion") == "success", f"Failed exact-head receipt: {name}")
        _require(isinstance(receipt.get("id"), int) and receipt["id"] > 0, f"Invalid receipt ID: {name}")
    return data


def _proof_identity_errors(record: dict) -> list[str]:
    errors: list[str] = []
    proof = record.get("proof_v2") or {}
    source = record.get("source") or {}
    _append_error(errors, proof.get("schema") == PROOF_SCHEMA, "proof-v2 schema missing")
    _append_error(errors, proof.get("proof_id") == AUTHORIZED_PROOF_ID, "proof-v2 identity mismatch")
    _append_error(errors, proof.get("target_url") == AUTHORIZED_TARGET_URL, "proof-v2 target mismatch")
    _append_error(
        errors,
        proof.get("target_key") == proof_target_key(AUTHORIZED_PROOF_ID, AUTHORIZED_TARGET_URL),
        "proof-v2 target key mismatch",
    )
    execution_sha = proof.get("execution_sha", "")
    _append_error(errors, bool(re.fullmatch(r"[0-9a-f]{40}", execution_sha)), "proof-v2 execution SHA missing")
    _append_error(errors, execution_sha == source.get("git_sha"), "proof-v2 execution/source SHA mismatch")
    _append_error(
        errors,
        isinstance(proof.get("github_run_id"), int) and proof["github_run_id"] > 0,
        "proof-v2 GitHub run ID missing",
    )
    _append_error(errors, proof.get("github_run_attempt") == 1, "proof-v2 rerun evidence is invalid")
    workflow_ref = str(proof.get("github_workflow_ref") or "")
    _append_error(
        errors,
        workflow_ref.endswith(f"/{WORKFLOW_PATH}@refs/heads/main"),
        "proof-v2 workflow ref mismatch",
    )
    return errors


def _receipt_errors(record: dict, directory: Path) -> list[str]:
    errors: list[str] = []
    proof = record.get("proof_v2") or {}
    execution_sha = proof.get("execution_sha", "")
    try:
        payload = (directory / "ci-prerequisites.json").read_bytes()
        receipts = json.loads(payload)
    except (OSError, json.JSONDecodeError):
        return ["retained CI prerequisites missing or invalid"]
    _append_error(errors, proof.get("ci_receipts_sha256") == digest(payload), "CI receipt digest mismatch")
    _append_error(errors, receipts.get("schema") == PROOF_SCHEMA, "retained CI receipt schema mismatch")
    _append_error(errors, receipts.get("sha") == execution_sha, "retained CI receipt SHA mismatch")
    _append_error(errors, receipts.get("proof_id") == AUTHORIZED_PROOF_ID, "retained CI proof identity mismatch")
    _append_error(errors, receipts.get("target_url") == AUTHORIZED_TARGET_URL, "retained CI target mismatch")
    _append_error(errors, receipts.get("run_id") == proof.get("github_run_id"), "retained CI run ID mismatch")
    items = receipts.get("receipts") or []
    by_name = {item.get("name"): item for item in items if isinstance(item, dict)}
    _append_error(errors, len(by_name) == len(items), "retained CI receipt names are duplicate or missing")
    _append_error(errors, set(by_name) == set(REQUIRED_CHECKS), "retained canonical CI receipt set incomplete")
    for name in REQUIRED_CHECKS:
        item = by_name.get(name) or {}
        _append_error(errors, item.get("head_sha") == execution_sha, f"retained wrong-head receipt: {name}")
        _append_error(
            errors,
            item.get("status") == "completed" and item.get("conclusion") == "success",
            f"retained unsuccessful receipt: {name}",
        )
    return errors


def _reservation_errors(directory: Path) -> list[str]:
    try:
        with sqlite3.connect(f"file:{directory / 'ledger.sqlite'}?mode=ro", uri=True) as database:
            rows = database.execute(
                "SELECT target_key FROM proof_runs WHERE proof_id = ?", (AUTHORIZED_PROOF_ID,)
            ).fetchall()
    except sqlite3.Error:
        return ["retained proof-v2 reservation missing or invalid"]
    expected = proof_target_key(AUTHORIZED_PROOF_ID, AUTHORIZED_TARGET_URL)
    return [] if rows == [(expected,)] else ["retained proof-v2 reservation missing or ambiguous"]


def proof_metadata_errors(record: dict, directory: Path) -> list[str]:
    """Independently validate retained proof-v2 identity, workflow and prerequisite evidence."""
    return _proof_identity_errors(record) + _receipt_errors(record, directory) + _reservation_errors(directory)


def _current_source_errors(record: dict) -> list[str]:
    try:
        current = provenance()
    except RuntimeError as exc:
        return [f"Current source attestation failed: {exc}"]
    recorded = record.get("source") or {}
    if (
        current.get("git_sha") == recorded.get("git_sha")
        and current.get("source_sha256") == recorded.get("source_sha256")
        and current.get("inputs") == recorded.get("inputs")
    ):
        return []
    return ["Executed source differs from the reviewed Git checkout"]


def review_v2(record: dict, directory: Path) -> list[str]:
    return evaluate(record, directory) + proof_metadata_errors(record, directory) + _current_source_errors(record)


def execute(args: argparse.Namespace) -> tuple[dict, list[str]]:
    validate_authorized_inputs(args.proof_id, args.url)
    context = workflow_context(args.execution_sha)
    reserve_proof(args.ledger, args.proof_id, args.url)
    receipts = load_ci_receipts(
        args.ci_receipts, args.execution_sha, args.proof_id, args.url, context["run_id"]
    )
    record = asyncio.run(run_gate(args.url, args.evidence, args.ledger))
    retained_receipts = args.evidence / "ci-prerequisites.json"
    shutil.copyfile(args.ci_receipts, retained_receipts)
    record["proof_v2"] = {
        "schema": PROOF_SCHEMA,
        "proof_id": args.proof_id,
        "target_url": args.url,
        "target_key": proof_target_key(args.proof_id, args.url),
        "execution_sha": args.execution_sha,
        "github_run_id": context["run_id"],
        "github_run_attempt": context["run_attempt"],
        "github_workflow_ref": context["workflow_ref"],
        "ci_receipts_sha256": digest(retained_receipts.read_bytes()),
        "ci_receipt_count": len(receipts["receipts"]),
    }
    errors = review_v2(record, args.evidence)
    record["violations"] = errors
    record["verdict"] = "PASS" if not errors else "NOT_PROVEN"
    (args.evidence / "summary.json").write_text(json.dumps(record, indent=2))
    return record, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url")
    parser.add_argument("--proof-id")
    parser.add_argument("--execution-sha")
    parser.add_argument("--ci-receipts", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--review", action="store_true")
    args = parser.parse_args()
    if args.review:
        record = json.loads((args.evidence / "summary.json").read_text())
        errors = review_v2(record, args.evidence)
    else:
        if not all((args.url, args.proof_id, args.execution_sha, args.ci_receipts, args.ledger)):
            parser.error("--url, --proof-id, --execution-sha, --ci-receipts and --ledger are required")
        record, errors = execute(args)
    if record.get("evidence_kind") != "public_greenhouse":
        errors.append("Synthetic runner verification cannot prove the public Gate 2")
    print(json.dumps({"gate": 2, "proof": "v2", "verdict": "NOT_PROVEN" if errors else "PASS",
                      "violations": errors}))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
