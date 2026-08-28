from copy import deepcopy

from app.services.day42_publish_readiness import (
    DAY42_CANDIDATE_WORKFLOW_PATH,
    DAY42_REQUIRED_WORKFLOWS,
    EXPECTED_ADAPTER_SCOPE,
    build_day42_publish_readiness,
    expected_day42_publication_acknowledgment,
)


REVISION = "a" * 40
APK_SHA = "b" * 64
OTHER_SHA = "c" * 64
CANDIDATE_RUN_ID = 424242


def _inputs():
    audit = {
        "passed": True,
        "day42_entry_eligible": True,
        "candidate_revision": REVISION,
        "report_sha256": OTHER_SHA,
        "publication_authorized": False,
        "release_tag_authorized": False,
    }
    matrix = {
        "passed": True,
        "revision": REVISION,
        "current_head": REVISION,
        "workflows": {name: "success" for name in DAY42_REQUIRED_WORKFLOWS},
    }
    artifact = {
        "source_revision": REVISION,
        "apk_sha256": APK_SHA,
        "build_identity_sha256": OTHER_SHA,
        "signing_certificate_sha256": OTHER_SHA,
        "signing_mode": "development_signed",
        "workflow_run_id": CANDIDATE_RUN_ID,
        "workflow_path": DAY42_CANDIDATE_WORKFLOW_PATH,
        "workflow_conclusion": "success",
        "reproducible_build": True,
        "source_commit_file_present": True,
        "checksums_file_present": True,
        "build_info_present": True,
        "candidate_metadata_present": True,
        "publication_authorized": False,
    }
    adapters = {
        name: {
            "version": expected["version"],
            "maturity": expected["maturity"],
            "autonomous_submission_allowed": expected["autonomous"],
        }
        for name, expected in EXPECTED_ADAPTER_SCOPE.items()
    }
    maturity = {
        "candidate_revision": REVISION,
        "release_version": "v2.0.0",
        "truthful_scope_verified": True,
        "real_submission_default_enabled": False,
        "real_followup_default_enabled": False,
        "adapters": adapters,
    }
    repository = {
        "main_revision": REVISION,
        "release_tag_exists": False,
        "release_exists": False,
        "release_assets_exist": False,
    }
    docs = {
        "readme_updated": True,
        "changelog_updated": True,
        "release_notes_final": True,
        "known_boundaries_final": True,
        "operator_guide_final": True,
        "incident_runbook_final": True,
    }
    owner = {
        "approved": True,
        "approval_reference": "v2-final-publication",
        "release_version": "v2.0.0",
        "release_tag": "v2.0.0",
        "approved_for_commit": REVISION,
        "approved_apk_sha256": APK_SHA,
        "approved_candidate_run_id": CANDIDATE_RUN_ID,
        "acknowledgment": expected_day42_publication_acknowledgment(
            revision=REVISION,
            apk_sha256=APK_SHA,
        ),
    }
    return audit, matrix, artifact, maturity, repository, docs, owner


def _result(**overrides):
    audit, matrix, artifact, maturity, repository, docs, owner = _inputs()
    values = {
        "day41_audit": audit,
        "final_release_matrix": matrix,
        "candidate_artifact": artifact,
        "maturity_manifest": maturity,
        "repository_release_state": repository,
        "release_documents": docs,
        "owner_authorization": owner,
    }
    values.update(overrides)
    return build_day42_publish_readiness(**values)


def test_day42_clean_exact_artifact_is_eligible_but_not_published():
    result = _result()

    assert result["publication_eligible"] is True
    assert result["candidate_run_id"] == CANDIDATE_RUN_ID
    assert result["candidate_workflow_path"] == DAY42_CANDIDATE_WORKFLOW_PATH
    assert result["publication_executed"] is False
    assert result["release_tag_created"] is False
    assert result["github_release_created"] is False
    assert result["real_submission_enabled"] is False
    assert result["real_followup_send_enabled"] is False
    assert result["blockers"] == []
    assert len(result["report_sha256"]) == 64


def test_day42_requires_strict_day41_pass():
    audit, *_ = _inputs()
    audit["day42_entry_eligible"] = False

    result = _result(day41_audit=audit)

    assert result["publication_eligible"] is False
    assert "day41.day42_entry_eligible" in result["blockers"]


def test_day42_requires_final_exact_head_matrix():
    _, matrix, *_ = _inputs()
    matrix["current_head"] = "d" * 40

    result = _result(final_release_matrix=matrix)

    assert result["publication_eligible"] is False
    assert "final_release_matrix.final_matrix_exact_head" in result["blockers"]


def test_day42_requires_every_final_workflow():
    _, matrix, *_ = _inputs()
    matrix["workflows"]["Day 42 publish-readiness tooling gate"] = "failure"

    result = _result(final_release_matrix=matrix)

    assert result["publication_eligible"] is False
    assert "final_release_matrix.workflow:Day 42 publish-readiness tooling gate" in result["blockers"]


