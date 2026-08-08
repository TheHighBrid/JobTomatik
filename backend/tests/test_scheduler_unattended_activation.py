from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.scheduler_policy import SCHEDULER_POLICY_VERSION
from app.services.unattended_policy import (
    REQUIRED_SCHEDULER_POLICY_VERSION,
    evaluate_unattended_job_policy,
)


def test_scheduler_and_unattended_policy_versions_cannot_drift():
    assert REQUIRED_SCHEDULER_POLICY_VERSION == SCHEDULER_POLICY_VERSION


def test_legacy_scheduler_flags_fail_closed_at_shared_unattended_gate(db_session):
    user = User(
        email="legacy-unattended@example.test",
        hashed_password="test-hash",
        automation_settings={
            # These historical values may have originated from old true defaults.
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "dry_run_mode": False,
            "autopilot_enabled_platforms": ["lever"],
        },
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    job = Job(
        external_id="legacy-policy-job",
        title="Risk analyst",
        company="Example Co",
        location="ottawa, ontario",
        salary_min=90000,
        seniority="mid",
        source=JobSource.lever,
        status=JobStatus.queued,
        url="https://jobs.lever.co/example/job-1",
        raw_data={"language": "english", "requires_sponsorship": False},
    )

    decision = evaluate_unattended_job_policy(db_session, user, job)
    assert decision.allowed is False
    assert decision.code == "scheduler_policy_upgrade_required"
    assert decision.metadata["current_scheduler_policy_version"] is None
    assert decision.metadata["required_scheduler_policy_version"] == SCHEDULER_POLICY_VERSION
