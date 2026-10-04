"""Synthetic-only tests for the separately authorized Gate 2 public proof-v2 contract."""
import json
import sqlite3
from pathlib import Path

import pytest

from app.services import recovery_gate2 as gate
from scripts import run_recovery_gate2_v2 as v2


def _receipts(sha: str, run_id: int) -> dict:
    return {
        "schema": v2.PROOF_SCHEMA,
        "proof_id": v2.AUTHORIZED_PROOF_ID,
        "target_url": v2.AUTHORIZED_TARGET_URL,
        "sha": sha,
        "run_id": run_id,
        "receipts": [
            {"name": name, "id": index + 1, "head_sha": sha,
             "status": "completed", "conclusion": "success", "url": "https://example.test/check"}
            for index, name in enumerate(v2.REQUIRED_CHECKS)
        ],
    }


def test_authorized_inputs_are_exact():
    v2.validate_authorized_inputs(v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL)
    with pytest.raises(RuntimeError, match="proof identity"):
        v2.validate_authorized_inputs("gate2-public-proof-v2-other", v2.AUTHORIZED_TARGET_URL)
    with pytest.raises(RuntimeError, match="target"):
        v2.validate_authorized_inputs(v2.AUTHORIZED_PROOF_ID,
                                      "https://job-boards.greenhouse.io/gitlab/jobs/8860302003")


def test_proof_v2_reservation_is_one_use_and_separate_from_v1_attempt(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    target = gate.identity(v2.AUTHORIZED_TARGET_URL)
    legacy = gate.claim_attempt(ledger, target)
    proof = v2.reserve_proof(ledger, v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL)
    assert legacy["duplicate_rejected"] is True
    assert proof["target_key"] == v2.proof_target_key(v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL)
    with pytest.raises(sqlite3.IntegrityError):
        v2.reserve_proof(ledger, v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL)
    with sqlite3.connect(ledger) as database:
        assert database.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM proof_runs").fetchone()[0] == 1


def test_workflow_context_requires_first_attempt_main_and_exact_head(monkeypatch):
    head = gate.provenance()["git_sha"]
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", head)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv(
        "GITHUB_WORKFLOW_REF",
        f"TheHighBrid/JobTomatik/{v2.WORKFLOW_PATH}@refs/heads/main",
    )
    context = v2.workflow_context(head)
    assert context["run_id"] == 12345 and context["run_attempt"] == 1
    assert context["source_sha256"]
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with pytest.raises(RuntimeError, match="reruns"):
        v2.workflow_context(head)


def test_ci_receipts_require_complete_exact_head_set(tmp_path):
    sha = "a" * 40
    path = tmp_path / "receipts.json"
    path.write_text(json.dumps(_receipts(sha, 77)))
    data = v2.load_ci_receipts(
        path, sha, v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL, 77
    )
    assert len(data["receipts"]) == len(v2.REQUIRED_CHECKS)
    broken = _receipts(sha, 77)
    broken["receipts"] = [item for item in broken["receipts"] if item["name"] != "Analyze python"]
    path.write_text(json.dumps(broken))
    with pytest.raises(RuntimeError, match="incomplete"):
        v2.load_ci_receipts(path, sha, v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL, 77)


def test_proof_metadata_requires_retained_ci_and_proof_reservation(tmp_path):
    sha = "b" * 40
    run_id = 88
    receipts = _receipts(sha, run_id)
    receipts_path = tmp_path / "ci-prerequisites.json"
    receipts_path.write_text(json.dumps(receipts))
    ledger = tmp_path / "ledger.sqlite"
    v2.reserve_proof(ledger, v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL)
    record = {
        "source": {"git_sha": sha},
        "proof_v2": {
            "schema": v2.PROOF_SCHEMA,
            "proof_id": v2.AUTHORIZED_PROOF_ID,
            "target_url": v2.AUTHORIZED_TARGET_URL,
            "target_key": v2.proof_target_key(v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL),
            "execution_sha": sha,
            "github_run_id": run_id,
            "github_run_attempt": 1,
            "github_workflow_ref":
                f"TheHighBrid/JobTomatik/{v2.WORKFLOW_PATH}@refs/heads/main",
            "ci_receipts_sha256": gate.digest(receipts_path.read_bytes()),
        },
    }
    assert v2.proof_metadata_errors(record, tmp_path) == []
    record["proof_v2"]["github_run_attempt"] = 2
    assert "proof-v2 rerun evidence is invalid" in v2.proof_metadata_errors(record, tmp_path)


