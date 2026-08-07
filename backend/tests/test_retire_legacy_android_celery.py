from scripts.retire_legacy_android_celery import legacy_local_worker_names


def test_only_default_local_legacy_worker_is_selected():
    workers = [
        "celery@localhost",
        "jobtomatik-android@localhost",
        "celery@remote-worker.example",
        "analytics@localhost",
    ]

    assert legacy_local_worker_names(
        workers,
        local_hosts={"localhost", "device"},
    ) == ["celery@localhost"]


def test_managed_android_worker_is_never_selected_for_retirement():
    assert legacy_local_worker_names(
        ["jobtomatik-android@localhost"],
        local_hosts={"localhost"},
    ) == []
