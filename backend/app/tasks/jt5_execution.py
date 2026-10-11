"""JT5 worker entry point. Disabled until browser execution integration is complete.

Do not claim an attempt without actually running and finalizing it.
"""
from app.celery_app import celery_app


@celery_app.task(name="app.tasks.jt5_execution.execute_reserved_application", queue="applications", max_retries=0)
def execute_reserved_application(application_id: int, attempt_reference: str):
    raise RuntimeError("JT5 worker cutover is not complete; do not dispatch reserved attempts")
