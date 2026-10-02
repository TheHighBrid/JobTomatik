from __future__ import annotations

from pathlib import Path
from subprocess import run


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts/jobtomatik_promotion_lane.sh"
STATE_PREPARER = BACKEND_ROOT / "scripts/prepare_lever_promotion_lane_state.py"
CONFIG = BACKEND_ROOT / "app/config.py"
BROWSER_HANDOFF = BACKEND_ROOT / "app/services/browser_handoff.py"
BROWSER_RUNTIME_BASE = BACKEND_ROOT / "app/services/browser_runtime_base.py"
GITIGNORE = BACKEND_ROOT.parent / ".gitignore"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _function(source: str, name: str, next_name: str) -> str:
    start = source.index(f"{name}() {{")
    end = source.index(f"{next_name}() {{", start)
    return source[start:end]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _require_contains(haystack: str, needle: str) -> None:
    _require(needle in haystack, f"Expected to find {needle!r}")


def _require_absent(haystack: str, needle: str) -> None:
    _require(needle not in haystack, f"Did not expect to find {needle!r}")


def _require_before(haystack: str, first: str, second: str) -> None:
    _require(
        haystack.index(first) < haystack.index(second),
        f"Expected {first!r} before {second!r}",
    )


def test_promotion_lane_shell_is_syntax_valid_and_pins_source_revision_once():
    run(
        ["bash", "-n", "scripts/jobtomatik_promotion_lane.sh"],
        cwd=BACKEND_ROOT,
        check=True,
    )
    source = _source()

    _require_contains(source, 'EXPECTED_FROZEN_REVISION="${JOBTOMATIK_FROZEN_REVISION:-}"')
    _require_contains(source, "resolve_source_revision")
    _require_contains(source, 'git -C "$repo" rev-parse HEAD')
    _require_contains(source, 'SOURCE_REVISION_PIN_MODE="captured_at_invocation"')
    _require_absent(source, "198b197dfcece6fbf9f3edfc5a92511fd951b484")
    _require_contains(source, 'FROZEN_REPO="${JOBTOMATIK_FROZEN_PROOT_REPO:-/root/JobTomatik}"')
    _require_contains(source, 'PROMOTION_REPO="${JOBTOMATIK_PROMOTION_PROOT_REPO:-/root/JobTomatik-promotion}"')
    _require_contains(source, "git -C \"$source_repo\" worktree add --detach")
    _require_contains(source, 'ln -s "$source_repo/backend/.venv"')
    _require_contains(source, "verify_python_environment_requirements.py")
    _require_before(
        source,
        "verify_python_environment_requirements.py",
        "prepare_lever_promotion_lane_state.py prepare",
    )
    _require_contains(source, 'source_requirements="$(git -C "$source_repo" rev-parse')
    _require_contains(source, 'target_requirements="$(git -C "$source_repo" rev-parse')
    _require_contains(source, "cat-file -e")
    _require_contains(source, "prepare_lever_promotion_lane_state.py prepare")
    _require_contains(source, "prepare_lever_promotion_lane_state.py verify")
    _require(STATE_PREPARER.is_file(), "Promotion state preparer must exist")


def test_promotion_lane_has_no_embedded_database_mutation_logic_or_submit_arm():
    source = _source()

    _require_absent(source, "source.backup(target)")
    _require_absent(source, "sqlite3.connect")
    _require_absent(source, "ALLOW_REAL_APPLICATION_SUBMIT=true")
    _require_absent(source, "LEVER_SUPERVISED_PILOT_ENABLED=true")
    _require_absent(source, "AUTOPILOT_ENABLED=true")
    _require_absent(source, "promotion_pilot arm")
    _require_absent(source, 'PILOT_COMMAND" arm')


def test_promotion_lane_isolates_runtime_browser_broker_and_transient_control_state():
    source = _source()

    _require_contains(source, "$HOME/.jobtomatik-promotion-runtime")
    _require_contains(source, "$HOME/.jobtomatik-promotion-chromium")
    _require_contains(source, "redis://localhost:${PROMOTION_REDIS_PORT}/${PROMOTION_REDIS_DB}")
    _require_contains(source, "JOBTOMATIK_ANDROID_REDIS_URL=\"$PROMOTION_REDIS_URL\"")
    _require_contains(source, "JOBTOMATIK_ANDROID_REDIS_URL=\"$FROZEN_REDIS_URL\"")
    _require_contains(source, "start_promotion_redis")
    _require_contains(source, "stop_promotion_redis")
    _require_contains(source, "FLUSHDB")
    _require_contains(source, "promotion-redis.rdb")
    _require_contains(source, "JOBTOMATIK_ANDROID_BROWSER_PROFILE=\"$PROMOTION_BROWSER_PROFILE\"")
    _require_contains(source, "JOBTOMATIK_REQUIRE_ISOLATED_BROWSER_PROFILE=1")
    _require_contains(source, "JOBTOMATIK_ANDROID_RUNTIME_DIR=\"$PROMOTION_RUNTIME_DIR\"")
    _require_contains(source, "archive_shared_control_dir")
    _require_contains(source, "pilot-control-archives")


