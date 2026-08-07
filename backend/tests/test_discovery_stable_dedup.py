from __future__ import annotations

from app.models.job import Job, JobSource, JobStatus
from app.services.discovery_dedup import partition_new_discovery_jobs
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


def test_repeated_search_does_not_reinsert_existing_linkedin_job(db_session):
    existing = Job(
        external_id="legacy-tracking-hash-one",
        title="Senior Machine Learning Engineer (Fraud)",
        company="Affirm",
        location="Ottawa, ON",
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
    new_jobs, duplicates = partition_new_discovery_jobs(db_session, [repeated])

    db_session.refresh(existing)
    assert new_jobs == []
    assert duplicates == 1
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

    new_jobs, duplicates = partition_new_discovery_jobs(db_session, [first, second])

    assert len(new_jobs) == 1
    assert duplicates == 1
    assert new_jobs[0]["external_id"] == "linkedin:4442675569"
    assert new_jobs[0]["url"] == "https://www.linkedin.com/jobs/view/4442675569"
