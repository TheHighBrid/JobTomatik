import pytest

from app.models.job import Job, JobSource, JobStatus, JobType
from app.models.user import User
from app.services import application_queue_policy as queue_policy
from app.services.application_queue_policy_runtime import build_shared_evaluator
from app.services.operations_policy import AutomationDecision


def test_production_policy_decision_does_not_proceed_without_durable_audit(
    db_session,
    monkeypatch,
):
    user = User(
        email="day30-audit-fail@example.com",
        hashed_password="not-used",
        automation_settings={
            "autopilot_allowed_roles": ["fraud analyst"],
            "autopilot_allowed_workplace_modes": ["remote"],
            "autopilot_authorized_countries": ["CA"],
            "autopilot_daily_platform_limits": {"greenhouse": 2},
        },
    )
    job = Job(
        external_id="gh-day30-audit-fail",
        title="Fraud Analyst",
        company="Acme",
        location="Remote",
        url="https://boards.greenhouse.io/acme/jobs/789",
        source=JobSource.greenhouse,
        status=JobStatus.queued,
        job_type=JobType.remote,
        raw_data={
            "remote_status": "remote",
            "requires_sponsorship": False,
            "country_code": "CA",
        },
    )
    db_session.add_all([user, job])
    db_session.flush()

    def inherited_allow(db, candidate_user, candidate_job, now=None):
        return AutomationDecision(True, "inherited_allowed", "Inherited policy passed.", {})

    monkeypatch.setattr(queue_policy, "_audit_decision", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="day30_policy_audit_persistence_failed"):
        build_shared_evaluator(inherited_allow)(db_session, user, job)
