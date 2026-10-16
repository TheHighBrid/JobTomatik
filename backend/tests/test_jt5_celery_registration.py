"""JT5 worker task must be importable and routed onto the applications queue."""
from app.celery_app import celery_app


def test_jt5_task_module_is_included():
    assert "app.tasks.jt5_execution" in celery_app.conf.include


def test_jt5_task_routes_to_applications_queue():
    routes = celery_app.conf.task_routes or {}
    assert routes.get("app.tasks.jt5_execution.*") == {"queue": "applications"}


def test_jt5_task_is_registered():
    # Import side-effect registers the task on the shared Celery app.
    from app.tasks.jt5_execution import execute_reserved_application

    assert execute_reserved_application.name == (
        "app.tasks.jt5_execution.execute_reserved_application"
    )
    assert execute_reserved_application.name in celery_app.tasks
