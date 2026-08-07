from scripts.retire_legacy_android_celery import (
    legacy_local_worker_names,
    managed_android_worker_names,
)


def test_only_default_local_legacy_worker_is_selected():
    workers = [
        "celery@localhost",
        "jobtomatik-android@localhost",
        "jobtomatik-android-abc123@localhost",
        "celery@remote-worker.example",
        "analytics@localhost",
    ]

    assert legacy_local_worker_names(
        workers,
        local_hosts={"localhost", "device"},
    ) == ["celery@localhost"]


def test_managed_android_workers_are_excluded_from_legacy_selection():
    assert legacy_local_worker_names(
        ["jobtomatik-android@localhost", "jobtomatik-android-abc123@localhost"],
        local_hosts={"localhost"},
    ) == []


def test_managed_selector_targets_only_local_jobtomatik_workers():
    workers = [
        "jobtomatik-android@localhost",
        "jobtomatik-android-abc123@localhost",
        "jobtomatik-android-abc123@remote.example",
        "celery@localhost",
    ]

    assert managed_android_worker_names(
        workers,
        local_hosts={"localhost", "device"},
    ) == [
        "jobtomatik-android-abc123@localhost",
        "jobtomatik-android@localhost",
    ]
