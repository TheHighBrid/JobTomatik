import pytest
from scripts import start_onehost_display as display


def test_reused_pid_lock_is_removed_before_display_restart(tmp_path, monkeypatch):
    lock, socket = tmp_path / "lock", tmp_path / "socket"
    lock.write_text("7")
    socket.touch()
    monkeypatch.setattr(display, "is_display_process", lambda pid: False)
    display.remove_stale_display_files(lock, socket)
    assert not lock.exists() and not socket.exists()


def test_live_display_lock_is_never_removed(tmp_path, monkeypatch):
    lock, socket = tmp_path / "lock", tmp_path / "socket"
    lock.write_text("7")
    socket.touch()
    monkeypatch.setattr(display, "is_display_process", lambda pid: True)
    with pytest.raises(RuntimeError, match="refusing to remove"):
        display.remove_stale_display_files(lock, socket)
    assert lock.exists() and socket.exists()


def test_reachable_display_is_reused_without_starting_another_server(monkeypatch):
    monkeypatch.setenv("APPLICATION_BROWSER_HEADLESS", "false")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(display, "display_ready", lambda: True)
    def forbidden(*args, **kwargs): raise AssertionError("must not start a second display")
    monkeypatch.setattr(display.subprocess, "Popen", forbidden)
    display.main()
