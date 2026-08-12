from pathlib import Path
import subprocess

from app.celery_app import _beat_scheduler_name
from scripts.retire_legacy_android_celery import managed_broker_worker_names


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_android_managed_beat_avoids_dbm_backed_persistent_scheduler(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    assert _beat_scheduler_name() == "celery.beat:Scheduler"


def test_non_android_beat_keeps_existing_persistent_scheduler(monkeypatch):
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_MODE", raising=False)
    assert _beat_scheduler_name() == "celery.beat:PersistentScheduler"


def test_managed_broker_cleanup_includes_legacy_default_worker_on_db1():
    workers = [
        "celery@localhost",
        "jobtomatik-android-oldrev@localhost",
        "jobtomatik-android-oldrev@remote.example",
        "analytics@localhost",
    ]

    assert managed_broker_worker_names(
        workers,
        local_hosts={"localhost", "device"},
    ) == [
        "celery@localhost",
        "jobtomatik-android-oldrev@localhost",
    ]


def test_android_manager_derives_its_root_from_bash_source():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert 'SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"' in manager
    assert 'dirname -- "$SCRIPT_SOURCE"' in manager
    assert 'BACKEND_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"' not in manager


def test_bash_source_path_survives_parent_shell_argv0(tmp_path):
    manager = tmp_path / "backend" / "scripts" / "probe.sh"
    manager.parent.mkdir(parents=True)
    manager.write_text(
        'SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"\n'
        'BACKEND_ROOT="$(cd -- "$(dirname -- "$SCRIPT_SOURCE")/.." && pwd)"\n'
        'printf "%s\\n" "$SCRIPT_SOURCE" "$BACKEND_ROOT"\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "-c", f'source "{manager}"'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.splitlines()
    assert lines[0] == str(manager)
    assert lines[1] == str(tmp_path / "backend")


def test_detached_android_manager_is_sourced_by_long_lived_proot_shell_with_manager_argv0():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    detached = (
        r"exec bash -c 'source \"\$0\" \"\$1\" && exec sleep infinity' "
        "backend/scripts/manage_android_stack.sh '$action'"
    )
    assert detached in wrapper
    assert "source backend/scripts/manage_android_stack.sh '$action' && exec sleep infinity" not in wrapper


def test_sourced_bash_receives_manager_path_as_argv0(tmp_path):
    manager = tmp_path / "backend" / "scripts" / "manage_android_stack.sh"
    manager.parent.mkdir(parents=True)
    manager.write_text(
        "printf '%s\\n' \"$0\" \"${1:-}\" \"$(cd -- \"$(dirname -- \"$0\")/..\" && pwd)\"\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$0" "$1"',
            str(manager),
            "restart",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.splitlines()
    assert lines[0] == str(manager)
    assert lines[1] == "restart"
    assert lines[2] == str(tmp_path / "backend")


def test_android_wrapper_propagates_managed_runtime_and_static_frontend_modes_to_manager():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    foreground = (
        "export JOBTOMATIK_RUNTIME_MODE=android_managed "
        "JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE' && "
        "bash backend/scripts/manage_android_stack.sh '$action'"
    )
    detached = (
        "export JOBTOMATIK_RUNTIME_MODE=android_managed "
        "JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE' && "
        r"exec bash -c 'source \"\$0\" \"\$1\" && exec sleep infinity' "
        "backend/scripts/manage_android_stack.sh '$action'"
    )

    assert foreground in wrapper
    assert detached in wrapper


def test_android_manager_worker_readiness_does_not_depend_on_remote_inspect():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert "celery_app.control.inspect" not in manager
    assert "active_queues()" not in manager
    assert "worker_control_ready" not in manager
    assert "worker_process_identity_ready && worker_application_canary_ready" in manager


def test_android_manager_worker_canary_is_bound_to_managed_pid_and_queue_cmdline():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert 'JOBTOMATIK_EXPECTED_WORKER_PID="$worker_pid"' in manager
    assert 'JOBTOMATIK_EXPECTED_WORKER_QUEUES="applications,celery,followup,scraping"' in manager
    assert 'f"jobtomatik-android-{revision_short}@"' in manager
    assert 'if int(payload.get("worker_pid", -1)) != expected_worker_pid:' in manager
