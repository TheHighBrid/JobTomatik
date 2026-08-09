from datetime import datetime, timedelta

from app.models.application import Application, ApplicationAutomationState
from app.models.intelligence import AgentRun
from app.models.job import Job
from app.models.material import ApplicationMaterial
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.operational_observability import (
    DIGEST_KIND,
    INCIDENT_KIND,
    build_operational_observability_report,
    build_source_health_report,
    sync_operational_notifications,
)


def _user(db_session, email="observability@example.test"):
    user = User(email=email, hashed_password="test-hash", full_name="Reliability User")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _discovery_run(db_session, user, now, *, source="linkedin", status="failed", count=0, saved=0):
    run = AgentRun(
        user_id=user.id,
        objective="Synthetic discovery observability run",
        status="completed",
        autonomy_level="reviewed",
        risk_level="low",
        requires_approval=False,
        plan=[],
        run_context={"pipeline": "public_ats_discovery_v1"},
        result={
            "saved": saved,
            "source_diagnostics": [
                {
                    "source": source,
                    "kind": "broad_board",
                    "status": status,
                    "result_count": count,
                    "target": None,
                    "error_code": "syntheticerror" if status == "failed" else None,
                }
            ],
        },
        started_at=now,
        completed_at=now,
        created_at=now,
    )
    db_session.add(run)
    db_session.flush()
    return run


def test_source_health_detects_consecutive_breakage(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    user = _user(db_session)
    for minutes in (30, 20, 10):
        _discovery_run(db_session, user, now - timedelta(minutes=minutes))
    db_session.commit()

    report = build_source_health_report(
        db_session,
        user.id,
        failure_threshold=3,
        now=now,
    )

    source = report["sources"][0]
    assert source["source"] == "linkedin"
    assert source["status"] == "critical"
    assert source["consecutive_failures"] == 3
    assert source["failed_observations"] == 3
    assert source["error_counts"] == {"syntheticerror": 3}
    assert report["alerts"][0]["code"] == "source_breakage"
    assert report["alerts"][0]["recovery_path"] == "/adapter-health"


def test_source_health_warns_on_repeated_zero_results(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    user = _user(db_session, "zero-results@example.test")
    for minutes in (30, 20, 10):
        _discovery_run(
            db_session,
            user,
            now - timedelta(minutes=minutes),
            source="jobbank",
            status="success",
            count=0,
        )
    db_session.commit()

    report = build_source_health_report(
        db_session,
        user.id,
        failure_threshold=3,
        now=now,
    )
    source = report["sources"][0]
    assert source["status"] == "degraded"
    assert source["success_rate"] == 1.0
    assert source["zero_result_observations"] == 3
    assert report["alerts"][0]["code"] == "source_zero_results"
    assert report["alerts"][0]["recovery_path"] == "/scheduler"


def test_source_health_is_account_scoped(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    first = _user(db_session, "first-observability@example.test")
    second = _user(db_session, "second-observability@example.test")
    for minutes in (30, 20, 10):
        _discovery_run(db_session, first, now - timedelta(minutes=minutes))
    db_session.commit()

    report = build_source_health_report(
        db_session,
        second.id,
        failure_threshold=3,
        now=now,
    )
    assert report["run_count"] == 0
    assert report["sources"] == []
    assert report["alerts"] == []


def test_operational_notifications_are_deduplicated_and_digest_once_per_utc_day(db_session):
    # Fixed midday UTC keeps the second sync in the same daily-digest bucket.
    now = datetime(2026, 7, 16, 12, 0, 0)
    user = _user(db_session, "digest@example.test")
    for minutes in (30, 20, 10):
        _discovery_run(
            db_session,
            user,
            now - timedelta(minutes=minutes),
            saved=2,
        )
    db_session.commit()

    first = sync_operational_notifications(
        db_session,
        user.id,
        failure_threshold=3,
        now=now,
    )
    db_session.commit()

    notifications = db_session.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.type == NotificationType.system,
    ).all()
    incident_rows = [item for item in notifications if (item.data or {}).get("kind") == INCIDENT_KIND]
    digest_rows = [item for item in notifications if (item.data or {}).get("kind") == DIGEST_KIND]

    assert first["incidents_detected"] == 1
    assert first["notifications_created"] == 1
    assert first["digest_created"] is True
    assert len(incident_rows) == 1
    assert len(digest_rows) == 1
    assert incident_rows[0].data["recovery_path"] == "/adapter-health"
    assert digest_rows[0].data["activity"]["new_jobs_saved"] == 6

    second = sync_operational_notifications(
        db_session,
        user.id,
        failure_threshold=3,
        now=now + timedelta(minutes=10),
    )
    db_session.commit()
    assert second["notifications_created"] == 0
    assert second["notifications_deduplicated"] == 1
    assert second["digest_created"] is False
    assert db_session.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.type == NotificationType.system,
    ).count() == 2


def test_material_needs_review_is_visible_as_integrity_incident(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    user = _user(db_session, "material-observability@example.test")
    job = Job(
        external_id="observability-material-job",
        title="Risk Analyst",
        company="Example Employer",
        url="https://example.test/jobs/1",
    )
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        automation_state=ApplicationAutomationState.needs_review.value,
        submission_idempotency_key=f"observability-material:{user.id}",
        created_at=now,
    )
    db_session.add(application)
    db_session.flush()
    db_session.add(ApplicationMaterial(
        user_id=user.id,
        application_id=application.id,
        material_type="cover_letter",
        version=1,
        status="needs_review",
        content="Review required",
        claims=[],
        warnings=["missing evidence"],
        source_snapshot={},
        created_at=now,
    ))
    db_session.commit()

    report = build_operational_observability_report(db_session, user.id, now=now)
    incident = next(item for item in report["incidents"] if item["code"] == "material_integrity_review")
    assert incident["application_ids"] == [application.id]
    assert incident["recovery_path"] == f"/applications/{application.id}"
    assert report["invariants"]["cannot_authorize_submission"] is True
    assert report["invariants"]["cannot_change_adapter_maturity"] is True


def test_observability_api_is_account_scoped_and_refresh_is_nonconsequential(auth_client, db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    now = datetime.utcnow().replace(microsecond=0)
    for minutes in (30, 20, 10):
        _discovery_run(db_session, user, now - timedelta(minutes=minutes))
    db_session.commit()

    report = auth_client.get("/api/adapter-health/observability", params={"failure_threshold": 3})
    assert report.status_code == 200
    payload = report.json()
    assert payload["summary"]["incident_count"] >= 1
    assert payload["invariants"] == {
        "read_only_report": True,
        "cannot_change_adapter_maturity": True,
        "cannot_authorize_submission": True,
        "cannot_send_recruiter_outreach": True,
    }

    refresh = auth_client.post("/api/adapter-health/observability/notifications/refresh")
    assert refresh.status_code == 200
    assert refresh.json()["notifications_created"] >= 1
    assert db_session.query(Application).filter(Application.user_id == user.id).count() == 0
