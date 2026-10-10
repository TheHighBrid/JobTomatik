import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.services import browser_runtime_base as runtime


@pytest.fixture
def proc_root(monkeypatch, tmp_path):
    root = tmp_path / 'proc'
    root.mkdir()
    monkeypatch.setattr(runtime, 'Path', lambda path: root if path == '/proc' else Path(path))
    return root


def add_process(root, pid, arguments):
    entry = root / str(pid)
    entry.mkdir()
    (entry / 'cmdline').write_bytes(b'\0'.join(os.fsencode(arg) for arg in arguments) + b'\0')
    return entry


@pytest.mark.parametrize('arguments,owned', [
    (['chromium', '--user-data-dir=/tmp/profile'], True),
    (['chromium', '--user-data-dir', '/tmp/profile'], True),
    (['chromium', '--user-data-dir=/tmp/profile-other'], False),
    (['chromium', '--user-data-dir', '/tmp/profile-other'], False),
    (['chromium', '--note=--user-data-dir=/tmp/profile'], False),
    (['other-browser', '--user-data-dir=/tmp/profile'], False),
    (['chromium', '--user-data-dir=/tmp/profile with spaces'], False),
])
def test_profile_owner_requires_complete_argument(proc_root, arguments, owned):
    add_process(proc_root, 4321, arguments)
    assert runtime._owned_profile_processes(Path('/tmp/profile')) == ([4321] if owned else [])


@pytest.mark.parametrize('failure', ['unavailable_root', 'unreadable_root', 'unreadable_pid', 'missing_cmdline'])
def test_incomplete_scan_preserves_markers(proc_root, monkeypatch, tmp_path, failure):
    profile = tmp_path / 'profile'
    profile.mkdir()
    for name in runtime.CHROMIUM_TRANSIENT_SINGLETON_NAMES:
        (profile / name).write_text('retained')
    entry = add_process(proc_root, 4321, ['unrelated'])
    if failure == 'unavailable_root':
        (entry / 'cmdline').unlink()
        entry.rmdir()
        proc_root.rmdir()
    elif failure == 'unreadable_root':
        original = Path.iterdir

        def iterdir(path):
            if path == proc_root:
                # Simulate an error after enumeration has already yielded data.
                yield entry
                raise PermissionError('denied')
            yield from original(path)

        monkeypatch.setattr(Path, 'iterdir', iterdir)
    elif failure == 'unreadable_pid':
        original = Path.read_bytes

        def read_bytes(path):
            if path == entry / 'cmdline':
                raise PermissionError('denied')
            return original(path)

        monkeypatch.setattr(Path, 'read_bytes', read_bytes)
    else:
        (entry / 'cmdline').unlink()

    assert runtime._owned_profile_processes(profile) is None
    with pytest.raises(runtime.BrowserRuntimeError, match='OWNERSHIP_UNKNOWN'):
        runtime._prepare_owned_profile(profile)
    assert all((profile / name).read_text() == 'retained' for name in runtime.CHROMIUM_TRANSIENT_SINGLETON_NAMES)


def test_vanished_pid_does_not_make_scan_incomplete(proc_root, monkeypatch):
    vanished = proc_root / '4321'
    add_process(proc_root, 4322, ['chromium', '--user-data-dir=/tmp/profile'])
    original = Path.iterdir
    monkeypatch.setattr(Path, 'iterdir', lambda path: iter([vanished, *original(path)]))
    assert runtime._owned_profile_processes(Path('/tmp/profile')) == [4322]