def test_current_source_attestation_fails_closed(monkeypatch):
    recorded = {"git_sha": "a" * 40, "source_sha256": "1" * 64, "inputs": {"x.py": "2" * 64}}
    monkeypatch.setattr(v2, "provenance", lambda: dict(recorded))
    assert v2._current_source_errors({"source": recorded}) == []
    monkeypatch.setattr(v2, "provenance", lambda: {**recorded, "git_sha": "b" * 40})
    assert v2._current_source_errors({"source": recorded}) == [
        "Executed source differs from the reviewed Git checkout"
    ]


def test_v2_workflow_is_separate_from_consumed_v1_and_requires_codeql():
    root = Path(gate.ROOT)
    v1 = (root / ".github/workflows/recovery-gate2-public.yml").read_text()
    v2_text = (root / v2.WORKFLOW_PATH).read_text()
    assert "sol61/gate2-public-proof" in v1
    assert "on:\n  create:" in v1
    assert "workflow_dispatch:" in v2_text
    assert "on:\n  create:" not in v2_text
    assert v2.AUTHORIZED_PROOF_ID in v2_text
    assert v2.AUTHORIZED_TARGET_URL in v2_text
    assert "GITHUB_RUN_ATTEMPT" in v2_text
    assert "recovery-gate2-public-v2.yml" in v2_text
    assert "proof-v2-controls" in v2_text
    assert "Analyze python" in v2_text
    assert "Analyze javascript-typescript" in v2_text
    assert "--proof-id" in v2_text
    assert "--execution-sha" in v2_text


def test_dispatch_inputs_are_not_interpolated_inside_shell_commands():
    workflow = (Path(gate.ROOT) / v2.WORKFLOW_PATH).read_text()
    assert 'DISPATCH_EXECUTION_SHA: ${{ inputs.execution_sha }}' in workflow
    assert 'DISPATCH_PROOF_ID: ${{ inputs.proof_id }}' in workflow
    assert 'DISPATCH_TARGET_URL: ${{ inputs.target_url }}' in workflow
    assert '--url "${{ inputs.target_url }}"' not in workflow
    assert '--proof-id "${{ inputs.proof_id }}"' not in workflow
    assert '--execution-sha "${{ inputs.execution_sha }}"' not in workflow
    assert '--url "$DISPATCH_TARGET_URL"' in workflow
    assert '--proof-id "$DISPATCH_PROOF_ID"' in workflow
    assert '--execution-sha "$DISPATCH_EXECUTION_SHA"' in workflow


def test_every_required_receipt_has_a_main_push_producer():
    root = Path(gate.ROOT)
    producers = {
        ".github/workflows/recovery-gate2.yml": ("synthetic-controls",),
        ".github/workflows/recovery-gate2-proof-v2.yml": ("proof-v2-controls",),
        ".github/workflows/current-head-final-acceptance.yml": ("exact-head-acceptance",),
        ".github/workflows/backend-tests.yml": ("pytest",),
        ".github/workflows/onehost-fixture-gate.yml": ("owned-browser-compose-proof",),
        ".github/workflows/onehost-api-celery-gate.yml": ("phase0-fastapi-celery-proof",),
        ".github/workflows/reproducible-verification.yml": (
            "backend-browser-migration", "fast-gate", "dependency-audit",
        ),
        ".github/workflows/post-merge-stabilization.yml": ("integrated-backend",),
    }
    produced = set()
    for path, checks in producers.items():
        workflow = (root / path).read_text()
        assert "push:" in workflow and "main" in workflow, path
        for check in checks:
            assert f"{check}:" in workflow, f"{check} missing from {path}"
            produced.add(check)
    codeql = (root / ".github/workflows/codeql.yml").read_text()
    assert "push:" in codeql and "main" in codeql
    assert "python" in codeql and "javascript-typescript" in codeql
    produced.update({"Analyze python", "Analyze javascript-typescript"})
    assert produced == set(v2.REQUIRED_CHECKS)


def test_v1_runner_and_public_workflow_remain_unchanged_in_role():
    root = Path(gate.ROOT)
    runner = (root / "backend/scripts/run_recovery_gate2.py").read_text()
    workflow = (root / ".github/workflows/recovery-gate2-public.yml").read_text()
    assert "--review" in runner and "run_gate" in runner
    assert "Recovery Gate 2 single public proof" in workflow
    assert "sol61/gate2-public-proof" in workflow
