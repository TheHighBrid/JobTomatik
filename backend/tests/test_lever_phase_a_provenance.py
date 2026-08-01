from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from app.services.ats_lever import LEVER_ADAPTER_VERSION
from app.services.lever_phase_a_operator import (
    build_phase_a_report,
    build_resumed_exercise,
    frozen_target_identity,
    load_locked_target,
    write_report,
)
from app.services.lever_phase_a_provenance import (
    ACTIONS_RUN_PREFIX,
    LeverPhaseAProvenanceError,
    finalize_interactive_candidate,
    require_retained_report_path,
    validate_external_provenance,
)
from app.services.lever_pilot_ingestion import load_phase_a_baseline


ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = ROOT / "backend" / "evidence" / "lever-phase-a-target-corpus"


def _qualifying_report(review_id: str) -> dict:
    target = load_locked_target(review_id, CORPUS_ROOT)
    url = str(target["canonical_application_url"])
    inspection = {
        "url": url,
        "mode": "inspect",
        "passed": True,
        "final_submit_clicked": False,
        "adapter": "lever",
        "adapter_version": LEVER_ADAPTER_VERSION,
        "dom": {
            "visible_control_count": 7,
            "required_control_count": 5,
        },
    }
    initial = {
        "success": False,
        "ready_to_submit": False,
        "requires_manual_review": True,
        "ats_adapter": "lever",
        "ats_adapter_version": LEVER_ADAPTER_VERSION,
        "fields_filled": 5,
        "steps_completed": 1,
        "log": [{"action": "ats_manual_challenge_ready"}],
        "review_items": [
            {
                "reason_code": "captcha_detected",
                "summary": "Human verification required.",
                "details": {"handoff_stage": "post_fill_pre_action"},
            }
        ],
        "validation_errors": [],
        "upload_evidence": [
            {"filename": "synthetic.pdf", "verification": "passed"}
        ],
        "step_evidence": [{"action": "ats_step_filled", "step": 1}],
        "control_evidence": [
            {"control_id": "name", "verification": "passed"},
            {"control_id": "email", "verification": "passed"},
        ],
    }
    resumed = {
        "success": True,
        "ready_to_submit": True,
        "requires_manual_review": False,
        "ats_adapter": "lever",
        "ats_adapter_version": LEVER_ADAPTER_VERSION,
        "fields_filled": 5,
        "steps_completed": 1,
        "log": [{"action": "ats_final_submit_ready", "submit_clicked": False}],
        "review_items": [],
        "validation_errors": [],
        "upload_evidence": [
            {"filename": "synthetic.pdf", "verification": "passed"}
        ],
        "step_evidence": [{"action": "ats_final_submit_ready", "step": 1}],
        "control_evidence": [
            {"control_id": "name", "verification": "passed"},
            {"control_id": "email", "verification": "passed"},
        ],
        "error": None,
    }
    exercise = build_resumed_exercise(
        url=url,
        initial_result=initial,
        resumed_result=resumed,
        certification_metadata={
            "synthetic_profile": True,
            "review_id": review_id,
            "frozen_target": frozen_target_identity(target),
            "supervised_target": {
                "platform": "lever",
                "adapter": "lever",
                "adapter_version": LEVER_ADAPTER_VERSION,
                "site": target["site"],
                "posting_id": target["posting_id"],
                "region": target["region"],
                "canonical_application_url": url,
                "official_title": target["role"],
            },
        },
        handoff_verification={
            "challenge_cleared": True,
            "verification_method": "captcha_response_state",
            "target_verification": {"verified": True},
        },
        submit_guard={
            "installed": True,
            "blocked_clicks": 0,
            "blocked_submits": 0,
        },
    )
    return build_phase_a_report(inspection, exercise)


def _verified_retention_stub(report: dict):
    def fetch_verified_retention_artifact(
        *,
        github_token: str,
        local_report_path: Path,
        evidence_root: Path,
        review_id: str,
        workflow_run_id: str,
        artifact_id: str,
        artifact_digest: str,
    ) -> dict:
        assert github_token == "test-token"
        artifact_path = require_retained_report_path(local_report_path, evidence_root)
        provenance = validate_external_provenance(
            workflow_run_id=workflow_run_id,
            artifact_id=artifact_id,
            artifact_digest=artifact_digest,
        )
        report_bytes = Path(local_report_path).read_bytes()
        assert json.loads(report_bytes) == report
        return {
            "report": report,
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "archive_bytes": b"externally-retained-test-archive",
            "archive_sha256": artifact_digest,
            "artifact_path": artifact_path,
            "manifest": {},
            "provenance": provenance,
        }

    return fetch_verified_retention_artifact


