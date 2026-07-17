from celery import Celery
from celery.schedules import crontab
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "jobtomatik",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.scraping",
        "app.tasks.applications",
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
        "app.tasks.unattended.*": {"queue": "applications"},
        "app.tasks.followup.*": {"queue": "followup"},
        "app.tasks.operations.*": {"queue": "followup"},
    },
    beat_schedule={
        "check-followups-every-hour": {
            "task": "app.tasks.followup.send_pending_followups",
            "schedule": crontab(minute=0),
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
