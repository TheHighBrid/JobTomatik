from __future__ import annotations

import os
import signal
import time
from pathlib import Path

from app.models.handoff import ManualHandoffSession
from app.services.browser_handoff import BrowserHandoffUnavailable, _require_local_affinity


_TERMINATION_POLL_SECONDS = 0.05
_DEFAULT_GRACEFUL_TIMEOUT_SECONDS = 5.0
_DEFAULT_KILL_TIMEOUT_SECONDS = 5.0


def _reap_child_if_possible(pid: int) -> bool:
    """Reap a terminated child when the current worker is its parent."""
    try:
        waited_pid, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return False
    except OSError:
        return False
    return waited_pid == pid


def _linux_process_state(pid: int) -> str:
    """Return the Linux /proc process state when available."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        suffix = raw.rsplit(")", 1)[1].strip()
        return suffix.split(None, 1)[0] if suffix else ""
    except (OSError, IndexError):
        return ""


def _process_exited(pid: int) -> bool:
    if _reap_child_if_possible(pid):
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    # A zombie has already exited and owns no browser resources. If it is not
    # our child, only its actual parent can reap the process-table entry.
    return _linux_process_state(pid) == "Z"


def _wait_for_process_exit(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout))
    while time.monotonic() < deadline:
        if _process_exited(pid):
            return True
        time.sleep(_TERMINATION_POLL_SECONDS)
    return _process_exited(pid)


def _require_expected_browser_process(session: ManualHandoffSession, pid: int) -> None:
    """Fail closed before signalling a stale or obviously wrong PID."""
    if pid <= 1 or pid == os.getpid():
        raise BrowserHandoffUnavailable(
            "The retained browser PID is unsafe to terminate; refusing process cleanup."
        )

    profile_path = str(session.browser_profile_path or "").strip()
    cmdline_path = Path(f"/proc/{pid}/cmdline")
    if not profile_path or not cmdline_path.exists():
        return
    try:
        command = cmdline_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace")
    except OSError:
        return
    expected = f"--user-data-dir={profile_path}"
    if expected not in command:
        raise BrowserHandoffUnavailable(
            "The retained browser PID no longer matches the recorded JobTomatik profile; "
            "refusing to signal a potentially reused process id."
        )


def _signal_owned_browser(pid: int, sig: signal.Signals) -> None:
    """Signal the isolated Chromium process group when it is still the group leader."""
    try:
        process_group = os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        process_group = None

    if process_group == pid:
        os.killpg(process_group, sig)
    else:
        os.kill(pid, sig)


def terminate_retained_browser(
    session: ManualHandoffSession,
    *,
    graceful_timeout: float = _DEFAULT_GRACEFUL_TIMEOUT_SECONDS,
    kill_timeout: float = _DEFAULT_KILL_TIMEOUT_SECONDS,
) -> bool:
    """Terminate a JobTomatik-owned retained browser and verify it is gone.

    The retained Chromium launcher starts an isolated process session. Handoff
    reconciliation may no longer have the original ``Popen`` handle, so merely
    sending SIGTERM is insufficient: the worker must verify exit, reap its child
    when possible, and escalate to SIGKILL only when the recorded Chromium is
    still alive.
    """
    _require_local_affinity(session)
    pid = int(session.browser_process_id or 0)
    if not pid:
        return False

    if _process_exited(pid):
        return False
    _require_expected_browser_process(session, pid)

    try:
        _signal_owned_browser(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        raise BrowserHandoffUnavailable(
            "The retained browser process cannot be terminated safely."
        ) from exc

    if _wait_for_process_exit(pid, graceful_timeout):
        return True

    try:
        _signal_owned_browser(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError as exc:
        raise BrowserHandoffUnavailable(
            "The retained browser process cannot be force-terminated safely."
        ) from exc

    if _wait_for_process_exit(pid, kill_timeout):
        return True

    raise BrowserHandoffUnavailable(
        "The retained browser process did not terminate after SIGTERM/SIGKILL; "
        "handoff cleanup is incomplete."
    )