def test_external_provenance_requires_numeric_ids_and_sha256() -> None:
    valid = validate_external_provenance(
        workflow_run_id="123456789",
        artifact_id="987654321",
        artifact_digest="a" * 64,
    )
    assert valid["source_reference"] == ACTIONS_RUN_PREFIX + "123456789"

    for values in (
        {"workflow_run_id": "local", "artifact_id": "1", "artifact_digest": "a" * 64},
        {"workflow_run_id": "1", "artifact_id": "artifact", "artifact_digest": "a" * 64},
        {"workflow_run_id": "1", "artifact_id": "2", "artifact_digest": "sha256:bad"},
    ):
        with pytest.raises(LeverPhaseAProvenanceError):
            validate_external_provenance(**values)


def test_finalizer_emits_qualifying_candidate_and_source_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = tmp_path / "evidence"
    report_path = (
        evidence_root
        / "lever-phase-a-artifacts"
        / "D8-001"
        / "lever-phase-a-interactive-report.json"
    )
    candidate_path = evidence_root / "lever-phase-a-candidate-D8-001.csv"
    source_path = evidence_root / "lever-phase-a-source-D8-001.csv"
    report = _qualifying_report("D8-001")
    write_report(report_path, report)
    monkeypatch.setattr(
        "app.services.lever_phase_a_provenance.fetch_verified_retention_artifact",
        _verified_retention_stub(report),
    )

    finalized = finalize_interactive_candidate(
        report_path=report_path,
        review_id="D8-001",
        corpus_root=CORPUS_ROOT,
        evidence_root=evidence_root,
        candidate_path=candidate_path,
        source_receipt_path=source_path,
        operator="TheHighBrid",
        workflow_run_id="123456789",
        artifact_id="987654321",
        artifact_digest="b" * 64,
        github_token="test-token",
    )

    loaded = load_phase_a_baseline(candidate_path)
    assert len(loaded) == 1
    assert loaded[0]["qualifies_for_dry_run_matrix"] is True
    assert loaded[0]["source_reference"] == ACTIONS_RUN_PREFIX + "123456789"
    assert loaded[0]["artifact_path"] == (
        "lever-phase-a-artifacts/D8-001/lever-phase-a-interactive-report.json"
    )
    assert finalized["candidate"]["run_id"] == (
        "github-actions-123456789-interactive-d8-001"
    )

    with source_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "workflow_run_id": "123456789",
            "artifact_id": "987654321",
            "artifact_digest": "b" * 64,
            "retained_record_count": "1",
        }
    ]


def test_finalizer_rejects_report_outside_retained_artifact_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = tmp_path / "evidence"
    report_path = tmp_path / "mutable-local-report.json"
    report = _qualifying_report("D8-001")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        "app.services.lever_phase_a_provenance.fetch_verified_retention_artifact",
        _verified_retention_stub(report),
    )

    with pytest.raises(LeverPhaseAProvenanceError, match="lever-phase-a-artifacts"):
        finalize_interactive_candidate(
            report_path=report_path,
            review_id="D8-001",
            corpus_root=CORPUS_ROOT,
            evidence_root=evidence_root,
            candidate_path=evidence_root / "candidate.csv",
            source_receipt_path=evidence_root / "source.csv",
            operator="TheHighBrid",
            workflow_run_id="123456789",
            artifact_id="987654321",
            artifact_digest="c" * 64,
            github_token="test-token",
        )


def test_interactive_runner_never_self_certifies_local_report() -> None:
    source = (
        ROOT / "backend" / "scripts" / "run_lever_phase_a_handoff.py"
    ).read_text(encoding="utf-8")

    assert "local-sha256:" not in source
    assert "build_phase_a_candidate" not in source
    assert "export_phase_a_candidate" not in source
    assert "lever-phase-a-candidate.csv" not in source
    assert "No candidate CSV was emitted" in source