from datetime import datetime, timedelta

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewTask,
)
from app.models.intelligence import AgentRun
from app.models.job import Job, JobSource, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.autonomous_material_verification import generate_autonomy_verified_material
from app.services.day32_observability import (
    DAY32_OBSERVABILITY_VERSION,
    build_day32_observability_report,
    sync_day32_operational_notifications,
)
from app.services.operational_observability import DIGEST_KIND, INCIDENT_KIND


def _user(db_session, email="day32@example.test"):
    user = User(
        email=email,
        hashed_password="day32-test-hash",
        full_name="Day 32 Operator",
        profile_data={
            "current_role": "Fraud Analyst",
            "years_experience": "4",
            "employment_history": "Example Bank | Fraud Analyst | Reviewed suspicious transactions",
            "key_achievements": "Maintained audit-ready case documentation",
        },
        job_preferences={"skills": ["AML", "Fraud Investigation"]},
    )
    db_session.add(user)
    db_session.flush()
    return user


def _job(db_session, suffix: str, *, platform="lever"):
    if platform == "lever":
        url = f"https://jobs.lever.co/example/{suffix}"
        source = JobSource.lever
    else:
        url = f"https://boards.greenhouse.io/example/jobs/{suffix}"
        source = JobSource.greenhouse
    job = Job(
        external_id=f"day32-job-{suffix}",
        title="Fraud Investigator",
        company="Example Bank",
        location="Ottawa, ON",
        description="Investigate suspicious transactions and document findings.",
        requirements="Fraud investigation, AML, case documentation.",
        url=url,
        source=source,
        status=JobStatus.approved,
        skills=["Fraud Investigation", "AML"],
        relevance_score=0.9,
        raw_data={"selected_apply_url": url},
    )
    db_session.add(job)
    db_session.flush()
    return job


def _application(
    db_session,
    user: User,
    job: Job,
    suffix: str,
    *,
    state: str = ApplicationAutomationState.needs_review.value,
    created_at: datetime | None = None,
):
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=state,
        source_listing_url=job.url,
        application_target_url=job.url,
        submission_attempt_count=1,
        last_submission_attempt_at=created_at,
        submission_idempotency_key=f"day32:{user.id}:{suffix}",
        created_at=created_at,
    )
    db_session.add(application)
    db_session.flush()
    return application


def _review(db_session, application: Application, reason: ManualReviewReason, when: datetime):
    db_session.add(ManualReviewTask(
        application_id=application.id,
        reason_code=reason.value,
        summary=f"Synthetic {reason.value}",
        details={"synthetic_day32": True},
        blocking_url=application.application_target_url,
        created_at=when,
    ))


def _discovery_failure(db_session, user: User, when: datetime, source="jobbank"):
    db_session.add(AgentRun(
        user_id=user.id,
        objective="Synthetic Day 32 discovery failure",
        status="completed",
        autonomy_level="reviewed",
        risk_level="low",
        requires_approval=False,
        plan=[],
        run_context={"pipeline": "public_ats_discovery_v1"},
        result={
            "saved": 0,
            "source_diagnostics": [{
                "source": source,
                "kind": "broad_board",
                "status": "failed",
                "result_count": 0,
                "target": None,
                "error_code": "synthetic_source_failure",
            }],
        },
        started_at=when,
        completed_at=when,
        created_at=when,
    ))


def test_day32_report_covers_required_incident_taxonomy_and_actions(db_session, tmp_path):
    now = datetime.utcnow().replace(microsecond=0)
    user = _user(db_session)

    uncertain_job = _job(db_session, "uncertain")
    uncertain = _application(
        db_session,
        user,
        uncertain_job,
        "uncertain",
        state=ApplicationAutomationState.submission_uncertain.value,
        created_at=now - timedelta(minutes=5),
    )

    for index in range(3):
        job = _job(db_session, f"validation-{index}")
        application = _application(
            db_session,
            user,
            job,
            f"validation-{index}",
            created_at=now - timedelta(minutes=10 + index),
        )
        _review(
            db_session,
            application,
            ManualReviewReason.validation_error,
            now - timedelta(minutes=10 + index),
        )

    for index in range(3):
        job = _job(db_session, f"login-{index}", platform="greenhouse")
        application = _application(
            db_session,
            user,
            job,
            f"login-{index}",
            created_at=now - timedelta(minutes=20 + index),
        )
        _review(
            db_session,
            application,
            ManualReviewReason.login_required,
            now - timedelta(minutes=20 + index),
        )

    for minutes in (30, 20, 10):
        _discovery_failure(db_session, user, now - timedelta(minutes=minutes))

    resume = tmp_path / "day32-resume.pdf"
    resume.write_bytes(b"canonical-resume-v1")
    user.resume_path = str(resume)
    user.resume_filename = resume.name
    material_job = _job(db_session, "material-drift")
    material_app = _application(
        db_session,
        user,
        material_job,
        "material-drift",
        state=ApplicationAutomationState.preparing.value,
        created_at=now - timedelta(minutes=2),
    )
    material, verification = generate_autonomy_verified_material(
        db_session,
        material_app,
        user,
        material_job,
    )
    assert verification["requires_manual_review"] is False
    db_session.flush()
    material.content += "\nPost-verification mutation.\n"
    db_session.commit()

    report = build_day32_observability_report(
        db_session,
        user.id,
        failure_threshold=3,
        now=now,
    )
    codes = {item["code"] for item in report["incidents"]}

    assert "submission_uncertain" in codes
    assert "validation_failure_spike" in codes
    assert "source_breakage" in codes
    assert "login_lockout_risk" in codes
    assert "circuit_breaker_open" in codes
    assert "evidence_mismatch" in codes
    assert report["summary"]["evidence_mismatch_count"] == 1

    linked = [
        item for item in report["incidents"]
        if item.get("application_ids")
    ]
    assert linked
    for incident in linked:
        assert incident["application_links"]
        assert all(
            link["path"] == f"/applications/{link['application_id']}"
            for link in incident["application_links"]
        )
        assert len(incident["recovery_actions"]) >= 2

    mismatch = next(item for item in report["incidents"] if item["code"] == "evidence_mismatch")
    assert mismatch["application_ids"] == [material_app.id]
    assert mismatch["recovery_path"] == f"/applications/{material_app.id}"
    assert "material_content_changed" in mismatch["blockers"]
    assert report["day32_contract"] == {
        "version": DAY32_OBSERVABILITY_VERSION,
        "adapter_success_dashboard": True,
        "source_success_dashboard": True,
        "submission_uncertain_alert": True,
        "repeated_validation_failure_alert": True,
        "source_breakage_alert": True,
        "lockout_risk_alert": True,
        "circuit_breaker_alert": True,
        "evidence_mismatch_alert": True,
        "exact_application_links": True,
        "recovery_actions": True,
        "routine_successes_digest_only": True,
    }
    assert uncertain.id in next(
        item["application_ids"]
        for item in report["incidents"]
        if item["code"] == "submission_uncertain"
    )


