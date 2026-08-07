from pathlib import Path

from app.celery_app import celery_app


REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGER = REPO_ROOT / "backend" / "scripts" / "manage_android_stack.sh"
FRONTEND_DETAIL = REPO_ROOT / "frontend" / "src" / "pages" / "ApplicationDetail.jsx"


def test_celery_exposes_started_state_for_long_browser_tasks():
    assert celery_app.conf.task_track_started is True
    assert celery_app.conf.broker_connection_retry_on_startup is True


def test_android_status_requires_live_worker_control_response_and_queue_contract():
    source = MANAGER.read_text(encoding="utf-8")

    assert "worker_control_ready" in source
    assert "celery_app.control.inspect(timeout=2.0)" in source
    assert "inspect.ping()" in source
    assert "inspect.active_queues()" in source
    assert '{"applications", "celery", "followup", "scraping"}' in source
    assert "DOWN_OR_UNRESPONSIVE_ON_ANDROID_BROKER" in source
    assert "CELERY_LOG:" in source


def test_application_page_does_not_restore_old_celery_task_ids_after_runtime_restart():
    source = FRONTEND_DETAIL.read_text(encoding="utf-8")

    assert "sessionStorage" not in source
    assert "setSubmitQueuedAt(Date.now())" in source
    assert "shouldReleaseUnacknowledgedTask" in source
    assert "app.automation_state === 'applying'" in source
    assert "obsolete navigation-only review" in source
