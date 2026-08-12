from pathlib import Path

from app.celery_app import celery_app


REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGER = REPO_ROOT / "backend" / "scripts" / "manage_android_stack.sh"
FRONTEND_DETAIL = REPO_ROOT / "frontend" / "src" / "pages" / "ApplicationDetail.jsx"
RUNTIME_HELPER = REPO_ROOT / "frontend" / "src" / "applicationTaskRuntime.js"


def test_celery_exposes_started_state_for_long_browser_tasks():
    assert celery_app.conf.task_track_started is True
    assert celery_app.conf.broker_connection_retry_on_startup is True
    assert "app.tasks.runtime" in celery_app.conf.include


def test_android_status_requires_managed_worker_identity_and_application_queue_round_trip():
    source = MANAGER.read_text(encoding="utf-8")

    assert "worker_process_identity_ready" in source
    assert 'JOBTOMATIK_EXPECTED_WORKER_QUEUES="applications,celery,followup,scraping"' in source
    assert 'f"jobtomatik-android-{revision_short}@"' in source
    assert 'Path("/proc") / str(pid) / "cmdline"' in source
    assert "worker_application_canary_ready" in source
    assert 'JOBTOMATIK_EXPECTED_WORKER_PID="$worker_pid"' in source
    assert "application_queue_canary.apply_async" in source
    assert 'int(payload.get("worker_pid", -1)) != expected_worker_pid' in source
    assert "celery_app.control.inspect" not in source
    assert "active_queues()" not in source
    assert "CELERY_APPLICATION_CANARY: READY" in source
    assert "DOWN_OR_UNRESPONSIVE_ON_ANDROID_BROKER" in source
    assert "CELERY_LOG:" in source


def test_application_page_does_not_restore_old_celery_task_ids_after_runtime_restart():
    source = FRONTEND_DETAIL.read_text(encoding="utf-8")

    assert "sessionStorage" not in source
    assert "setSubmitQueuedAt(Date.now())" in source
    assert "shouldReleaseUnacknowledgedTask" in source
    assert "if (app?.automation_state === 'applying') return undefined" not in source
    assert "obsolete navigation-only review" in source


def test_pending_task_timeout_does_not_trust_stale_applying_database_state():
    source = RUNTIME_HELPER.read_text(encoding="utf-8")
    release_helper = source.split("export function applicationRuntimeBusy", 1)[0]

    assert "PENDING" in release_helper
    assert "TASK_START_ACK_TIMEOUT_MS" in release_helper
    assert "toLowerCase() === 'applying'" not in release_helper
