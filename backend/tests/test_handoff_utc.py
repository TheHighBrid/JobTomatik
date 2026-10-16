from datetime import datetime, timedelta, timezone

import pytest

from app.services.handoff_session import (
    HandoffSessionExpired, claim_handoff_session, heartbeat_handoff_session,
    issue_handoff_session, verify_handoff_lease,
)
from app.services.handoff_recovery import recover_handoff_lease
from tests.test_handoff_sessions import make_records


@pytest.mark.parametrize("offset", [0, 5, -4])
def test_postgres_aware_handoff_claim_heartbeat_and_lease_recovery(db_session, offset):
    user, _, application, review = make_records(db_session)
    issued = issue_handoff_session(db_session, application, review, browser_provider="local_cdp")
    session = issued.session
    zone = timezone(timedelta(hours=offset))
    session.expires_at = (datetime.now(timezone.utc) + timedelta(minutes=20)).astimezone(zone)
    claimed = claim_handoff_session(db_session, session, user_id=user.id, resume_token=issued.resume_token)
    session.lease_expires_at = session.lease_expires_at.replace(tzinfo=timezone.utc).astimezone(zone)
    heartbeat_handoff_session(db_session, session, user_id=user.id, lease_token=claimed.lease_token)
    session.lease_expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).astimezone(zone)
    recovered = recover_handoff_lease(db_session, session, user_id=user.id)
    verify_handoff_lease(db_session, session, user_id=user.id, lease_token=recovered.lease_token)
    assert recovered.lease_token != claimed.lease_token
    session.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).astimezone(zone)
    with pytest.raises(HandoffSessionExpired):
        verify_handoff_lease(db_session, session, user_id=user.id, lease_token=recovered.lease_token)
