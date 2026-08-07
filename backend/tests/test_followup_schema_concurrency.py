from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import create_engine, inspect, text

from app.services.followup_schema import ensure_followup_schema


def test_concurrent_sqlite_followup_schema_upgrades_are_serialized(tmp_path):
    database_path = tmp_path / "concurrent-followups.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE followups ("
                "id INTEGER PRIMARY KEY, "
                "application_id INTEGER NOT NULL, "
                "scheduled_at TIMESTAMP NOT NULL, "
                "sent_at TIMESTAMP, "
                "subject VARCHAR(500), "
                "message TEXT, "
                "recipient_email VARCHAR(255), "
                "status VARCHAR(50), "
                "created_at TIMESTAMP"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO followups "
                "(id, application_id, scheduled_at, recipient_email, status) "
                "VALUES (1, 10, :scheduled, 'recruiter@example.test', 'pending')"
            ),
            {"scheduled": datetime.utcnow()},
        )

    def upgrade_once():
        ensure_followup_schema(engine)
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: upgrade_once(), range(2)))

    assert results == [True, True]
    columns = {item["name"] for item in inspect(engine).get_columns("followups")}
    assert "approval_status" in columns
    assert "send_idempotency_key" in columns
    assert "recruiter_contact_id" in columns

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, approval_status, send_idempotency_key "
                "FROM followups WHERE id = 1"
            )
        ).one()
    assert row[0] == "draft"
    assert row[1] == "unapproved"
    assert row[2]
