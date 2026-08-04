from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from app.services.ats_lever import LEVER_ADAPTER_VERSION
from app.services.lever_phase_a_operator import load_locked_target
from app.services.lever_phase_a_provenance import LeverPhaseAProvenanceError
from scripts.finalize_lever_phase_a_ready import (
    MANIFEST_NAME,
    _normalized_manifest_report_path,
    finalize,
    validate_ready_report,
    verify_artifact_bundle,
)


REVIEW_ID = "D8-003"
URL = "https://jobs.lever.co/waveapps/e5bb8724-6ee8-49d2-ae4e-1e83c4d61637/apply"
RUN_ID = "30800000001"
ARTIFACT_ID = "9000000001"


def _report() -> dict:
    return {
        "certification": "lever_supervised_live_dry_run",
        "final_submit_clicked": False,
        "passed": True,
        "reports": [
            {
                "url": URL,
                "mode": "inspect",
                "passed": True,
                "final_submit_clicked": False,
                "posting_available": True,
                "posting_http_status": 200,
                "adapter": "lever",
                "adapter_version": LEVER_ADAPTER_VERSION,
                "posting_metadata": {
                    "title": "Group Product Manager",
                    "posting_metadata_certified": True,
                    "apply_url_matches_posting": True,
                },
            },
            {
                "url": URL,
                "mode": "exercise",
                "passed": True,
                "certification_outcome": "ready_to_submit",
                "ready_to_submit": True,
                "requires_manual_review": False,
                "fields_filled": 16,
                "review_items": [],
                "validation_errors": [],
                "upload_evidence": [
                    {
                        "upload_type": "resume",
                        "verification": "passed",
                    }
                ],
                "control_evidence_schema_version": "1.0",
                "control_evidence": [
                    {
                        "action": "control_verified",
                        "control_engine_version": "2.1.0",
                        "control_id": "jt-text-1",
                        "control_type": "email",
                        "descriptor": "Email",
                        "canonical_key": "profile.email",
                        "policy_id": None,
                        "selected": [],
                        "options_fingerprint": "a" * 16,
                        "verification": "passed",
                        "pass": 1,
                        "source": "profile",
                        "value_redacted": True,
                    },
                    {
                        "action": "control_verified",
                        "control_engine_version": "2.1.0",
                        "control_id": "jt-text-2",
                        "control_type": "textarea",
                        "descriptor": "Why this role?",
                        "canonical_key": "why_this_role",
                        "policy_id": 7,
                        "selected": [],
                        "options_fingerprint": "b" * 16,
                        "verification": "passed",
                        "pass": 1,
                        "source": "answer_policy",
                        "value_redacted": True,
                    },
                ],
                "control_evidence_count": 2,
                "policy_evidence_count": 1,
                "final_submit_clicked": False,
                "adapter": "lever",
                "adapter_version": LEVER_ADAPTER_VERSION,
                "certification_metadata": {
                    "site": "waveapps",
                    "posting_id": "e5bb8724-6ee8-49d2-ae4e-1e83c4d61637",
                    "region": "global",
                    "synthetic_profile": True,
                },
                "error": None,
            },
        ],
    }


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    evidence = tmp_path / "evidence"
    report = (
        evidence
        / "lever-phase-a-artifacts"
        / REVIEW_ID
        / "lever-phase-a-report.json"
    )
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps(_report(), indent=2) + "\n", encoding="utf-8")
    return evidence, report


def _artifact(report: Path, evidence: Path) -> tuple[dict, bytes, str]:
    relative = report.relative_to(evidence).as_posix()
    manifest = {
        "repository": "TheHighBrid/JobTomatik",
        "workflow_run_id": RUN_ID,
        "retained_record_count": 1,
        "report": {
            "review_id": REVIEW_ID,
            "path": relative,
            "sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
        },
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(relative, report.read_bytes())
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2) + "\n")
    archive_bytes = stream.getvalue()
    digest = hashlib.sha256(archive_bytes).hexdigest()
    metadata = {
        "id": int(ARTIFACT_ID),
        "name": f"lever-phase-a-ready-{REVIEW_ID}-deadbeef",
        "expired": False,
        "digest": "sha256:" + digest,
        "workflow_run": {"id": int(RUN_ID)},
    }
    return metadata, archive_bytes, digest


def test_ready_report_matches_locked_target() -> None:
    target = load_locked_target(
        REVIEW_ID,
        Path("evidence/lever-phase-a-target-corpus"),
    )
    result = validate_ready_report(_report(), target)
    assert result["review_id"] == REVIEW_ID
    assert result["exercise"]["ready_to_submit"] is True


def test_count_only_control_evidence_is_rejected() -> None:
    target = load_locked_target(
        REVIEW_ID,
        Path("evidence/lever-phase-a-target-corpus"),
    )
    report = _report()
    exercise = report["reports"][1]
    exercise.pop("control_evidence")
    with pytest.raises(LeverPhaseAProvenanceError, match="per-control"):
        validate_ready_report(report, target)


