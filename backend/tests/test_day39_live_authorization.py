from datetime import datetime, timedelta, timezone

import pytest

from app.models.application import Application
from app.models.job import Job, JobSource
from app.models.live_pilot import LivePilotAttemptReservation, LivePilotAuthorization
from app.models.user import User
from app.services.day39_live_authorization import (
    create_live_pilot_authorization,
    live_pilot_authorization_integrity_ok,
    reserve_live_pilot_attempt,
    revoke_live_pilot_authorization,
)
from app.services.day39_live_window import expected_live_window_acknowledgment


REVISION = "a" * 40
NOW = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)


def _promotion():
    return {
        "passed": True,
        "promotion_authorized": True,
        "live_window_authorized": False,
        "real_submission_authorized": False,
        "release_candidate_revision": REVISION,
        "target_adapter": "lever",
        "target_adapter_version": "1.1.0",
        "target_maturity": "certified_autonomous",
    }


def _adapter():
    return {
        "name": "lever",
        "version": "1.1.0",
        "maturity": "certified_autonomous",
        "autonomous_submission_allowed": True,
    }


def _runtime():
    return {
        "current_revision": REVISION,
        "allow_real_application_submit": False,
        "allow_real_followup_send": False,
        "global_kill_switch": False,
        "live_window_authorized": False,
    }


def _policy():
    return {
        "ready": True,
        "policy_profile": "production",
        "circuit_breaker_clear": True,
        "quiet_hours_active": False,
        "remaining_daily": 5,
        "remaining_weekly": 20,
    }


def _owner(reference="day39-owner-first-wave", cap=2):
    return {
        "approved": True,
        "approval_reference": reference,
        "approved_for_commit": REVISION,
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "max_submission_attempts": cap,
        "starts_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=6)).isoformat(),
        "acknowledgment": expected_live_window_acknowledgment(
            revision=REVISION,
            attempt_cap=cap,
        ),
    }


def _create(db, user_id, *, owner=None):
    return create_live_pilot_authorization(
        db,
        approved_by_user_id=user_id,
        promotion=_promotion(),
        adapter_state=_adapter(),
        runtime_safety=_runtime(),
        policy_state=_policy(),
        owner_request=owner or _owner(),
        now=NOW,
    )