def lock_is_held_in_other_process(profile):
    result = subprocess.run(
        [sys.executable, '-c', '''
import fcntl, sys
with open(sys.argv[1], 'a+b') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(23)
''', str(profile / '.jobtomatik-startup.lock')],
        check=False, timeout=5,
    )
    assert result.returncode in (0, 23)
    return result.returncode == 23


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [None, 'launch', 'readiness', 'cancel'])
async def test_launch_holds_interprocess_lock_until_ready(monkeypatch, tmp_path, failure):
    profile = tmp_path / 'profile'
    profile.mkdir()
    marker = profile / 'SingletonLock'
    marker.write_text('stale')
    events = []
    process = SimpleNamespace(pid=4321)
    monkeypatch.setenv('HANDOFF_STORAGE_DIR', str(tmp_path / 'handoffs'))

    def scan(_profile):
        assert lock_is_held_in_other_process(profile)
        events.append('scan')
        return []

    def launch(*args, **kwargs):
        assert lock_is_held_in_other_process(profile)
        assert not marker.exists()
        events.append('launch')
        if failure == 'launch':
            raise RuntimeError('launch failed')
        return process

    async def wait(*args):
        assert lock_is_held_in_other_process(profile)
        # A competing launch must be rejected before it can scan or delete markers.
        marker.write_text('new owner')
        with pytest.raises(runtime.BrowserRuntimeError, match='PROFILE_IN_USE'):
            await runtime.launch_retainable_browser(playwright, profile_dir=profile)
        assert marker.read_text() == 'new owner'
        events.append('ready')
        if failure == 'readiness':
            raise RuntimeError('readiness failed')
        if failure == 'cancel':
            raise asyncio.CancelledError()

    async def connect(*args):
        assert not lock_is_held_in_other_process(profile)
        return object()

    async def page(*args, **kwargs):
        return object(), object()

    def terminate(_process):
        assert lock_is_held_in_other_process(profile)
        events.append('terminate')

    playwright = SimpleNamespace(chromium=SimpleNamespace(executable_path='/chromium'))
    monkeypatch.setattr(runtime, '_owned_profile_processes', scan)
    # Retain the real Popen used by subprocess.run in the cross-process lock probe.
    monkeypatch.setattr(runtime, 'subprocess', SimpleNamespace(Popen=launch, STDOUT=subprocess.STDOUT))
    monkeypatch.setattr(runtime, '_wait_for_cdp_endpoint', wait)
    monkeypatch.setattr(runtime, '_connect_playwright_over_cdp', connect)
    monkeypatch.setattr(runtime, '_create_owned_controlled_page', page)
    monkeypatch.setattr(runtime, '_terminate_owned_process', terminate)
    if failure:
        with pytest.raises(asyncio.CancelledError if failure == 'cancel' else RuntimeError):
            await runtime.launch_retainable_browser(playwright, profile_dir=profile)
    else:
        await runtime.launch_retainable_browser(playwright, profile_dir=profile)
    assert events[:2] == ['scan', 'launch']
    assert ('terminate' in events) == (failure in ('readiness', 'cancel'))
    assert not lock_is_held_in_other_process(profile)


@pytest.mark.parametrize('leader_exited', [False, True])
def test_cleanup_kills_survivor_after_leader_exits(tmp_path, leader_exited):
    """Use a real isolated group with a child that ignores SIGTERM."""
    pid_file = tmp_path / 'child.pid'
    ready_file = tmp_path / 'ready'
    leader = subprocess.Popen([sys.executable, '-c', '''
import os, signal, sys, time
pid = os.fork()
if pid == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    open(sys.argv[1], 'w').write(str(os.getpid()))
    while True:
        time.sleep(1)
while not os.path.exists(sys.argv[1]):
    time.sleep(0.01)
open(sys.argv[2], 'w').close()
if sys.argv[3] == 'True':
    sys.exit(0)
while True:
    time.sleep(1)
''', str(pid_file), str(ready_file), str(leader_exited)], start_new_session=True)
    import time
    try:
        deadline = time.monotonic() + 5
        while not ready_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready_file.exists()
        child_pid = int(pid_file.read_text())
        if leader_exited:
            leader.wait(timeout=5)
        runtime._terminate_owned_process(leader, timeout=0.1)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                state = Path(f'/proc/{child_pid}/stat').read_text().split(') ', 1)[1].split()[0]
            except FileNotFoundError:
                break
            if state == 'Z':
                break  # Dead child awaiting the sandbox init's reaper.
            time.sleep(0.01)
        else:
            pytest.fail('owned child survived cleanup')
        assert leader.poll() is not None
    finally:
        try:
            os.killpg(leader.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        leader.wait(timeout=5)
