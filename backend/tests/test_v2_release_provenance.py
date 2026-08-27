from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ANDROID_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "android-apk.yml"
CANDIDATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-v2-release-candidate.yml"
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish-v1-command.yml"


def test_android_apk_workflow_builds_exact_source_without_publishing_from_pr():
    workflow = ANDROID_WORKFLOW.read_text(encoding="utf-8")

    assert "SOURCE_REVISION: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$SOURCE_REVISION"' in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "softprops/action-gh-release" not in workflow
    assert "publish-v2-release" not in workflow
    assert "Publication authorized: false" in workflow
    assert "apksigner\" verify --print-certs" in workflow
    assert "release/SOURCE-COMMIT.txt" in workflow
    assert "JobTomatik-v2.00-development.apk" in workflow


def test_exact_commit_candidate_builder_is_owner_only_and_never_publishes():
    workflow = CANDIDATE_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "source_commit:" in workflow
    assert "day41_audit_reference:" in workflow
    assert "github.actor == 'TheHighBrid'" in workflow
    assert '[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]' in workflow
    assert 'test "$(git rev-parse origin/main)" = "$SOURCE_COMMIT"' in workflow
    assert 'git checkout --detach "$SOURCE_COMMIT"' in workflow
    assert "Publication authorized: false" in workflow
    assert "CANDIDATE-METADATA.json" in workflow
    assert "workflow_run_id" in workflow
    assert "softprops/action-gh-release" not in workflow
    assert "contents: read" in workflow


def test_v2_publisher_requires_owner_exact_main_candidate_and_day42_hash():
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "source_commit:" in workflow
    assert "candidate_run_id:" in workflow
    assert "approved_apk_sha256:" in workflow
    assert "day42_readiness_sha256:" in workflow
    assert "authorization_reference:" in workflow
    assert "acknowledgment:" in workflow
    assert "github.actor == 'TheHighBrid'" in workflow
    assert "issue_comment:" not in workflow
    assert "chatgpt-codex-connector[bot]" not in workflow
    assert '[[ "$EXPECTED_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]' in workflow
    assert '[[ "$APPROVED_APK_SHA256" =~ ^[0-9a-f]{64}$ ]]' in workflow
    assert '[[ "$DAY42_READINESS_SHA256" =~ ^[0-9a-f]{64}$ ]]' in workflow
    assert 'test "$EXPECTED_SOURCE_COMMIT" = "$MAIN_HEAD"' in workflow
    assert "PUBLISH JOBTOMATIK V2.0.0" in workflow
    assert "actions: read" in workflow


def test_publisher_verifies_candidate_workflow_identity_and_reuses_exact_bytes():
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    assert "github.rest.actions.getWorkflowRun" in workflow
    assert "run.path !== '.github/workflows/build-v2-release-candidate.yml'" in workflow
    assert "run.conclusion !== 'success'" in workflow
    assert "run.head_sha !== process.env.EXPECTED_SOURCE_COMMIT" in workflow
    assert "actions/download-artifact@v8" in workflow
    assert "run-id: ${{ needs.authorize-exact-release.outputs.candidate_run_id }}" in workflow
    assert "JobTomatik-v2.00-candidate-${{ needs.authorize-exact-release.outputs.source_commit }}" in workflow
    assert 'test "$ACTUAL_APK_SHA256" = "$APPROVED_APK_SHA256"' in workflow
    assert "metadata.get('workflow_run_id')" in workflow
    assert "assembleRelease" not in workflow
    assert "assembleDebug" not in workflow
    assert "npm run android:prepare" not in workflow


def test_v2_release_is_immutable_and_bound_to_artifact_source_commit():
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    assert 'refs/tags/$RELEASE_TAG' in workflow
    assert "Release tag $RELEASE_TAG already exists; refusing mutable republish." in workflow
    assert "Release tag $RELEASE_TAG appeared before publication; refusing overwrite." in workflow
    assert "target_commitish: ${{ needs.authorize-exact-release.outputs.source_commit }}" in workflow
    assert "target_commitish: main" not in workflow
    assert "overwrite_files: false" in workflow
    assert "release/SOURCE-COMMIT.txt" in workflow
    assert "release/APK-SIGNING.txt" in workflow
    assert "release/CANDIDATE-METADATA.json" in workflow
    assert "release/DAY42-READINESS-SHA256.txt" in workflow
    assert "JobTomatik-v2.00.sha256" in workflow
    assert "apksigner\" verify --print-certs" in workflow


def test_release_notes_do_not_treat_publication_as_autonomy_promotion():
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    assert "Publication does not itself promote adapter maturity." in workflow
    assert "certified-adapter maturity" in workflow
    assert "fail-safe submission controls" in workflow
