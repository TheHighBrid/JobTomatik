from types import SimpleNamespace

from app.api import supervised_submissions as supervised_api


class _FakeSendApp:
    def __init__(self):
        self.calls = []

    def send_task(self, name, *, args, kwargs, queue):
        self.calls.append(
            {
                "name": name,
                "args": args,
                "kwargs": kwargs,
                "queue": queue,
            }
        )
        return SimpleNamespace(id="celery-task-123")


class _FakeQuery:
    def __init__(self, row):
        self.row = row

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.row


class _FakeDb:
    def __init__(self, latest_attempt_number):
        self.latest_attempt_number = latest_attempt_number
        self.flush_calls = 0

    def query(self, _column):
        row = (
            (self.latest_attempt_number,)
            if self.latest_attempt_number is not None
            else None
        )
        return _FakeQuery(row)

    def flush(self):
        self.flush_calls += 1


def test_supervised_publish_uses_named_task_with_exact_immutable_envelope(monkeypatch):
    fake_app = _FakeSendApp()
    fake_task = SimpleNamespace(
        name="app.tasks.applications.submit_application_task",
        app=fake_app,
    )
    monkeypatch.setattr(supervised_api, "submit_application_task", fake_task)

    result = supervised_api._publish_supervised_submission_task(
        220,
        "ghsup-approval",
        "attempt-reference",
    )

    assert result.id == "celery-task-123"
    assert fake_app.calls == [
        {
            "name": "app.tasks.applications.submit_application_task",
            "args": [220],
            "kwargs": {
                "dry_run": False,
                "approval_reference": "ghsup-approval",
                "attempt_reference": "attempt-reference",
            },
            "queue": "applications",
        }
    ]


def test_blocked_preworker_reservation_advances_next_attempt_baseline():
    db = _FakeDb(latest_attempt_number=1)
    application = SimpleNamespace(id=220, submission_attempt_count=0)

    supervised_api._synchronize_submission_attempt_counter(db, application)

    assert application.submission_attempt_count == 1
    assert db.flush_calls == 1


def test_attempt_counter_is_never_moved_backwards():
    db = _FakeDb(latest_attempt_number=1)
    application = SimpleNamespace(id=220, submission_attempt_count=3)

    supervised_api._synchronize_submission_attempt_counter(db, application)

    assert application.submission_attempt_count == 3
    assert db.flush_calls == 0