def test_day32_notification_preserves_exact_links_actions_and_deduplicates(db_session, tmp_path):
    now = datetime(2026, 8, 24, 12, 0, 0)
    user = _user(db_session, "day32-notifications@example.test")
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"resume-before-drift")
    user.resume_path = str(resume)
    user.resume_filename = resume.name
    job = _job(db_session, "notify-evidence")
    application = _application(
        db_session,
        user,
        job,
        "notify-evidence",
        state=ApplicationAutomationState.preparing.value,
        created_at=now - timedelta(minutes=1),
    )
    material, verification = generate_autonomy_verified_material(
        db_session,
        application,
        user,
        job,
    )
    assert verification["requires_manual_review"] is False
    material.content += "\nDrift after verification.\n"
    db_session.commit()

    first = sync_day32_operational_notifications(
        db_session,
        user.id,
        failure_threshold=3,
        now=now,
    )
    db_session.commit()
    assert first["notifications_created"] >= 1
    assert first["contract"]["routine_successes_digest_only"] is True

    row = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.type == NotificationType.system,
        )
        .all()
    )
    incident = next(
        item for item in row
        if (item.data or {}).get("kind") == INCIDENT_KIND
        and (item.data or {}).get("code") == "evidence_mismatch"
    )
    assert incident.data["application_links"] == [{
        "application_id": application.id,
        "path": f"/applications/{application.id}",
    }]
    assert incident.data["recovery_path"] == f"/applications/{application.id}"
    assert len(incident.data["recovery_actions"]) == 3
    assert incident.data["observability_version"] == DAY32_OBSERVABILITY_VERSION

    second = sync_day32_operational_notifications(
        db_session,
        user.id,
        failure_threshold=3,
        now=now + timedelta(minutes=10),
    )
    db_session.commit()
    assert second["notifications_created"] == 0
    assert second["notifications_deduplicated"] >= 1


def test_day32_routine_activity_is_digest_only_once_per_utc_day(db_session):
    now = datetime(2026, 8, 24, 12, 0, 0)
    user = _user(db_session, "day32-digest@example.test")
    for minutes in (30, 20):
        db_session.add(AgentRun(
            user_id=user.id,
            objective="Synthetic successful discovery",
            status="completed",
            autonomy_level="reviewed",
            risk_level="low",
            requires_approval=False,
            plan=[],
            run_context={"pipeline": "public_ats_discovery_v1"},
            result={
                "saved": 2,
                "source_diagnostics": [{
                    "source": "jobbank",
                    "kind": "broad_board",
                    "status": "success",
                    "result_count": 2,
                    "target": None,
                    "error_code": None,
                }],
            },
            started_at=now - timedelta(minutes=minutes),
            completed_at=now - timedelta(minutes=minutes),
            created_at=now - timedelta(minutes=minutes),
        ))
    db_session.commit()

    first = sync_day32_operational_notifications(db_session, user.id, now=now)
    db_session.commit()
    second = sync_day32_operational_notifications(
        db_session,
        user.id,
        now=now + timedelta(minutes=5),
    )
    db_session.commit()

    rows = db_session.query(Notification).filter(Notification.user_id == user.id).all()
    digests = [item for item in rows if (item.data or {}).get("kind") == DIGEST_KIND]
    incidents = [item for item in rows if (item.data or {}).get("kind") == INCIDENT_KIND]
    assert first["digest_created"] is True
    assert second["digest_created"] is False
    assert len(digests) == 1
    assert incidents == []
    assert digests[0].data["activity"]["new_jobs_saved"] == 4
