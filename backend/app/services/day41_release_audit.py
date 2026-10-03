"""Strict Day 41 release-candidate audit evaluator.

The evaluator is intentionally read-only. It consumes retained Day 40 certification,
exact-head release matrix results, live-mode shutdown state, audit/drill evidence, and
candidate artifact identity. A pass only makes the exact commit eligible for Day 42;
it does not publish a release or re-enable live submission.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


DAY41_RELEASE_AUDIT_VERSION = "day41-release-candidate-audit-v1"
DAY41_RELEASE_VERSION = "v2.0.0"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

DAY41_REQUIRED_WORKFLOWS = (
    "Backend tests",
    "Post-merge stabilization",
    "Reproducible verification",
    "CodeQL security analysis",
    "Current-head end-to-end acceptance",
    "Android runtime dispatch acceptance",
    "Android static frontend artifact",
    "Android APK",
    "Certification and scale",
    "Submission evidence review certification",
    "Full-stack shadow campaigns",
    "Day 39 live-window tooling gate",
    "Day 40 second-wave tooling gate",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sha40(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _SHA40.fullmatch(text) else ""


def _sha256(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.split(":", 1)[1]
    return text if _SHA256.fullmatch(text) else ""


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_day41_release_candidate_audit(
    *,
    day40_certification: Any,
    release_matrix: Any,
    runtime_state: Any,
    audit_results: Any,
    recovery_drills: Any,
    candidate_artifact: Any,
    release_documents: Any,
    checklist: Any,
) -> dict[str, Any]:
    """Return whether one exact release commit may enter the Day 42 publish gate."""

    day40 = _mapping(day40_certification)
    matrix = _mapping(release_matrix)
    runtime = _mapping(runtime_state)
    audits = _mapping(audit_results)
    drills = _mapping(recovery_drills)
    artifact = _mapping(candidate_artifact)
    docs = _mapping(release_documents)
    signed = _mapping(checklist)

    day40_revision = _sha40(day40.get("release_candidate_revision"))
    matrix_revision = _sha40(matrix.get("revision"))
    current_head = _sha40(matrix.get("current_head"))
    runtime_revision = _sha40(runtime.get("current_revision"))
    artifact_revision = _sha40(artifact.get("source_revision"))
    checklist_revision = _sha40(signed.get("revision"))
    day40_report_sha = _sha256(day40.get("report_sha256"))

    predecessor_checks = {
        "day40_passed": day40.get("passed") is True,
        "day41_entry_eligible": day40.get("day41_entry_eligible") is True,
        "day40_revision_valid": bool(day40_revision),
        "day40_report_hash_valid": bool(day40_report_sha),
    }

    workflows = _mapping(matrix.get("workflows"))
    release_matrix_checks = {
        "release_matrix_passed": matrix.get("passed") is True,
        "release_revision_valid": bool(matrix_revision),
        "release_matrix_exact_head": bool(matrix_revision)
        and current_head == matrix_revision,
        "release_revision_matches_day40": bool(day40_revision)
        and matrix_revision == day40_revision,
    }
    for workflow_name in DAY41_REQUIRED_WORKFLOWS:
        release_matrix_checks[f"workflow:{workflow_name}"] = (
            str(workflows.get(workflow_name) or "").strip().lower() == "success"
        )

    runtime_checks = {
        "runtime_revision_exact": bool(matrix_revision)
        and runtime_revision == matrix_revision,
        "live_window_disabled": runtime.get("live_window_authorized") is False,
        "real_submission_disabled": runtime.get("allow_real_application_submit") is False,
        "real_followup_send_disabled": runtime.get("allow_real_followup_send") is False,
        "autopilot_disabled_for_release_audit": runtime.get("autopilot_enabled") is False,
        "global_kill_switch_state_known": runtime.get("global_kill_switch") in {True, False},
    }

    audit_checks = {
        "data_integrity_audit_passed": audits.get("data_integrity_passed") is True,
        "security_audit_passed": audits.get("security_passed") is True,
        "privacy_audit_passed": audits.get("privacy_passed") is True,
        "dependency_verification_passed": audits.get("dependencies_verified") is True,
        "pip_check_passed": audits.get("pip_check_passed") is True,
        "production_npm_audit_passed": audits.get("npm_production_audit_passed") is True,
        "migration_smoke_passed": audits.get("migration_smoke_passed") is True,
        "android_candidate_verified": audits.get("android_candidate_verified") is True,
        "release_provenance_verified": audits.get("release_provenance_verified") is True,
        "secret_scan_passed": audits.get("secret_scan_passed") is True,
        "test_secrets_rotated": audits.get("test_secrets_rotated") is True,
        "no_production_secret_in_source": audits.get("no_production_secret_in_source") is True,
        "no_production_secret_in_artifacts": audits.get("no_production_secret_in_artifacts")
        is True,
    }

    drill_checks = {
        "rollback_drill_passed": drills.get("rollback_passed") is True,
        "rollback_report_hash_valid": bool(_sha256(drills.get("rollback_report_sha256"))),
        "kill_switch_drill_passed": drills.get("kill_switch_passed") is True,
        "kill_switch_report_hash_valid": bool(_sha256(drills.get("kill_switch_report_sha256"))),
        "database_restore_drill_passed": drills.get("database_restore_passed") is True,
        "database_restore_report_hash_valid": bool(
            _sha256(drills.get("database_restore_report_sha256"))
        ),
        "previous_release_compatibility_passed": drills.get(
            "previous_release_compatibility_passed"
        )
        is True,
        "previous_release_compatibility_report_hash_valid": bool(
            _sha256(drills.get("previous_release_compatibility_report_sha256"))
        ),
    }

    signing_mode = str(artifact.get("signing_mode") or "").strip().lower()
    artifact_checks = {
        "artifact_source_revision_exact": bool(matrix_revision)
        and artifact_revision == matrix_revision,
        "apk_sha256_valid": bool(_sha256(artifact.get("apk_sha256"))),
        "build_identity_sha256_valid": bool(_sha256(artifact.get("build_identity_sha256"))),
        "signing_certificate_sha256_valid": bool(
            _sha256(artifact.get("signing_certificate_sha256"))
        ),
        "signing_mode_explicit": signing_mode in {"release_signed", "development_signed"},
        "reproducible_candidate_build": artifact.get("reproducible_build") is True,
        "publication_not_authorized_during_audit": artifact.get("publication_authorized")
        is False,
        "release_tag_not_created_during_audit": artifact.get("release_tag_created") is False,
    }

    document_checks = {
        "release_notes_final": docs.get("release_notes_final") is True,
        "known_boundaries_final": docs.get("known_boundaries_final") is True,
        "operator_guide_final": docs.get("operator_guide_final") is True,
        "incident_runbook_final": docs.get("incident_runbook_final") is True,
        "changelog_ready": docs.get("changelog_ready") is True,
        "readme_release_scope_ready": docs.get("readme_release_scope_ready") is True,
    }

    checklist_checks = {
        "checklist_generated": signed.get("generated") is True,
        "checklist_revision_exact": bool(matrix_revision)
        and checklist_revision == matrix_revision,
        "checklist_sha256_valid": bool(_sha256(signed.get("checklist_sha256"))),
        "checklist_review_reference_present": bool(
            str(signed.get("review_reference") or "").strip()
        ),
        "checklist_release_version_exact": str(signed.get("release_version") or "")
        == DAY41_RELEASE_VERSION,
    }

    sections = {
        "day40": predecessor_checks,
        "release_matrix": release_matrix_checks,
        "runtime": runtime_checks,
        "audits": audit_checks,
        "recovery_drills": drill_checks,
        "candidate_artifact": artifact_checks,
        "release_documents": document_checks,
        "checklist": checklist_checks,
    }
    blockers = [
        f"{section}.{name}"
        for section, checks in sections.items()
        for name, passed in checks.items()
        if not passed
    ]
    passed = not blockers

    result: dict[str, Any] = {
        "version": DAY41_RELEASE_AUDIT_VERSION,
        "release_version": DAY41_RELEASE_VERSION,
        "candidate_revision": matrix_revision or None,
        "day40_report_sha256": day40_report_sha or None,
        "checks": sections,
        "blockers": blockers,
        "passed": passed,
        "day42_entry_eligible": passed,
        "publication_authorized": False,
        "release_tag_authorized": False,
        "real_submission_enabled": False,
        "real_followup_send_enabled": False,
        "invariants": {
            "live_mode_disabled_during_release_audit": True,
            "day41_does_not_publish_release": True,
            "day42_must_recheck_exact_release_commit": True,
            "development_signed_artifact_must_be_labeled_truthfully": True,
            "release_publication_requires_separate_owner_action": True,
        },
        "next_action": (
            "enter_day42_exact_commit_publish_gate"
            if passed
            else "satisfy_day41_release_audit_blockers"
        ),
    }
    result["report_sha256"] = _canonical_hash(result)
    return result


__all__ = [
    "DAY41_RELEASE_AUDIT_VERSION",
    "DAY41_RELEASE_VERSION",
    "DAY41_REQUIRED_WORKFLOWS",
    "build_day41_release_candidate_audit",
]
