from app import celery_app as celery_module
from app import database


def test_worker_schema_bootstrap_uses_shared_runtime_engine(monkeypatch):
    calls = []

    def fake_create_all(*, bind):
        calls.append(bind)

    monkeypatch.setattr(database.Base.metadata, "create_all", fake_create_all)

    celery_module.ensure_worker_runtime_schema()

    assert calls == [database.engine]
