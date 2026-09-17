from __future__ import annotations

from pathlib import Path
from shutil import which
from subprocess import run


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts/jobtomatik_promotion_lane.sh"
STATE_PREPARER = BACKEND_ROOT / "scripts/prepare_lever_promotion_lane_state.py"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _function(source: str, name: str, next_name: str) -> str:
    start = source.index(f"{name}() {{")
    end = source.index(f"{next_name}() {{", start)
    return source[start:end]


def test_promotion_lane_shell_is_syntax_valid_and_keeps_frozen_revision_explicit():
    bash = which("bash")
    assert bash is not None
    run([bash, "-n", str(SCRIPT)], check=True)
    source = _source()

    assert "198b197dfcece6fbf9f3edfc5a92511fd951b484" in source
    assert 'FROZEN_REPO="${JOBTOMATIK_FROZEN_PROOT_REPO:-/root/JobTomatik}"' in source
    assert 'PROMOTION_REPO="${JOBTOMATIK_PROMOTION_PROOT_REPO:-/root/JobTomatik-promotion}"' in source
    assert "git -C \"$source_repo\" worktree add --detach" in source
    assert 'ln -s "$source_repo/backend/.venv"' in source
    assert 'source_requirements="$(git -C "$source_repo" rev-parse' in source
    assert 'target_requirements="$(git -C "$source_repo" rev-parse' in source
    assert "cat-file -e" in source
    assert "prepare_lever_promotion_lane_state.py prepare" in source
    assert "prepare_lever_promotion_lane_state.py verify" in source
    assert STATE_PREPARER.is_file()


def test_promotion_lane_has_no_embedded_database_mutation_logic_or_submit_arm():
    source = _source()

    assert "source.backup(target)" not in source
    assert "sqlite3.connect" not in source
    assert "ALLOW_REAL_APPLICATION_SUBMIT=true" not in source
    assert "LEVER_SUPERVISED_PILOT_ENABLED=true" not in source
    assert "AUTOPILOT_ENABLED=true" not in source
    assert "promotion_pilot arm" not in source
    assert 'PILOT_COMMAND" arm' not in source


def test_promotion_lane_isolates_runtime_browser_broker_and_transient_control_state():
    source = _source()

    assert "$HOME/.jobtomatik-promotion-runtime" in source
    assert "$HOME/.jobtomatik-promotion-chromium" in source
    assert "redis://localhost:${PROMOTION_REDIS_PORT}/${PROMOTION_REDIS_DB}" in source
    assert "JOBTOMATIK_ANDROID_REDIS_URL=\"$PROMOTION_REDIS_URL\"" in source
    assert "JOBTOMATIK_ANDROID_REDIS_URL=\"$FROZEN_REDIS_URL\"" in source
    assert "start_promotion_redis" in source
    assert "stop_promotion_redis" in source
    assert "FLUSHDB" in source
    assert "promotion-redis.rdb" in source
    assert "JOBTOMATIK_ANDROID_BROWSER_PROFILE=\"$PROMOTION_BROWSER_PROFILE\"" in source
    assert "JOBTOMATIK_ANDROID_RUNTIME_DIR=\"$PROMOTION_RUNTIME_DIR\"" in source
    assert "archive_shared_control_dir" in source
    assert "pilot-control-archives" in source


def test_existing_lane_must_match_freshly_fetched_current_main():
    source = _source()
    prepare = _function(source, "prepare_lane", "restore_frozen_after_failure")

    assert 'if [[ "$existing_target" != "$target_revision" ]]' in prepare
    assert "Existing promotion lane is not current main" in prepare
    assert "Refusing implicit upgrade" in prepare


def test_start_proves_frozen_rollback_before_stopping_frozen_lane_and_requires_acceptance():
    source = _source()
    start = _function(source, "start_lane", "stop_lane")

    assert start.index("verify_frozen_return_artifact") < start.index("frozen_stack stop")
    assert start.index("frozen_stack stop") < start.index("start_promotion_redis")
    assert start.index("start_promotion_redis") < start.index("promotion_stack start")
    assert "promotion_stack acceptance" in start
    assert "promotion_pilot status" in start
    assert "lever-pilot-runtime.active" in start
    assert "lever-pilot-runtime.pending" in start
    assert "JOBTOMATIK_PROMOTION_LANE_READY_FAIL_SAFE" in start


def test_every_post_stop_failure_path_restores_the_frozen_lane():
    source = _source()
    start = _function(source, "start_lane", "stop_lane")
    recovery = _function(source, "restore_frozen_after_failure", "start_lane")

    assert "frozen_stack start || true" in recovery
    assert "stop_promotion_redis" in recovery
    assert "failed-promotion-start" in start
    assert "failed-promotion-acceptance" in start
    assert "unexpected-promotion-pilot-marker" in start
    assert "failed-promotion-pilot-status" in start
    assert start.count("restore_frozen_after_failure") >= 4
    assert "Promotion Redis failed to start; restoring frozen lane" in start
    assert "frozen_stack start || true" in start


def test_return_frozen_never_updates_or_switches_the_frozen_checkout():
    source = _source()
    restore = _function(source, "return_frozen", "status_lane")

    assert "stop_promotion_redis" in restore
    assert "verify_frozen_return_artifact" in restore
    assert "frozen_stack start" in restore
    assert "frozen_stack acceptance" in restore
    assert "git switch" not in restore
    assert "git pull" not in restore
    assert "update" not in restore