def test_day42_requires_exact_apk_and_build_provenance():
    _, _, artifact, *_ = _inputs()
    artifact["source_revision"] = "d" * 40
    artifact["checksums_file_present"] = False

    result = _result(candidate_artifact=artifact)

    assert result["publication_eligible"] is False
    assert "candidate_artifact.artifact_revision_exact" in result["blockers"]
    assert "candidate_artifact.checksums_file_present" in result["blockers"]


def test_day42_requires_truthful_explicit_signing_mode():
    _, _, artifact, *_ = _inputs()
    artifact["signing_mode"] = "development"

    result = _result(candidate_artifact=artifact)

    assert result["publication_eligible"] is False
    assert "candidate_artifact.signing_mode_truthful" in result["blockers"]


def test_day42_requires_successful_exact_candidate_workflow():
    _, _, artifact, *_ = _inputs()
    artifact["workflow_run_id"] = 0
    artifact["workflow_path"] = ".github/workflows/android-apk.yml"
    artifact["workflow_conclusion"] = "failure"

    result = _result(candidate_artifact=artifact)

    assert result["publication_eligible"] is False
    assert "candidate_artifact.candidate_run_id_valid" in result["blockers"]
    assert "candidate_artifact.candidate_workflow_exact" in result["blockers"]
    assert "candidate_artifact.candidate_workflow_succeeded" in result["blockers"]


def test_day42_rejects_candidate_that_pre_authorizes_publication():
    _, _, artifact, *_ = _inputs()
    artifact["publication_authorized"] = True

    result = _result(candidate_artifact=artifact)

    assert result["publication_eligible"] is False
    assert (
        "candidate_artifact.publication_not_pre_authorized_in_candidate"
        in result["blockers"]
    )


def test_day42_rejects_adapter_scope_drift():
    _, _, _, maturity, *_ = _inputs()
    maturity = deepcopy(maturity)
    maturity["adapters"]["greenhouse"]["maturity"] = "certified_autonomous"
    maturity["adapters"]["greenhouse"]["autonomous_submission_allowed"] = True

    result = _result(maturity_manifest=maturity)

    assert result["publication_eligible"] is False
    assert "maturity_manifest.adapter:greenhouse:maturity" in result["blockers"]
    assert "maturity_manifest.adapter:greenhouse:autonomous" in result["blockers"]


def test_day42_requires_fail_safe_submission_defaults():
    _, _, _, maturity, *_ = _inputs()
    maturity["real_submission_default_enabled"] = True

    result = _result(maturity_manifest=maturity)

    assert result["publication_eligible"] is False
    assert "maturity_manifest.submission_default_fail_safe" in result["blockers"]


def test_day42_refuses_existing_tag_or_release():
    _, _, _, _, repository, *_ = _inputs()
    repository["release_tag_exists"] = True
    repository["release_exists"] = True

    result = _result(repository_release_state=repository)

    assert result["publication_eligible"] is False
    assert "repository_release_state.release_tag_absent_before_publish" in result["blockers"]
    assert "repository_release_state.github_release_absent_before_publish" in result["blockers"]


def test_day42_requires_readme_and_changelog_updated_before_publish():
    *_, docs, _ = _inputs()
    docs["readme_updated"] = False
    docs["changelog_updated"] = False

    result = _result(release_documents=docs)

    assert result["publication_eligible"] is False
    assert "release_documents.readme_updated_for_release" in result["blockers"]
    assert "release_documents.changelog_updated_for_release" in result["blockers"]


def test_day42_owner_authorization_is_exact_commit_apk_and_run_bound():
    *_, owner = _inputs()
    owner["approved_for_commit"] = "d" * 40
    owner["approved_apk_sha256"] = "e" * 64
    owner["approved_candidate_run_id"] = CANDIDATE_RUN_ID + 1

    result = _result(owner_authorization=owner)

    assert result["publication_eligible"] is False
    assert "owner_authorization.owner_commit_exact" in result["blockers"]
    assert "owner_authorization.owner_apk_sha256_exact" in result["blockers"]
    assert "owner_authorization.owner_candidate_run_exact" in result["blockers"]


def test_day42_owner_acknowledgment_must_be_exact():
    *_, owner = _inputs()
    owner["acknowledgment"] += " EXTRA"

    result = _result(owner_authorization=owner)

    assert result["publication_eligible"] is False
    assert "owner_authorization.owner_acknowledgment_exact" in result["blockers"]


def test_day42_acknowledgment_binds_short_commit_and_apk_hash():
    assert expected_day42_publication_acknowledgment(
        revision=REVISION,
        apk_sha256=APK_SHA,
    ) == f"PUBLISH JOBTOMATIK V2.0.0 {REVISION[:12]} {APK_SHA[:12]}"


def test_day42_report_is_deterministic():
    first = _result()
    second = _result()

    assert first == second
    assert first["report_sha256"] == second["report_sha256"]