def _seed_user_and_apps(db, count=3):
    user = User(
        email="live-window@example.com",
        hashed_password="test-hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    apps = []
    for index in range(count):
        job = Job(
            title=f"Live Pilot Role {index}",
            company=f"Employer {index}",
            url=f"https://jobs.lever.co/example/{index}",
            source=JobSource.lever,
        )
        db.add(job)
        db.flush()
        application = Application(user_id=user.id, job_id=job.id)
        db.add(application)
        db.flush()
        apps.append(application)
    return user, apps


def test_eligible_owner_request_persists_hashed_authorization_without_runtime_enablement(db_session):
    user, _apps = _seed_user_and_apps(db_session, count=1)

    record, report = _create(db_session, user.id)

    assert record is not None
    assert record.status == "approved"
    assert record.commit_sha == REVISION
    assert record.adapter == "lever"
    assert record.adapter_version == "1.1.0"
    assert record.max_submission_attempts == 2
    assert record.reserved_submission_attempts == 0
    assert live_pilot_authorization_integrity_ok(record) is True
    assert report["authorization_persisted"] is True
    assert report["live_window_authorized"] is False
    assert report["real_submission_enabled"] is False


def test_same_owner_reference_is_idempotent_only_for_identical_authority(db_session):
    user, _apps = _seed_user_and_apps(db_session, count=1)
    first, first_report = _create(db_session, user.id)
    second, second_report = _create(db_session, user.id)

    assert first is not None and second is not None
    assert second.id == first.id
    assert first_report["duplicate"] is False
    assert second_report["duplicate"] is True

    changed = _owner(cap=1)
    with pytest.raises(ValueError, match="different authority"):
        _create(db_session, user.id, owner=changed)


def test_second_overlapping_live_window_is_blocked_even_with_different_reference(db_session):
    user, _apps = _seed_user_and_apps(db_session, count=1)
    first, _ = _create(db_session, user.id)
    assert first is not None

    second, report = _create(
        db_session,
        user.id,
        owner=_owner(reference="day39-owner-second-window"),
    )

    assert second is None
    assert report["authorization_eligible"] is False
    assert "database.active_live_window_exists" in report["blockers"]


def test_integrity_tampering_invalidates_authorization(db_session):
    user, _apps = _seed_user_and_apps(db_session, count=1)
    record, _ = _create(db_session, user.id)
    assert record is not None
    assert live_pilot_authorization_integrity_ok(record) is True

    record.max_submission_attempts = 99
    db_session.flush()

    assert live_pilot_authorization_integrity_ok(record) is False


def test_attempt_slots_are_non_reclaiming_and_hard_capped(db_session):
    user, apps = _seed_user_and_apps(db_session, count=3)
    authorization, _ = _create(db_session, user.id)
    assert authorization is not None

    first = reserve_live_pilot_attempt(
        db_session,
        user_id=user.id,
        application_id=apps[0].id,
        adapter="lever",
        adapter_version="1.1.0",
        revision=REVISION,
        now=NOW + timedelta(minutes=1),
    )
    second = reserve_live_pilot_attempt(
        db_session,
        user_id=user.id,
        application_id=apps[1].id,
        adapter="lever",
        adapter_version="1.1.0",
        revision=REVISION,
        now=NOW + timedelta(minutes=2),
    )
    third = reserve_live_pilot_attempt(
        db_session,
        user_id=user.id,
        application_id=apps[2].id,
        adapter="lever",
        adapter_version="1.1.0",
        revision=REVISION,
        now=NOW + timedelta(minutes=3),
    )

    assert first["allowed"] is True and first["attempts_reserved"] == 1
    assert second["allowed"] is True and second["attempts_reserved"] == 2
    assert third == {"allowed": False, "reason": "live_pilot_attempt_cap_exhausted"}
    db_session.refresh(authorization)
    assert authorization.reserved_submission_attempts == 2
    assert db_session.query(LivePilotAttemptReservation).count() == 2


def test_retry_of_same_application_reuses_existing_slot_without_increment(db_session):
    user, apps = _seed_user_and_apps(db_session, count=1)
    authorization, _ = _create(db_session, user.id)
    assert authorization is not None

    first = reserve_live_pilot_attempt(
        db_session,
        user_id=user.id,
        application_id=apps[0].id,
        adapter="lever",
        adapter_version="1.1.0",
        revision=REVISION,
        now=NOW + timedelta(minutes=1),
    )
    retry = reserve_live_pilot_attempt(
        db_session,
        user_id=user.id,
        application_id=apps[0].id,
        adapter="lever",
        adapter_version="1.1.0",
        revision=REVISION,
        now=NOW + timedelta(minutes=2),
    )

    assert first["allowed"] is True and first["reused"] is False
    assert retry["allowed"] is True and retry["reused"] is True
    db_session.refresh(authorization)
    assert authorization.reserved_submission_attempts == 1
    assert db_session.query(LivePilotAttemptReservation).count() == 1


def test_revocation_stops_new_and_retried_attempts_without_reclaiming_slots(db_session):
    user, apps = _seed_user_and_apps(db_session, count=2)
    authorization, _ = _create(db_session, user.id)
    assert authorization is not None

    reserved = reserve_live_pilot_attempt(
        db_session,
        user_id=user.id,
        application_id=apps[0].id,
        adapter="lever",
        adapter_version="1.1.0",
        revision=REVISION,
        now=NOW + timedelta(minutes=1),
    )
    assert reserved["allowed"] is True

    revoke_live_pilot_authorization(
        db_session,
        authorization=authorization,
        reason="operator stop",
        revoked_by_user_id=user.id,
        now=NOW + timedelta(minutes=2),
    )

    new_attempt = reserve_live_pilot_attempt(
        db_session,
        user_id=user.id,
        application_id=apps[1].id,
        adapter="lever",
        adapter_version="1.1.0",
        revision=REVISION,
        now=NOW + timedelta(minutes=3),
    )
    retry = reserve_live_pilot_attempt(
        db_session,
        user_id=user.id,
        application_id=apps[0].id,
        adapter="lever",
        adapter_version="1.1.0",
        revision=REVISION,
        now=NOW + timedelta(minutes=3),
    )

    assert new_attempt == {"allowed": False, "reason": "active_live_pilot_authorization_missing"}
    assert retry["allowed"] is False
    assert retry["reason"] == "existing_reservation_not_valid_for_active_authorization"
    db_session.refresh(authorization)
    assert authorization.reserved_submission_attempts == 1
    assert authorization.authorization_metadata["reserved_attempts_reclaimed"] is False


def test_expired_or_wrong_revision_authorization_cannot_be_spent(db_session):
    user, apps = _seed_user_and_apps(db_session, count=1)
    authorization, _ = _create(db_session, user.id)
    assert authorization is not None

    wrong_revision = reserve_live_pilot_attempt(
        db_session,
        user_id=user.id,
        application_id=apps[0].id,
        adapter="lever",
        adapter_version="1.1.0",
        revision="b" * 40,
        now=NOW + timedelta(minutes=1),
    )
    expired = reserve_live_pilot_attempt(
        db_session,
        user_id=user.id,
        application_id=apps[0].id,
        adapter="lever",
        adapter_version="1.1.0",
        revision=REVISION,
        now=NOW + timedelta(hours=7),
    )

    assert wrong_revision == {"allowed": False, "reason": "active_live_pilot_authorization_missing"}
    assert expired == {"allowed": False, "reason": "active_live_pilot_authorization_missing"}


def test_ineligible_pure_readiness_never_persists_authorization(db_session):
    user, _apps = _seed_user_and_apps(db_session, count=1)
    runtime = _runtime()
    runtime["allow_real_application_submit"] = True

    record, report = create_live_pilot_authorization(
        db_session,
        approved_by_user_id=user.id,
        promotion=_promotion(),
        adapter_state=_adapter(),
        runtime_safety=runtime,
        policy_state=_policy(),
        owner_request=_owner(),
        now=NOW,
    )

    assert record is None
    assert report["authorization_eligible"] is False
    assert db_session.query(LivePilotAuthorization).count() == 0
