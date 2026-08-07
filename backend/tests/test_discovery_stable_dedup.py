from __future__ import annotations

from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.discovery_dedup import partition_new_discovery_jobs
from app.services.discovery_pipeline import persist_discovery_results
from app.services.job_identity import (
    canonical_job_url,
    job_identity_key,
    provider_posting_id,
    stable_external_id,
)


def _linkedin_job(url: str, external_id: str) -> dict:
    return {
        "external_id": external_id,
        "title": "Senior Machine Learning Engineer (Fraud)",
        "company": "Affirm",
        "location": "Ottawa, ON",
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "CAD",
        "job_type": "full_time",
        "description": "Build machine learning systems for fraud detection.",
        "requirements": "Machine learning and fraud risk experience.",
        "url": url,
        "source": "linkedin",
        "raw_data": {
            "application_method": "unsupported_job_board",
            "reason": "LinkedIn listing pages are discovery-only",
        },
    }


def test_linkedin_tracking_variants_share_one_provider_identity():
    first = _linkedin_job(
        "https://www.linkedin.com/jobs/view/senior-machine-learning-engineer-fraud-at-affirm-4442675569/?prefId=AAA&trackingId=ONE",
        "volatile-one",
    )
    second = _linkedin_job(
        "https://ca.linkedin.com/jobs/view/senior-machine-learning-engineer-fraud-at-affirm-4442675569/?refId=BBB&trackingId=TWO",
        "volatile-two",
    )

    assert provider_posting_id("linkedin", first["url"]) == "4442675569"
    assert canonical_job_url("linkedin", first["url"]) == (
        "https://www.linkedin.com/jobs/view/4442675569"
    )
    assert stable_external_id(first) == "linkedin:4442675569"
    assert stable_external_id(second) == "linkedin:4442675569"
    assert job_identity_key(first) == job_identity_key(second)


def test_repeated_search_rebinds_to_existing_linkedin_job(auth_client, db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    user.job_preferences = {
        "preferred_titles": ["Machine Learning Engineer"],
        "skills": ["fraud", "machine learning"],
        "preferred_locations": ["Ottawa"],
    }
    existing = Job(
        external_id="legacy-tracking-hash-one",
        title="Senior Machine Learning Engineer (Fraud)",
        company="Affirm",
        location="Ottawa, ON",
        description="Build machine learning systems for fraud detection.",
        requirements="Machine learning and fraud risk experience.",
        url=(
            "https://www.linkedin.com/jobs/view/"
            "senior-machine-learning-engineer-fraud-at-affirm-4442675569/"
            "?prefId=AAA&trackingId=ONE"
        ),
        source=JobSource.linkedin,
        status=JobStatus.rejected,
        raw_data={"application_method": "unsupported_job_board"},
    )
    db_session.add(existing)
    db_session.commit()

    repeated = _linkedin_job(
        "https://ca.linkedin.com/jobs/view/senior-machine-learning-engineer-fraud-at-affirm-4442675569/?refId=BBB&trackingId=TWO",
        "legacy-tracking-hash-two",
    )
    prepared, collapsed = partition_new_discovery_jobs(db_session, [repeated])

    assert collapsed == 0
    assert len(prepared) == 1
    assert prepared[0]["external_id"] == existing.external_id
    assert prepared[0]["url"] == "https://www.linkedin.com/jobs/view/4442675569"

    stats = persist_discovery_results(
        db_session,
        user,
        prepared,
        keywords="fraud machine learning",
    )
    db_session.commit()
    db_session.refresh(existing)

    assert stats["saved"] == 0
    assert stats["duplicates"] == 1
    assert existing.status == JobStatus.rejected
    assert db_session.query(Job).count() == 1


def test_same_run_tracking_variants_are_collapsed_before_persistence(db_session):
    first = _linkedin_job(
        "https://www.linkedin.com/jobs/view/4442675569?trackingId=ONE",
        "volatile-one",
    )
    second = _linkedin_job(
        "https://www.linkedin.com/jobs/view/4442675569?trackingId=TWO",
        "volatile-two",
    )

    prepared, collapsed = partition_new_discovery_jobs(db_session, [first, second])

    assert len(prepared) == 1
    assert collapsed == 1
    assert prepared[0]["external_id"] == "linkedin:4442675569"
    assert prepared[0]["url"] == "https://www.linkedin.com/jobs/view/4442675569"
