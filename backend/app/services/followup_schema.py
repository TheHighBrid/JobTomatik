"""Backward-compatible schema upgrade for supervised follow-up delivery."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.engine import Engine


def ensure_followup_schema(engine: Engine) -> None:
    """Upgrade legacy follow-up rows without making any of them sendable.

    This runs from both FastAPI and Celery startup because Android deployments may
    restart the worker before the API process. Legacy ``pending`` rows are demoted
    to draft/review states before indexes are installed.
    """
    inspector = sa_inspect(engine)
    if "followups" not in inspector.get_table_names():
        return

    with engine.begin() as conn:
        columns = {item["name"] for item in sa_inspect(engine).get_columns("followups")}
        additions = {
            "recruiter_contact_id": "INTEGER",
            "payload_hash": "VARCHAR(128)",
            "approval_reference": "VARCHAR(255)",
            "approval_status": "VARCHAR(40) DEFAULT 'unapproved' NOT NULL",
            "approval_payload_hash": "VARCHAR(128)",
            "approved_at": "TIMESTAMP",
            "approval_expires_at": "TIMESTAMP",
            "approved_by_user_id": "INTEGER",
            "send_idempotency_key": "VARCHAR(255)",
            "send_attempt_count": "INTEGER DEFAULT 0 NOT NULL",
            "last_send_attempt_at": "TIMESTAMP",
            "delivery_metadata": "JSON",
            "updated_at": "TIMESTAMP",
        }
        for column_name, definition in additions.items():
            if column_name not in columns:
                conn.execute(
                    text(f"ALTER TABLE followups ADD COLUMN {column_name} {definition}")
                )

        conn.execute(
            text(
                "UPDATE followups SET approval_status = 'unapproved' "
                "WHERE approval_status IS NULL OR approval_status = ''"
            )
        )
        conn.execute(
            text(
                "UPDATE followups SET send_attempt_count = 0 "
                "WHERE send_attempt_count IS NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE followups SET status = CASE "
                "WHEN recipient_email IS NULL OR TRIM(recipient_email) = '' "
                "THEN 'needs_recipient' ELSE 'draft' END "
                "WHERE status = 'pending'"
            )
        )

        missing_keys = conn.execute(
            text(
                "SELECT id FROM followups "
                "WHERE send_idempotency_key IS NULL OR send_idempotency_key = ''"
            )
        ).fetchall()
        for row in missing_keys:
            conn.execute(
                text(
                    "UPDATE followups SET send_idempotency_key = :key WHERE id = :id"
                ),
                {"key": f"legacy-followup-{row[0]}-{uuid4()}", "id": row[0]},
            )

        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_followups_approval_reference "
                "ON followups (approval_reference)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_followups_send_idempotency_key "
                "ON followups (send_idempotency_key)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_followups_recruiter_contact_id "
                "ON followups (recruiter_contact_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_followups_status "
                "ON followups (status)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_followups_approval_status "
                "ON followups (approval_status)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_followups_payload_hash "
                "ON followups (payload_hash)"
            )
        )
