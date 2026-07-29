import csv
import json
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services.application_state import record_submission_evidence
from app.services import lever_pilot_ingestion
from app.services.lever_pilot_ingestion import load_phase_a_baseline
from app.services.lever_pilot_ledger_boundary import (
    LeverPilotIngestionError,
    ingest_confirmed_lever_application,
    read_lever_pilot_readiness,
    validate_phase_b_runtime_ledger,
)
from app.services.platform_submission_evidence import review_platform_submission_evidence


SITE = "ledger-lever"
POSTING_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CANONICAL_URL = f"https://jobs.lever.co/{SITE}/{POSTING_ID}/apply"
IDENTITY = {
    "platform": "lever",
    "adapter": "lever",
    "adapter_version": "1.1.0",
    "site": SITE,
    "posting_id": POSTING_ID,
    "region": "global",
    "canonical_application_url": CANONICAL_URL,
    "posting_metadata_hash": "9" * 64,
    "identity_hash": "8" * 64,
    "verified": True,
    "blockers": [],
}


def _confirmed_fixture(db_session):
    user = User(
        email="lever-ledger@example.test",
        hashed_password="not-used",
        full_name="Lever Ledger Reviewer",
        resume_path="/tmp/lever-ledger.pdf",
        profile_data={},
    )
    job = Job(
        external_id=POSTING_ID,
        title="Compliance Analyst",
        company="Lever Ledger Employer",
        url=CANONICAL_URL,
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": CANONICAL_URL,
            "supervised_target_metadata": IDENTITY,
        },
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applied,
        automation_state=ApplicationAutomationState.submitted.value,
        submission_idempotency_key="application:lever:ledger:1",
        submission_attempt_count=1,
        last_submission_attempt_at=datetime.utcnow(),
        cover_letter="Prepared cover letter",
    )
    db_session.add(application)
    db_session.flush()
    approval = SubmissionApproval(
        application_id=application.id,
        user_id=user.id,
        platform="lever",
        status=SubmissionApprovalStatus.consumed.value,
        employer=job.company,
        role=job.title,
        application_url=CANONICAL_URL,
        submission_idempotency_key=application.submission_idempotency_key,
        profile_snapshot_hash="1" * 64,
        resume_hash="2" * 64,
        cover_letter_hash="3" * 64,
        answer_payload_hash="4" * 64,
        combined_payload_hash="5" * 64,
        approved_at=datetime.utcnow() - timedelta(minutes=2),
        expires_at=datetime.utcnow() + timedelta(minutes=20),
        consumed_at=datetime.utcnow() - timedelta(minutes=1),
        approval_metadata={
            "policy_count": 2,
            "adapter_version": "1.1.0",
            "target_identity_hash": IDENTITY["identity_hash"],
            "target_identity": IDENTITY,
        },
    )
    db_session.add(approval)
    db_session.flush()
    evidence = record_submission_evidence(
        db_session,
        application,
        "confirmation_page",
        is_sufficient=True,
        final_url=CANONICAL_URL,
        confirmation_text="Thank you for applying",
        screenshot_path="evidence/lever-ledger-confirmation.png",
        metadata={
            "source": "lever_confirmation",
            "adapter": "lever",
            "adapter_version": "1.1.0",
        },
    )
    db_session.flush()
    review_platform_submission_evidence(
        db_session,
        application,
        user,
        job,
        evidence,
        decision="accepted",
        confirm_employer=job.company,
        confirm_role=job.title,
        confirm_evidence_type=evidence.evidence_type,
        confirm_evidence_matches_application=True,
        review_acknowledgement="REVIEWED",
        notes="Concrete Lever confirmation independently reviewed",
    )
    db_session.commit()
    db_session.refresh(application)
    return user, job, application


def _paths(tmp_path):
    return {
        "baseline_path": tmp_path / "missing-phase-a.csv",
        "ledger_path": tmp_path / "lever-pilot-ledger.jsonl",
        "summary_json_path": tmp_path / "lever-readiness.json",
        "summary_markdown_path": tmp_path / "lever-readiness.md",
    }


