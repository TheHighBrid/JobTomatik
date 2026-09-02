from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_ROOT / "docs" / "operations" / "FINAL_DAY_ANDROID_RUNTIME_HANDOFF.md"


def test_final_day_handoff_sanitizes_pids_before_direct_stack_start() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    sanitizer = "bash scripts/sanitize_android_runtime_pid_files.sh"
    start = "bash scripts/manage_android_stack.sh start"

    assert sanitizer in text
    assert start in text
    assert text.index(sanitizer) < text.index(start)
    assert 'JOBTOMATIK_RUNTIME_REVISION="$CANDIDATE_SHA"' in text
    assert "removes a stale PID file without signalling the unrelated live process" in text
