from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_init

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "jobtomatik",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.scraping",
        "app.tasks.applications",
        "app.tasks.handoffs",
        "app.tasks.unattended",
        "app.tasks.followup",
        "app.tasks.operations",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.tasks.scraping.*": {"queue": "scraping"},
        "app.tasks.applications.*": {"queue": "applications"},
        "app.tasks.handoffs.*": {"queue": "applications"},
        "app.tasks.unattended.*": {"queue": "applications"},
        "app.tasks.followup.*": {"queue": "followup"},
        "app.tasks.operations.*": {"queue": "followup"},
    },
    beat_schedule={
        "check-followups-every-hour": {
            "task": "app.tasks.followup.send_pending_followups",
            "schedule": crontab(minute=0),
        },
        "recover-stale-application-attempts": {
            "task": "app.tasks.operations.recover_stale_application_attempts",
            "schedule": crontab(minute="5,20,35,50"),
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


@worker_init.connect
def install_worker_task_integrations(**_kwargs):
    """Install safety and retained-browser extensions in the Celery process.

    FastAPI installs these wrappers in the web process, but application attempts
    execute in Celery. Installing them at worker startup keeps both processes on
    the same task path and registers resumable handoff creation before any job is
    consumed.
    """
    from app.services.application_integrity import install_closed_application_task_gate
    from app.services.handoff_integration import install_handoff_task_integration
    from app.services.supervised_submission_integration import (
        install_supervised_submission_task_gate,
    )

    install_handoff_task_integration()
    install_supervised_submission_task_gate()
    # Must wrap the supervised gate so a stale task cannot consume an approval.
    install_closed_application_task_gate()