def _phase_a_runtime_record(index: int) -> dict:
    site = f"runtime-dry-{index}"
    posting_id = f"00000000-0000-0000-0000-{index:012d}"
    url = f"https://jobs.lever.co/{site}/{posting_id}/apply"
    return {
        "schema_version": "1.0",
        "run_id": f"lv-runtime-dry-{index}",
        "mode": "dry_run",
        "platform": "lever",
        "completed_at": datetime.utcnow().isoformat(),
        "employer": f"Runtime Dry Employer {index}",
        "role": "Analyst",
        "site": site,
        "posting_id": posting_id,
        "region": "global" if index % 2 else "eu",
        "board_token": site,
        "job_id": posting_id,
        "application_url": url,
        "canonical_application_url": url,
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "operator": "github-actions:TheHighBrid",
        "source_reference": f"actions-run:runtime:{index}",
        "artifact_sha256": f"{index % 10}" * 64,
        "approval_reference": None,
        "controls_discovered": 3,
        "controls_filled": 3,
        "controls_skipped": 0,
        "controls_blocked": 0,
        "policies_used": 2,
        "uploads_verified": 1,
        "validation_errors": [],
        "handoff_reason": None,
        "handoff_boundary": None,
        "pre_submit_state": "ready_to_submit",
        "final_url": url,
        "final_submit_clicked": False,
        "confirmation_evidence_type": None,
        "confirmation_evidence_reference": None,
        "final_status": "dry_run_passed",
        "duplicate_guard_verified": None,
        "duplicate_submission_detected": False,
        "reviewed_by": None,
        "review_reference": None,
        "qualifies_for_dry_run_matrix": True,
        "synthetic_profile": True,
        "error": None,
        "notes": None,
    }


def test_missing_phase_a_baseline_counts_as_zero_not_readiness(tmp_path):
    result = read_lever_pilot_readiness(
        baseline_path=tmp_path / "missing.csv",
        ledger_path=tmp_path / "empty.jsonl",
    )

    assert result["baseline_record_count"] == 0
    assert result["runtime_record_count"] == 0
    assert result["ledger_record_count"] == 0
    assert result["summary"]["canonical_maturity"] == "dry_run"
    assert result["summary"]["qualifying_dry_run_count"] == 0
    assert result["summary"]["promotion_ready"] is False


def test_runtime_ledger_rejects_dry_run_records_instead_of_counting_them(tmp_path):
    ledger = tmp_path / "lever-pilot-ledger.jsonl"
    planted = [_phase_a_runtime_record(index) for index in range(1, 31)]
    ledger.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in planted),
        encoding="utf-8",
    )

    with pytest.raises(LeverPilotIngestionError, match="Phase B records only"):
        validate_phase_b_runtime_ledger(ledger)
    with pytest.raises(LeverPilotIngestionError, match="Phase B records only"):
        read_lever_pilot_readiness(
            baseline_path=tmp_path / "missing.csv",
            ledger_path=ledger,
        )