def test_policy_text_evidence_requires_resolved_policy_id() -> None:
    target = load_locked_target(
        REVIEW_ID,
        Path("evidence/lever-phase-a-target-corpus"),
    )
    report = _report()
    report["reports"][1]["control_evidence"][1]["policy_id"] = None
    with pytest.raises(LeverPhaseAProvenanceError, match="policy ID"):
        validate_ready_report(report, target)


def test_text_evidence_rejects_raw_value_fields() -> None:
    target = load_locked_target(
        REVIEW_ID,
        Path("evidence/lever-phase-a-target-corpus"),
    )
    report = _report()
    report["reports"][1]["control_evidence"][0]["value"] = "secret"
    with pytest.raises(LeverPhaseAProvenanceError, match="raw-value"):
        validate_ready_report(report, target)


def test_duplicate_control_evidence_identity_is_rejected() -> None:
    target = load_locked_target(
        REVIEW_ID,
        Path("evidence/lever-phase-a-target-corpus"),
    )
    report = _report()
    duplicate = dict(report["reports"][1]["control_evidence"][0])
    report["reports"][1]["control_evidence"].append(duplicate)
    report["reports"][1]["control_evidence_count"] = 3
    with pytest.raises(LeverPhaseAProvenanceError, match="duplicate identity"):
        validate_ready_report(report, target)


def test_manual_challenge_report_is_rejected() -> None:
    target = load_locked_target(
        REVIEW_ID,
        Path("evidence/lever-phase-a-target-corpus"),
    )
    report = _report()
    exercise = report["reports"][1]
    exercise["certification_outcome"] = "manual_challenge_handoff"
    exercise["ready_to_submit"] = False
    exercise["requires_manual_review"] = True
    with pytest.raises(LeverPhaseAProvenanceError, match="ready_to_submit"):
        validate_ready_report(report, target)


def test_artifact_bundle_binds_byte_identical_report(tmp_path: Path) -> None:
    evidence, report = _paths(tmp_path)
    metadata, archive_bytes, digest = _artifact(report, evidence)
    verified = verify_artifact_bundle(
        metadata=metadata,
        archive_bytes=archive_bytes,
        report_path=report,
        evidence_root=evidence,
        review_id=REVIEW_ID,
        workflow_run_id=RUN_ID,
        artifact_id=ARTIFACT_ID,
        artifact_digest=digest,
    )
    assert verified["report_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert verified["artifact_path"].endswith("lever-phase-a-report.json")


def test_finalize_writes_candidate_source_and_archive(tmp_path: Path) -> None:
    evidence, report = _paths(tmp_path)
    metadata, archive_bytes, digest = _artifact(report, evidence)
    metadata_path = tmp_path / "artifact-metadata.json"
    zip_path = tmp_path / "artifact.zip"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    zip_path.write_bytes(archive_bytes)
    candidate = evidence / f"lever-phase-a-candidate-{REVIEW_ID}.csv"
    source = evidence / f"lever-phase-a-source-{REVIEW_ID}.csv"

    result = finalize(
        argparse.Namespace(
            review_id=REVIEW_ID,
            report=str(report),
            artifact_metadata=str(metadata_path),
            artifact_zip=str(zip_path),
            workflow_run_id=RUN_ID,
            artifact_id=ARTIFACT_ID,
            artifact_digest=digest,
            operator="TheHighBrid",
            run_id=None,
            corpus_root="evidence/lever-phase-a-target-corpus",
            evidence_root=str(evidence),
            candidate_output=str(candidate),
            source_output=str(source),
        )
    )

    with candidate.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with source.open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle))

    assert len(rows) == 1
    assert rows[0]["pre_submit_state"] == "ready_to_submit"
    assert rows[0]["final_status"] == "dry_run_passed"
    assert rows[0]["source_reference"].endswith("/actions/runs/" + RUN_ID)
    assert rows[0]["policies_used"] == "1"
    assert sources == [
        {
            "workflow_run_id": RUN_ID,
            "artifact_id": ARTIFACT_ID,
            "artifact_digest": digest,
            "retained_record_count": "1",
        }
    ]
    assert Path(result["durable_archive"]["path"]).is_file()

def test_manifest_report_path_normalizes_repository_roots() -> None:
    expected = "lever-phase-a-artifacts/D8-003/lever-phase-a-report.json"
    assert _normalized_manifest_report_path(expected) == expected
    assert _normalized_manifest_report_path("evidence/" + expected) == expected
    assert _normalized_manifest_report_path("backend/evidence/" + expected) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/evidence/lever-phase-a-artifacts/D8-003/lever-phase-a-report.json",
        "evidence/../secrets.json",
    ],
)
def test_manifest_report_path_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(LeverPhaseAProvenanceError):
        _normalized_manifest_report_path(value)
