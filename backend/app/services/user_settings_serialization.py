"""Transaction serialization for account-scoped JSON settings mutations."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.user import User


def acquire_user_settings_write_lock(db: Session, user_id: int) -> User:
    """
    Serialize a settings read/modify/write transaction and return fresh state.

    SQLite ignores ``SELECT ... FOR UPDATE``. Starting with a harmless write makes
    SQLite acquire its database write reservation before the JSON snapshot is read;
    on databases with row-level locking, the update locks only this user row. Raw
    SQL deliberately avoids firing the model's ``updated_at`` on-update default.
    """
    result = db.execute(
        text("UPDATE users SET id = id WHERE id = :user_id"),
        {"user_id": user_id},
    )
    if result.rowcount != 1:
        raise LookupError(f"User {user_id} not found")
    return (
        db.query(User)
        .filter(User.id == user_id)
        .populate_existing()
        .one()
    )


__all__ = ["acquire_user_settings_write_lock"]