def test_confirmed_lever_record_is_atomically_ingested_and_idempotent(db_session, tmp_path):
    user, job, application = _confirmed_fixture(db_session)
    paths = _paths(tmp_path)

    first = ingest_confirmed_lever_application(
        db_session, application, user, job, **paths
    )
    db_session.commit()
    second = ingest_confirmed_lever_application(
        db_session, application, user, job, **paths
    )
    db_session.commit()

    assert first["added"] is True
    assert second["added"] is False
    assert first["record"]["platform"] == "lever"
    assert first["record"]["mode"] == "supervised_real_submission"
    assert first["record"]["approval_reference"].startswith("lvsup-")
    assert first["record"]["site"] == SITE
    assert first["record"]["posting_id"] == POSTING_ID
    assert first["record"]["region"] == "global"
    assert first["record"]["evidence_payload_hash"] == first["record"]["combined_payload_hash"]
    assert second["ledger_sha256"] == first["ledger_sha256"]
    assert first["runtime_record_count"] == 1
    assert first["ledger_record_count"] == 1
    assert first["summary"]["supervised_confirmed_count"] == 1
    assert first["summary"]["qualifying_dry_run_count"] == 0
    assert first["summary"]["canonical_maturity"] == "dry_run"
    assert first["summary"]["promotion_ready"] is False

    lines = paths["ledger_path"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    persisted = json.loads(lines[0])
    assert persisted["run_id"] == first["record"]["run_id"]
    assert persisted["mode"] == "supervised_real_submission"
    assert paths["summary_json_path"].is_file()
    assert paths["summary_markdown_path"].is_file()
    assert not list(tmp_path.glob(".*.tmp"))

    events = (
        db_session.query(ApplicationEvent)
        .filter(ApplicationEvent.event_type == "lever_supervised_pilot_record_ingested")
        .all()
    )
    assert len(events) == 1
    assert events[0].payload["site"] == SITE
    assert events[0].payload["posting_id"] == POSTING_ID


def test_target_identity_replay_conflict_preserves_ledger(db_session, tmp_path):
    user, job, application = _confirmed_fixture(db_session)
    paths = _paths(tmp_path)
    first = ingest_confirmed_lever_application(
        db_session, application, user, job, **paths
    )
    db_session.commit()
    original = paths["ledger_path"].read_bytes()

    job.company = "Mutated Employer"
    db_session.commit()
    with pytest.raises(LeverPilotIngestionError, match="conflicting Lever evidence"):
        ingest_confirmed_lever_application(
            db_session, application, user, job, **paths
        )

    assert paths["ledger_path"].read_bytes() == original
    assert first["ledger_record_count"] == 1


def test_phase_a_rows_require_immutable_artifact_digest_and_exact_target(tmp_path):
    path = tmp_path / "phase-a.csv"
    fields = [
        "run_id",
        "completed_at",
        "employer",
        "role",
        "site",
        "posting_id",
        "region",
        "application_url",
        "adapter_version",
        "operator",
        "source_reference",
        "artifact_sha256",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "run_id": "lv-phase-a-1",
            "completed_at": datetime.utcnow().isoformat(),
            "employer": "Phase A Employer",
            "role": "Analyst",
            "site": "phase-a-site",
            "posting_id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
            "region": "eu",
            "application_url": "https://jobs.eu.lever.co/phase-a-site/bbbbbbbb-cccc-dddd-eeee-ffffffffffff/apply",
            "adapter_version": "1.1.0",
            "operator": "github-actions:TheHighBrid",
            "source_reference": "actions-run:123:artifact:lever-phase-a-1",
            "artifact_sha256": "a" * 64,
        })

    records = load_phase_a_baseline(path)
    assert len(records) == 1
    assert records[0]["final_submit_clicked"] is False
    assert records[0]["artifact_sha256"] == "a" * 64
    assert records[0]["region"] == "eu"

    text = path.read_text(encoding="utf-8").replace("a" * 64, "missing")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(LeverPilotIngestionError, match="artifact_sha256"):
        load_phase_a_baseline(path)

def test_hardening_and_summary_persistence_use_the_ingestion_lock_snapshot(
    db_session, tmp_path, monkeypatch
):
    user, job, application = _confirmed_fixture(db_session)
    paths = _paths(tmp_path)
    original_lock = lever_pilot_ingestion._ledger_lock
    original_harden = lever_pilot_ingestion.harden_lever_readiness
    state = {"inside_lock": False, "hardened": False}

    @contextmanager
    def observed_lock(path, *, exclusive):
        with original_lock(path, exclusive=exclusive):
            state["inside_lock"] = True
            try:
                yield
            finally:
                state["inside_lock"] = False

    def observed_harden(readiness, *, baseline_path, ledger_path):
        assert state["inside_lock"] is True
        state["hardened"] = True
        return original_harden(
            readiness, baseline_path=baseline_path, ledger_path=ledger_path
        )

    monkeypatch.setattr(lever_pilot_ingestion, "_ledger_lock", observed_lock)
    monkeypatch.setattr(lever_pilot_ingestion, "harden_lever_readiness", observed_harden)
    result = ingest_confirmed_lever_application(
        db_session, application, user, job, **paths
    )
    assert state["hardened"] is True
    persisted = json.loads(paths["summary_json_path"].read_text(encoding="utf-8"))
    expected = {
        key: value for key, value in result.items() if key not in {"added", "record"}
    }
    assert persisted == expected
    assert persisted["runtime_record_count"] == result["runtime_record_count"]
    assert persisted["runtime_ledger_sha256"] == result["runtime_ledger_sha256"]
    assert persisted["ledger_sha256"] == result["ledger_sha256"]