def test_existing_lane_must_match_freshly_fetched_current_main():
    source = _source()
    prepare = _function(source, "prepare_lane", "contain_promotion_stack")

    _require_contains(prepare, 'if [[ "$existing_target" != "$target_revision" ]]')
    _require_contains(prepare, "Existing promotion lane is not current main")
    _require_contains(prepare, "Refusing implicit upgrade")


def test_start_proves_frozen_rollback_before_stopping_frozen_lane_and_requires_acceptance():
    source = _source()
    start = _function(source, "start_lane", "stop_lane")

    _require_before(start, "verify_installed_native_contracts", "prepare_lane")
    _require_before(start, "verify_frozen_return_artifact", "promotion_stack browser-preflight")
    _require_before(start, "promotion_stack browser-preflight", "frozen_stack stop")
    _require_contains(start, "frozen lane remains untouched")
    _require_before(start, "frozen_stack stop", "start_promotion_redis")
    _require_before(start, "start_promotion_redis", "promotion_stack start")
    _require_contains(start, "promotion_stack acceptance")
    _require_contains(start, "promotion_pilot status")
    _require_contains(start, "lever-pilot-runtime.active")
    _require_contains(start, "lever-pilot-runtime.pending")
    _require_contains(start, "JOBTOMATIK_PROMOTION_LANE_READY_FAIL_SAFE")


def test_every_post_stop_failure_path_restores_only_after_verified_promotion_containment():
    source = _source()
    containment = _function(source, "contain_promotion_stack", "restore_frozen_after_failure")
    recovery = _function(source, "restore_frozen_after_failure", "start_lane")
    start = _function(source, "start_lane", "stop_lane")

    _require_contains(containment, "if ! promotion_stack stop")
    _require_contains(containment, "if ! stop_promotion_redis")
    _require_contains(containment, "frozen lane remains blocked")
    _require_contains(recovery, 'contain_promotion_stack "$label" || return 1')
    _require_contains(recovery, "frozen_stack start || return 1")
    _require_absent(recovery, "|| true")
    _require_contains(start, "failed-promotion-start")
    _require_contains(start, "failed-promotion-acceptance")
    _require_contains(start, "unexpected-promotion-pilot-marker")
    _require_contains(start, "failed-promotion-pilot-status")
    _require(start.count("restore_frozen_after_failure") >= 4, "Expected at least four recovery paths")


def test_return_frozen_fails_closed_before_starting_certification_lane():
    source = _source()
    restore = _function(source, "return_frozen", "status_lane")

    _require_before(restore, "verify_installed_native_contracts", "contain_promotion_stack")
    _require_before(restore, "contain_promotion_stack", "verify_frozen_return_artifact")
    _require_before(restore, "verify_frozen_return_artifact", "frozen_stack start")
    _require_contains(restore, "Refusing frozen-lane startup because promotion containment is unverified")
    _require_contains(restore, "frozen_stack acceptance")
    _require_absent(restore, "promotion_stack stop || true")
    _require_absent(restore, "git switch")
    _require_absent(restore, "git pull")


def test_installed_native_launchers_are_attested_and_pinned_into_nested_wrappers():
    source = _source()
    attestation = _function(source, "verify_installed_native_contracts", "prepare_lane")

    _require_contains(attestation, "expected_contract_digest")
    _require_contains(attestation, 'sha256sum "$installed_path"')
    _require_contains(attestation, "Installed native launcher drift detected")
    _require_contains(source, "JOBTOMATIK_BROWSER_COMMAND=\"$BROWSER_COMMAND\"")
    _require_contains(source, "JOBTOMATIK_PILOT_CONTROLLER_COMMAND=\"$PILOT_CONTROLLER_COMMAND\"")
    _require_contains(source, "JOBTOMATIK_PILOT_CONTROLLER_MANAGER=\"$PILOT_CONTROLLER_MANAGER_COMMAND\"")
    _require_contains(source, "JOBTOMATIK_PROCESS_IDENTITY_HELPER=\"$PROCESS_IDENTITY_HELPER\"")


def test_promotion_mutable_state_is_git_ignored_and_runtime_affinity_reads_settings():
    ignored = GITIGNORE.read_text(encoding="utf-8")
    config = CONFIG.read_text(encoding="utf-8")
    handoff = BROWSER_HANDOFF.read_text(encoding="utf-8")
    runtime = BROWSER_RUNTIME_BASE.read_text(encoding="utf-8")

    _require_contains(ignored, "backend/.promotion-state/")
    _require_contains(config, 'jobtomatik_browser_node_id: str = ""')
    _require_contains(config, 'handoff_storage_dir: str = "handoff_sessions"')
    _require_contains(handoff, "get_settings().jobtomatik_browser_node_id")
    _require_contains(runtime, "get_settings().handoff_storage_dir")
