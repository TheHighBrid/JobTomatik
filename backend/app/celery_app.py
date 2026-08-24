import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_init

from app.config import get_settings

settings = get_settings()


def _beat_scheduler_name() -> str:
    """Avoid dbm-backed Beat persistence inside the managed Android PRoot runtime.

    Android's Beat schedule is fully declared in code and recovery tasks are idempotent,
    so a persistent shelve database is unnecessary there. Keeping the default persistent
    scheduler elsewhere preserves existing non-Android deployment behavior.
    """
    runtime_mode = str(os.getenv("JOBTOMATIK_RUNTIME_MODE") or "").strip().lower()
    if runtime_mode == "android_managed":
        return "celery.beat:Scheduler"
    return "celery.beat:PersistentScheduler"


celery_app = Celery(
    "jobtomatik",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.scraping",
        "app.tasks.discovery",
        "app.tasks.applications",
        "app.tasks.handoffs",
        "app.tasks.unattended",
        "app.tasks.followup",
        "app.tasks.operations",
        "app.tasks.runtime",
        "app.tasks.shadow_runs",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    beat_scheduler=_beat_scheduler_name(),
    task_routes={
        "app.tasks.scraping.*": {"queue": "scraping"},
        "app.tasks.discovery.*": {"queue": "scraping"},
        "app.tasks.shadow_runs.*": {"queue": "scraping"},
        "app.tasks.applications.*": {"queue": "applications"},
        "app.tasks.handoffs.*": {"queue": "applications"},
        "app.tasks.unattended.*": {"queue": "applications"},
        "app.tasks.followup.*": {"queue": "followup"},
        "app.tasks.operations.*": {"queue": "followup"},
        "app.tasks.runtime.*": {"queue": "applications"},
    },
    beat_schedule={
        "check-followups-every-hour": {
            "task": "app.tasks.followup.send_pending_followups",
            "schedule": crontab(minute=0),
        },
        "continuous-job-discovery-hourly": {
            "task": "app.tasks.discovery.run_continuous_discovery",
            "schedule": crontab(minute=12),
        },
        "recover-stale-followup-deliveries": {
            "task": "app.tasks.followup.recover_stale_followup_deliveries",
            "schedule": crontab(minute="7,22,37,52"),
        },
        "recover-stale-application-attempts": {
            "task": "app.tasks.operations.recover_stale_application_attempts",
            "schedule": crontab(minute="5,20,35,50"),
        },
        "recover-stalled-shadow-campaigns": {
            "task": "app.tasks.shadow_runs.recover_stalled_shadow_sessions",
            "schedule": crontab(minute="11,26,41,56"),
        },
        "refresh-adapter-health-alerts-hourly": {
            "task": "app.tasks.operations.refresh_adapter_health_alerts",
            "schedule": crontab(minute=15),
        },
        "refresh-job-scores-daily": {
            "task": "app.tasks.scraping.refresh_all_scores",
            "schedule": crontab(hour=3, minute=0),
        },
        "daily-auto-search": {
            "task": "app.tasks.scraping.daily_auto_search_all",
            "schedule": crontab(hour="*/6", minute=0),
        },
    },
)


def ensure_worker_runtime_schema() -> None:
    """Create and compat-upgrade tables before this worker accepts tasks.

    FastAPI performs the same bootstrap during its lifespan. Android operators may
    restart Celery independently, however, so the worker must not assume the API
    process has already upgraded the shared SQLite database.
    """
    from app import models as _models  # noqa: F401
    from app.database import Base, engine
    from app.services.followup_schema import ensure_followup_schema

    Base.metadata.create_all(bind=engine)
    ensure_followup_schema(engine)


@worker_init.connect
def install_worker_task_integrations(**_kwargs):
    """Install schema, safety, discovery, policy, target-resolution, and browser extensions."""
    from app.services.application_integrity import install_closed_application_task_gate
    from app.services.application_queue_policy_integration import install_application_queue_policy
    from app.services.application_target_handoff import (
        install_application_target_handoff_task_persistence,
    )
    from app.services.application_target_task_integration import (
        install_application_target_task_integration,
    )
    from app.services.discovery_freshness_integration import install_scheduler_freshness_gate
    from app.services.handoff_integration import install_handoff_task_integration
    from app.services.operator_autonomy_control_integration import install_operator_autonomy_control
    from app.services.supervised_submission_integration import (
        install_supervised_submission_task_gate,
    )

    ensure_worker_runtime_schema()
    install_handoff_task_integration()
    install_application_target_handoff_task_persistence()
    install_application_target_task_integration()
    install_scheduler_freshness_gate()
    install_application_queue_policy()
    # Wrap the complete Day 30 evaluator so pause/drain cannot be bypassed by workers.
    install_operator_autonomy_control()
    install_supervised_submission_task_gate()
    # Must wrap the supervised gate so a stale task cannot consume an approval.
    install_closed_application_task_gate()
