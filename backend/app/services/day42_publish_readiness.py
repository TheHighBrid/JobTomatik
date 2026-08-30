"""Read-only Day 42 exact-commit publication readiness evaluator.

A passing result means an owner may invoke the separate hardened release workflow for
one exact commit and one exact prebuilt APK candidate. This module cannot create a tag,
GitHub release, or artifact, and cannot enable application submission or follow-up
sending.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


DAY42_PUBLISH_READINESS_VERSION = "day42-publish-readiness-v1"
DAY42_RELEASE_VERSION = "v2.0.0"
DAY42_RELEASE_TAG = "v2.0.0"
DAY42_CANDIDATE_WORKFLOW_PATH = ".github/workflows/build-v2-release-candidate.yml"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

DAY42_REQUIRED_WORKFLOWS = (
    "Backend tests",
    "Post-merge stabilization",
    "Reproducible verification",
    "CodeQL security analysis",
    "Current-head end-to-end acceptance",
    "Android runtime dispatch acceptance",
    "Runtime revision attestation",
    "Android static frontend artifact",
    "Android APK",
    "Certification and scale",
    "Submission evidence review certification",
    "Full-stack shadow campaigns",
    "Day 39 live-window tooling gate",
    "Day 40 second-wave tooling gate",
    "Day 41 release-audit tooling gate",
    "Day 42 publish-readiness tooling gate",
)

EXPECTED_ADAPTER_SCOPE = {
    "lever": {"version": "1.1.0", "maturity": "certified_autonomous", "autonomous": True},
    "greenhouse": {"version": "1.1.1", "maturity": "dry_run", "autonomous": False},
    "ashby": {"version": "1.1.0", "maturity": "dry_run", "autonomous": False},
    "smartrecruiters": {"version": "1.1.0", "maturity": "detect_only", "autonomous": False},
    "workday": {"version": "1.1.0", "maturity": "detect_only", "autonomous": False},
}


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


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def expected_day42_publication_acknowledgment(*, revision: str, apk_sha256: str) -> str:
    commit = _sha40(revision)
    apk = _sha256(apk_sha256)
    if not commit or not apk:
        return ""
    return f"PUBLISH JOBTOMATIK V2.0.0 {commit[:12]} {apk[:12]}"


def build_day42_publish_readiness(
    *,
    day41_audit: Any,
    final_release_matrix: Any,
    candidate_artifact: Any,
    maturity_manifest: Any,
    repository_release_state: Any,
    release_documents: Any,
    owner_authorization: Any,
) -> dict[str, Any]:
    """Evaluate whether the separate exact-artifact v2.0.0 publisher may be invoked."""

    audit = _mapping(day41_audit)
    matrix = _mapping(final_release_matrix)
    artifact = _mapping(candidate_artifact)
    maturity = _mapping(maturity_manifest)
    repository = _mapping(repository_release_state)
    docs = _mapping(release_documents)
    owner = _mapping(owner_authorization)

    audit_revision = _sha40(audit.get("candidate_revision"))
    matrix_revision = _sha40(matrix.get("revision"))
    current_head = _sha40(matrix.get("current_head"))
    main_revision = _sha40(repository.get("main_revision"))
    artifact_revision = _sha40(artifact.get("source_revision"))
    manifest_revision = _sha40(maturity.get("candidate_revision"))
    owner_revision = _sha40(owner.get("approved_for_commit"))
    apk_sha = _sha256(artifact.get("apk_sha256"))
    audit_sha = _sha256(audit.get("report_sha256"))
    candidate_run_id = _positive_int(artifact.get("workflow_run_id"))
    owner_candidate_run_id = _positive_int(owner.get("approved_candidate_run_id"))
    candidate_workflow_path = str(artifact.get("workflow_path") or "").strip()
    expected_ack = expected_day42_publication_acknowledgment(
        revision=matrix_revision,
        apk_sha256=apk_sha,
    )

    day41_checks = {
        "day41_passed": audit.get("passed") is True,
        "day42_entry_eligible": audit.get("day42_entry_eligible") is True,
        "day41_report_hash_valid": bool(audit_sha),
        "day41_revision_valid": bool(audit_revision),
        "day41_did_not_publish": audit.get("publication_authorized") is False,
        "day41_did_not_authorize_tag": audit.get("release_tag_authorized") is False,
    }

    workflows = _mapping(matrix.get("workflows"))
    matrix_checks = {
        "final_matrix_passed": matrix.get("passed") is True,
        "final_revision_valid": bool(matrix_revision),
        "final_matrix_exact_head": bool(matrix_revision) and current_head == matrix_revision,
        "final_revision_matches_day41": bool(audit_revision) and matrix_revision == audit_revision,
    }
    for workflow_name in DAY42_REQUIRED_WORKFLOWS:
        matrix_checks[f"workflow:{workflow_name}"] = (
            str(workflows.get(workflow_name) or "").strip().lower() == "success"
        )

    signing_mode = str(artifact.get("signing_mode") or "").strip().lower()
    artifact_checks = {
        "artifact_revision_exact": bool(matrix_revision) and artifact_revision == matrix_revision,
        "apk_sha256_valid": bool(apk_sha),
        "build_identity_sha256_valid": bool(_sha256(artifact.get("build_identity_sha256"))),
        "signing_certificate_sha256_valid": bool(
            _sha256(artifact.get("signing_certificate_sha256"))
        ),
        "signing_mode_truthful": signing_mode in {"release_signed", "development_signed"},
        "candidate_run_id_valid": candidate_run_id > 0,
        "candidate_workflow_exact": candidate_workflow_path == DAY42_CANDIDATE_WORKFLOW_PATH,
        "candidate_workflow_succeeded": artifact.get("workflow_conclusion") == "success",
        "candidate_reproducible": artifact.get("reproducible_build") is True,
        "source_commit_file_present": artifact.get("source_commit_file_present") is True,
        "checksums_file_present": artifact.get("checksums_file_present") is True,
        "build_info_present": artifact.get("build_info_present") is True,
        "candidate_metadata_present": artifact.get("candidate_metadata_present") is True,
        "publication_not_pre_authorized_in_candidate": artifact.get("publication_authorized") is False,
    }

    adapters = _mapping(maturity.get("adapters"))
    maturity_checks = {
        "manifest_revision_exact": bool(matrix_revision) and manifest_revision == matrix_revision,
        "manifest_release_version_exact": str(maturity.get("release_version") or "")
        == DAY42_RELEASE_VERSION,
        "manifest_truthful_scope_asserted": maturity.get("truthful_scope_verified") is True,
        "submission_default_fail_safe": maturity.get("real_submission_default_enabled") is False,
        "followup_default_fail_safe": maturity.get("real_followup_default_enabled") is False,
    }
    for name, expected in EXPECTED_ADAPTER_SCOPE.items():
        observed = _mapping(adapters.get(name))
        maturity_checks[f"adapter:{name}:version"] = (
            str(observed.get("version") or "") == expected["version"]
        )
        maturity_checks[f"adapter:{name}:maturity"] = (
            str(observed.get("maturity") or "") == expected["maturity"]
        )
        maturity_checks[f"adapter:{name}:autonomous"] = (
            observed.get("autonomous_submission_allowed") is expected["autonomous"]
        )

    repository_checks = {
        "main_revision_exact": bool(matrix_revision) and main_revision == matrix_revision,
        "release_tag_absent_before_publish": repository.get("release_tag_exists") is False,
        "github_release_absent_before_publish": repository.get("release_exists") is False,
        "release_assets_not_preexisting": repository.get("release_assets_exist") is False,
    }

    document_checks = {
        "readme_updated_for_release": docs.get("readme_updated") is True,
        "changelog_updated_for_release": docs.get("changelog_updated") is True,
        "release_notes_final": docs.get("release_notes_final") is True,
        "known_boundaries_final": docs.get("known_boundaries_final") is True,
        "operator_guide_final": docs.get("operator_guide_final") is True,
        "incident_runbook_final": docs.get("incident_runbook_final") is True,
    }

    owner_checks = {
        "owner_approved": owner.get("approved") is True,
        "owner_reference_present": bool(str(owner.get("approval_reference") or "").strip()),
        "owner_release_version_exact": str(owner.get("release_version") or "")
        == DAY42_RELEASE_VERSION,
        "owner_release_tag_exact": str(owner.get("release_tag") or "") == DAY42_RELEASE_TAG,
        "owner_commit_exact": bool(matrix_revision) and owner_revision == matrix_revision,
        "owner_apk_sha256_exact": bool(apk_sha)
        and _sha256(owner.get("approved_apk_sha256")) == apk_sha,
        "owner_candidate_run_exact": candidate_run_id > 0
        and owner_candidate_run_id == candidate_run_id,
        "owner_acknowledgment_exact": bool(expected_ack)
        and str(owner.get("acknowledgment") or "") == expected_ack,
    }

    sections = {
        "day41": day41_checks,
        "final_release_matrix": matrix_checks,
        "candidate_artifact": artifact_checks,
        "maturity_manifest": maturity_checks,
        "repository_release_state": repository_checks,
        "release_documents": document_checks,
        "owner_authorization": owner_checks,
    }
    blockers = [
        f"{section}.{name}"
        for section, checks in sections.items()
        for name, passed in checks.items()
        if not passed
    ]
    eligible = not blockers

    result: dict[str, Any] = {
        "version": DAY42_PUBLISH_READINESS_VERSION,
        "release_version": DAY42_RELEASE_VERSION,
        "release_tag": DAY42_RELEASE_TAG,
        "candidate_revision": matrix_revision or None,
        "candidate_run_id": candidate_run_id or None,
        "candidate_workflow_path": candidate_workflow_path or None,
        "apk_sha256": apk_sha or None,
        "day41_report_sha256": audit_sha or None,
        "expected_acknowledgment": expected_ack or None,
        "checks": sections,
        "blockers": blockers,
        "publication_eligible": eligible,
        "publication_executed": False,
        "release_tag_created": False,
        "github_release_created": False,
        "real_submission_enabled": False,
        "real_followup_send_enabled": False,
        "next_action": (
            "invoke_separate_exact_artifact_v2_publisher"
            if eligible
            else "satisfy_day42_publish_blockers"
        ),
        "invariants": {
            "readiness_evaluator_never_publishes": True,
            "publisher_must_recheck_main_before_publication": True,
            "publisher_must_refuse_existing_v2_tag": True,
            "release_target_commitish_must_be_exact_sha": True,
            "publisher_must_not_rebuild_approved_apk": True,
            "development_signed_artifact_must_be_labeled_truthfully": True,
            "owner_authorization_is_exact_commit_apk_and_candidate_run_bound": True,
        },
    }
    result["report_sha256"] = _canonical_hash(result)
    return result


__all__ = [
    "DAY42_CANDIDATE_WORKFLOW_PATH",
    "DAY42_PUBLISH_READINESS_VERSION",
    "DAY42_RELEASE_TAG",
    "DAY42_RELEASE_VERSION",
    "DAY42_REQUIRED_WORKFLOWS",
    "EXPECTED_ADAPTER_SCOPE",
    "build_day42_publish_readiness",
    "expected_day42_publication_acknowledgment",
]
