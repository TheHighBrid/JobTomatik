from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.certification import ReleaseAuthorization
from app.models.user import User


def _authorization(user_id: int, reference: str, suffix: str):
    now = datetime.now(timezone.utc)
    return ReleaseAuthorization(
        scope="autonomous_pilot",
        release_version="v2.00",
        commit_sha=(suffix * 40)[:40],
        approval_reference=reference,
        payload_hash=(suffix * 64)[:64],
        status="approved",
        approved_by_user_id=user_id,
        approved_at=now,
        expires_at=now + timedelta(hours=1),
        authorization_metadata={"runtime_enablement_changed": False},
    )


def test_authorization_reference_is_unique_per_owner_not_globally(db_session):
    first = User(email="auth-reference-one@example.test", hashed_password="unused")
    second = User(email="auth-reference-two@example.test", hashed_password="unused")
    db_session.add_all([first, second])
    db_session.flush()

    shared_reference = "owner:release-window-001"
    db_session.add(_authorization(first.id, shared_reference, "a"))
    db_session.add(_authorization(second.id, shared_reference, "b"))
    db_session.commit()

    assert db_session.query(ReleaseAuthorization).filter(
        ReleaseAuthorization.approval_reference == shared_reference
    ).count() == 2

    db_session.add(_authorization(first.id, shared_reference, "c"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    assert db_session.query(ReleaseAuthorization).filter(
        ReleaseAuthorization.approval_reference == shared_reference
    ).count() == 2
