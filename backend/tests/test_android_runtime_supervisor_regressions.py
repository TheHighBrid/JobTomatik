from pathlib import Path

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


def test_detached_android_manager_is_sourced_by_long_lived_proot_shell():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    assert "source backend/scripts/manage_android_stack.sh '$action' && exec sleep infinity" in wrapper
    assert "bash backend/scripts/manage_android_stack.sh '$action' && exec sleep infinity" not in wrapper


def test_android_wrapper_propagates_managed_runtime_mode_to_manager():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    foreground = (
        "export JOBTOMATIK_RUNTIME_MODE=android_managed && "
        "bash backend/scripts/manage_android_stack.sh '$action'"
    )
    detached = (
        "export JOBTOMATIK_RUNTIME_MODE=android_managed && "
        "source backend/scripts/manage_android_stack.sh '$action' && exec sleep infinity"
    )

    assert foreground in wrapper
    assert detached in wrapper
