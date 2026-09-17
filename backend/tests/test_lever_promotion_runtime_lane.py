from __future__ import annotations

import subprocess
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts/jobtomatik_promotion_lane.sh"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _function(source: str, name: str, next_name: str) -> str:
    start = source.index(f"{name}() {{")
    end = source.index(f"{next_name}() {{", start)
    return source[start:end]


def test_promotion_lane_shell_is_syntax_valid_and_keeps_frozen_revision_explicit():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    source = _source()

    assert "198b197dfcece6fbf9f3edfc5a92511fd951b484" in source
    assert 'FROZEN_REPO="${JOBTOMATIK_FROZEN_PROOT_REPO:-/root/JobTomatik}"' in source
    assert 'PROMOTION_REPO="${JOBTOMATIK_PROMOTION_PROOT_REPO:-/root/JobTomatik-promotion}"' in source
    assert "git -C \"$source_repo\" worktree add --detach" in source
    assert "source.backup(target)" in source
    assert 'target.execute("PRAGMA quick_check")' in source
    assert 'ln -s "$source_repo/backend/.venv"' in source
    assert 'source_requirements="$(git -C "$source_repo" rev-parse' in source
    assert 'target_requirements="$(git -C "$source_repo" rev-parse' in source


def test_promotion_lane_forces_persistent_submit_and_autopilot_flags_off():
    source = _source()

    for expected in (
        '"ALLOW_REAL_APPLICATION_SUBMIT": "false"',
        '"ALLOW_REAL_FOLLOWUP_SEND": "false"',
        '"AUTOPILOT_ENABLED": "false"',
        '"GREENHOUSE_SUPERVISED_PILOT_ENABLED": "false"',
        '"LEVER_SUPERVISED_PILOT_ENABLED": "false"',
        '"final_submit_authority_created": False',
    ):
        assert expected in source

    assert "ALLOW_REAL_APPLICATION_SUBMIT=true" not in source
    assert "LEVER_SUPERVISED_PILOT_ENABLED=true" not in source
    assert "AUTOPILOT_ENABLED=true" not in source
    assert "promotion_pilot arm" not in source
    assert 'PILOT_COMMAND" arm' not in source


def test_promotion_lane_isolates_database_runtime_browser_and_transient_control_state():
    source = _source()

    assert "jobtomatik-promotion.db" in source
    assert "$HOME/.jobtomatik-promotion-runtime" in source
    assert "$HOME/.jobtomatik-promotion-chromium" in source
    assert "JOBTOMATIK_ANDROID_BROWSER_PROFILE=\"$PROMOTION_BROWSER_PROFILE\"" in source
    assert "JOBTOMATIK_ANDROID_RUNTIME_DIR=\"$PROMOTION_RUNTIME_DIR\"" in source
    assert "archive_shared_control_dir" in source
    assert "pilot-control-archives" in source
    assert 'Path("backend/uploads")' in source
    assert 'Path("backend/handoff_sessions")' in source


def test_start_proves_frozen_rollback_before_stopping_frozen_lane_and_requires_acceptance():
    source = _source()
    start = _function(source, "start_lane", "stop_lane")

    assert start.index("verify_frozen_return_artifact") < start.index("frozen_stack stop")
    assert start.index("frozen_stack stop") < start.index("promotion_stack start")
    assert "promotion_stack acceptance" in start
    assert "promotion_pilot status" in start
    assert "lever-pilot-runtime.active" in start
    assert "lever-pilot-runtime.pending" in start
    assert "JOBTOMATIK_PROMOTION_LANE_READY_FAIL_SAFE" in start


def test_failed_promotion_start_or_acceptance_attempts_frozen_recovery():
    source = _source()
    start = _function(source, "start_lane", "stop_lane")

    assert start.count("frozen_stack start || true") >= 2
    assert "failed-promotion-start" in start
    assert "failed-promotion-acceptance" in start


def test_return_frozen_never_updates_or_switches_the_frozen_checkout():
    source = _source()
    restore = _function(source, "return_frozen", "status_lane")

    assert "verify_frozen_return_artifact" in restore
    assert "frozen_stack start" in restore
    assert "frozen_stack acceptance" in restore
    assert "git switch" not in restore
    assert "git pull" not in restore
    assert "update" not in restore
