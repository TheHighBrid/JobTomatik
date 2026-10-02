from copy import deepcopy

from app.services.day41_release_audit import (
    DAY41_REQUIRED_WORKFLOWS,
    build_day41_release_candidate_audit,
)


REVISION = "a" * 40
SHA256 = "b" * 64


def _inputs():
    day40 = {
        "passed": True,
        "day41_entry_eligible": True,
        "release_candidate_revision": REVISION,
        "report_sha256": SHA256,
    }
    matrix = {
        "passed": True,
        "revision": REVISION,
        "current_head": REVISION,
        "workflows": {name: "success" for name in DAY41_REQUIRED_WORKFLOWS},
    }
    runtime = {
        "current_revision": REVISION,
        "live_window_authorized": False,
        "allow_real_application_submit": False,
        "allow_real_followup_send": False,
        "autopilot_enabled": False,
        "global_kill_switch": False,
    }
    audits = {
        "data_integrity_passed": True,
        "security_passed": True,
        "privacy_passed": True,
        "dependencies_verified": True,
        "pip_check_passed": True,
        "npm_production_audit_passed": True,
        "migration_smoke_passed": True,
        "android_candidate_verified": True,
        "release_provenance_verified": True,
        "secret_scan_passed": True,
        "test_secrets_rotated": True,
        "no_production_secret_in_source": True,
        "no_production_secret_in_artifacts": True,
    }
    drills = {
        "rollback_passed": True,
        "rollback_report_sha256": SHA256,
        "kill_switch_passed": True,
        "kill_switch_report_sha256": SHA256,
        "database_restore_passed": True,
        "database_restore_report_sha256": SHA256,
        "previous_release_compatibility_passed": True,
        "previous_release_compatibility_report_sha256": SHA256,
    }
    artifact = {
        "source_revision": REVISION,
        "apk_sha256": SHA256,
        "build_identity_sha256": SHA256,
        "signing_certificate_sha256": SHA256,
        "signing_mode": "development_signed",
        "reproducible_build": True,
        "publication_authorized": False,
        "release_tag_created": False,
    }
    docs = {
        "release_notes_final": True,
        "known_boundaries_final": True,
        "operator_guide_final": True,
        "incident_runbook_final": True,
        "changelog_ready": True,
        "readme_release_scope_ready": True,
    }
    checklist = {
        "generated": True,
        "revision": REVISION,
        "checklist_sha256": SHA256,
        "review_reference": "day41-release-audit-review",
        "release_version": "v2.0.0",
    }
    return day40, matrix, runtime, audits, drills, artifact, docs, checklist


def _audit(**overrides):
    day40, matrix, runtime, audits, drills, artifact, docs, checklist = _inputs()
    values = {
        "day40_certification": day40,
        "release_matrix": matrix,
        "runtime_state": runtime,
        "audit_results": audits,
        "recovery_drills": drills,
        "candidate_artifact": artifact,
        "release_documents": docs,
        "checklist": checklist,
    }
    values.update(overrides)
    return build_day41_release_candidate_audit(**values)


def test_day41_clean_release_candidate_becomes_day42_eligible_without_publishing():
    result = _audit()

    assert result["passed"] is True
    assert result["day42_entry_eligible"] is True
    assert result["publication_authorized"] is False
    assert result["release_tag_authorized"] is False
    assert result["real_submission_enabled"] is False
    assert result["real_followup_send_enabled"] is False
    assert result["blockers"] == []
    assert len(result["report_sha256"]) == 64


def test_day41_requires_day40_strict_certification():
    day40, *_ = _inputs()
    day40["day41_entry_eligible"] = False

    result = _audit(day40_certification=day40)

    assert result["passed"] is False
    assert "day40.day41_entry_eligible" in result["blockers"]


def test_day41_requires_exact_head_matrix_and_same_day40_revision():
    _, matrix, *_ = _inputs()
    matrix["current_head"] = "c" * 40

    result = _audit(release_matrix=matrix)

    assert result["passed"] is False
    assert "release_matrix.release_matrix_exact_head" in result["blockers"]


def test_day41_requires_every_named_release_workflow():
    _, matrix, *_ = _inputs()
    matrix["workflows"]["Android APK"] = "failure"

    result = _audit(release_matrix=matrix)

    assert result["passed"] is False
    assert "release_matrix.workflow:Android APK" in result["blockers"]


def test_day41_requires_live_mode_and_autopilot_disabled():
    _, _, runtime, *_ = _inputs()
    runtime["allow_real_application_submit"] = True
    runtime["live_window_authorized"] = True
    runtime["autopilot_enabled"] = True

    result = _audit(runtime_state=runtime)

    assert result["passed"] is False
    assert "runtime.live_window_disabled" in result["blockers"]
    assert "runtime.real_submission_disabled" in result["blockers"]
    assert "runtime.autopilot_disabled_for_release_audit" in result["blockers"]


def test_day41_requires_dependency_privacy_and_secret_audits():
    _, _, _, audits, *_ = _inputs()
    audits["privacy_passed"] = False
    audits["dependencies_verified"] = False
    audits["no_production_secret_in_artifacts"] = False

    result = _audit(audit_results=audits)

    assert result["passed"] is False
    assert "audits.privacy_audit_passed" in result["blockers"]
    assert "audits.dependency_verification_passed" in result["blockers"]
    assert "audits.no_production_secret_in_artifacts" in result["blockers"]


def test_day41_requires_all_recovery_drills_and_hashes():
    _, _, _, _, drills, *_ = _inputs()
    drills["database_restore_passed"] = False
    drills["rollback_report_sha256"] = "not-a-hash"

    result = _audit(recovery_drills=drills)

    assert result["passed"] is False
    assert "recovery_drills.database_restore_drill_passed" in result["blockers"]
    assert "recovery_drills.rollback_report_hash_valid" in result["blockers"]


def test_day41_accepts_explicit_development_signed_candidate_but_not_unknown_signing():
    _, _, _, _, _, artifact, *_ = _inputs()
    assert _audit(candidate_artifact=artifact)["passed"] is True

    artifact = deepcopy(artifact)
    artifact["signing_mode"] = "mystery"
    result = _audit(candidate_artifact=artifact)

    assert result["passed"] is False
    assert "candidate_artifact.signing_mode_explicit" in result["blockers"]


def test_day41_rejects_candidate_that_already_published_or_tagged():
    _, _, _, _, _, artifact, *_ = _inputs()
    artifact["publication_authorized"] = True
    artifact["release_tag_created"] = True

    result = _audit(candidate_artifact=artifact)

    assert result["passed"] is False
    assert "candidate_artifact.publication_not_authorized_during_audit" in result["blockers"]
    assert "candidate_artifact.release_tag_not_created_during_audit" in result["blockers"]


def test_day41_requires_final_operator_release_documents():
    _, _, _, _, _, _, docs, _ = _inputs()
    docs["incident_runbook_final"] = False

    result = _audit(release_documents=docs)

    assert result["passed"] is False
    assert "release_documents.incident_runbook_final" in result["blockers"]


def test_day41_checklist_is_exact_commit_and_hash_bound():
    *_, checklist = _inputs()
    checklist["revision"] = "d" * 40
    checklist["checklist_sha256"] = "bad"

    result = _audit(checklist=checklist)

    assert result["passed"] is False
    assert "checklist.checklist_revision_exact" in result["blockers"]
    assert "checklist.checklist_sha256_valid" in result["blockers"]


def test_day41_report_is_deterministic():
    first = _audit()
    second = _audit()

    assert first == second
    assert first["report_sha256"] == second["report_sha256"]
