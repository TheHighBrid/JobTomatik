from app.models.application import Application, ApplicationTargetStatus
from app.models.job import Job
from app.services.application_target import (
    initialize_application_target,
    is_listing_source,
    is_valid_application_target,
    record_application_target,
)


class FakeDB:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)


def test_linkedin_listing_is_not_treated_as_application_target():
    url = "https://ca.linkedin.com/jobs/view/bilingual-fraud-advisor-4439524897"

    assert is_listing_source(url) is True
    assert is_valid_application_target(url, url) is False


def test_direct_employer_url_initializes_as_resolved_target():
    db = FakeDB()
    job = Job(id=7, title="Fraud Advisor", company="RBC", url="https://jobs.rbc.com/ca/en/job/123")
    app = Application(id=11, job_id=7)

    target = initialize_application_target(db, app, job)

    assert target == job.url
    assert app.source_listing_url == job.url
    assert app.application_target_url == job.url
    assert app.application_target_status == ApplicationTargetStatus.resolved.value
    assert app.application_target_resolved_at is not None
    assert job.url == "https://jobs.rbc.com/ca/en/job/123"
    assert db.added[-1].event_type == "application_target_initialized"


def test_listing_stays_unresolved_until_employer_destination_is_recorded():
    db = FakeDB()
    listing = "https://ca.linkedin.com/jobs/view/bilingual-fraud-advisor-4439524897"
    job = Job(id=7, title="Fraud Advisor", company="RBC", url=listing)
    app = Application(id=11, job_id=7)

    target = initialize_application_target(db, app, job)

    assert target is None
    assert app.source_listing_url == listing
    assert app.application_target_url is None
    assert app.application_target_status == ApplicationTargetStatus.unresolved.value


def test_recording_employer_target_preserves_original_job_url():
    db = FakeDB()
    listing = "https://ca.linkedin.com/jobs/view/bilingual-fraud-advisor-4439524897"
    employer = "https://jobs.rbc.com/ca/en/job/R-000123/bilingual-fraud-advisor"
    job = Job(id=7, title="Fraud Advisor", company="RBC", url=listing)
    app = Application(
        id=11,
        job_id=7,
        source_listing_url=listing,
        application_target_status=ApplicationTargetStatus.resolving.value,
    )

    record_application_target(
        db,
        app,
        target_url=employer,
        method="human_apply_click",
    )

    assert job.url == listing
    assert app.source_listing_url == listing
    assert app.application_target_url == employer
    assert app.application_target_status == ApplicationTargetStatus.resolved.value
    assert app.application_target_metadata["resolution_method"] == "human_apply_click"
    assert db.added[-1].event_type == "application_target_resolved"