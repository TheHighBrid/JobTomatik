import json

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.job import Job
from app.models.user import User
from app.services import supervised_pilot_dossier as dossier_service


POSTING_ID = "12345678-1234-1234-1234-123456789abc"
LEVER_URL = f"https://jobs.lever.co/dossier/{POSTING_ID}/apply"


def _fixture(db_session, tmp_path):
    resume = tmp_path / "lever-phase-b-dossier.pdf"
    resume.write_bytes(b"%PDF-1.4\nlever-phase-b-dossier\n")
    user = User(
        email="lever-phase-b-dossier@example.test",
        hashed_password="not-used",
        full_name="Lever Phase B Dossier",
        phone="6135550188",
        resume_path=str(resume),
        profile_data={"secret_profile_value": "never-copy-this"},
    )
    job = Job(
        external_id="lever-phase-b-dossier-job",
        company="Dossier Employer",
        title="Dossier Role",
        url=LEVER_URL,
        raw_data={"application_method": "external_url", "selected_apply_url": LEVER_URL},
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        submission_idempotency_key="application:lever-dossier:123",
        submission_attempt_count=0,
        cover_letter="Private Lever cover letter body",
    )
    db_session.add(application)
    db_session.flush()
    return user, job, application


def _preflight(application_id):
    return {
        "ready": False,
        "blockers": [
            "global_live_submit_disabled",
            "lever_supervised_pilot_disabled",
        ],
        "application_id": application_id,
        "platform": "lever",
        "platform_display_name": "Lever",
        "adapter_version": "1.1.0",
        "employer": "Dossier Employer",
        "role": "Dossier Role",
        "application_url": LEVER_URL,
        "original_application_url": LEVER_URL,
        "automation_state": "ready_to_apply",
        "unresolved_manual_review_count": 0,
        "global_live_submit_enabled": False,
        "platform_pilot_enabled": False,
        "submission_idempotency_key": "application:lever-dossier:123",
        "profile_snapshot_hash": "1" * 64,
        "resume_hash": "2" * 64,
        "cover_letter_hash": "3" * 64,
        "answer_payload_hash": "4" * 64,
        "combined_payload_hash": "5" * 64,
        "policy_count": 4,
        "cover_letter_present": True,
        "resume_filename": "lever-phase-b-dossier.pdf",
        "target_identity": {
            "site": "dossier",
            "posting_id": POSTING_ID,
            "region": "global",
            "canonical_application_url": LEVER_URL,
            "posting_metadata_hash": "6" * 64,
        },
        "target_identity_hash": "7" * 64,
        "target_identity_verified": True,
    }


def _readiness():
    return {
        "lever": {
            "summary": {
                "platform": "lever",
                "canonical_maturity": "dry_run",
                "qualifying_dry_run_count": 30,
                "distinct_site_count": 30,
                "regions_covered": ["eu", "global"],
                "supervised_confirmed_count": 4,
                "gates": {
                    "thirty_qualifying_dry_runs": True,
                    "thirty_distinct_lever_sites": True,
                    "global_and_eu_hosts_covered": True,
                    "all_phase_a_records_have_successful_matching_inspection": True,
                    "ten_supervised_confirmed_submissions": False,
                    "zero_false_submitted_records": True,
                    "zero_duplicate_submissions": True,
                    "all_uncertain_outcomes_remain_uncertain": True,
                    "all_success_evidence_independently_reviewed": True,
                    "all_evidence_hashes_match_consumed_approvals": True,
                },
            }
        }
    }


def test_lever_dossier_is_read_only_exact_target_and_sanitized(
    db_session,
    tmp_path,
    monkeypatch,
):
    user, job, application = _fixture(db_session, tmp_path)
    db_session.commit()
    monkeypatch.setattr(
        dossier_service,
        "build_supervised_preflight",
        lambda *args, **kwargs: _preflight(application.id),
    )

    dossier = dossier_service.build_supervised_pilot_dossier(
        db_session,
        application,
        user,
        job,
        readiness=_readiness(),
    )

    assert dossier["scope"] == "lever_supervised_phase_b_candidate"
    assert dossier["read_only"] is True
    assert dossier["target"] == {
        "employer": "Dossier Employer",
        "role": "Dossier Role",
        "application_url": LEVER_URL,
        "application_host": "jobs.lever.co",
        "platform": "lever",
        "adapter_version": "1.1.0",
        "site": "dossier",
        "posting_id": POSTING_ID,
        "region": "global",
        "canonical_application_url": LEVER_URL,
        "posting_metadata_hash": "6" * 64,
        "target_identity_hash": "7" * 64,
        "target_identity_verified": True,
    }
    assert dossier["preflight"]["technical_ready"] is True
    assert dossier["preflight"]["structural_blockers"] == []
    assert dossier["preflight"]["execution_ready"] is False
    assert set(dossier["preflight"]["execution_blockers"]) == {
        "global_live_submit_disabled",
        "lever_supervised_pilot_disabled",
    }
    assert dossier["kill_switches"]["platform_flag_name"] == "LEVER_SUPERVISED_PILOT_ENABLED"
    assert dossier["kill_switches"]["platform_flag_enabled"] is False
    assert dossier["kill_switches"]["direct_submit_action_in_dossier"] is False
    assert dossier["pilot_progress"]["phase_a_distinct_sites"] == 30
    assert dossier["pilot_progress"]["phase_a_regions_covered"] == ["eu", "global"]
    assert dossier["pilot_progress"]["phase_a_complete"] is True
    assert dossier["pilot_progress"]["phase_b_remaining"] == 6
    assert dossier["pilot_progress"]["phase_b_complete"] is False
    assert dossier["download_filename"].startswith("lever-phase-b-dossier-")
    assert len(dossier["dossier_sha256"]) == 64

    serialized = json.dumps(dossier, sort_keys=True)
    assert "6135550188" not in serialized
    assert "never-copy-this" not in serialized
    assert "Private Lever cover letter body" not in serialized


def test_lever_dossier_digest_changes_on_exact_target_identity_change(
    db_session,
    tmp_path,
    monkeypatch,
):
    user, job, application = _fixture(db_session, tmp_path)
    db_session.commit()
    current = _preflight(application.id)
    monkeypatch.setattr(
        dossier_service,
        "build_supervised_preflight",
        lambda *args, **kwargs: dict(current),
    )

    before = dossier_service.build_supervised_pilot_dossier(
        db_session,
        application,
        user,
        job,
        readiness=_readiness(),
    )
    current["target_identity_hash"] = "8" * 64
    current["target_identity"] = {
        **current["target_identity"],
        "posting_metadata_hash": "9" * 64,
    }
    after = dossier_service.build_supervised_pilot_dossier(
        db_session,
        application,
        user,
        job,
        readiness=_readiness(),
    )

    assert before["dossier_sha256"] != after["dossier_sha256"]
    assert before["target"]["target_identity_hash"] != after["target"]["target_identity_hash"]
