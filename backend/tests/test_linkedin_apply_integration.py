from types import SimpleNamespace

from app.services.linkedin_apply_integration import _needs_linkedin_reresolution


def test_legacy_linkedin_job_requires_reresolution():
    job = SimpleNamespace(
        url="https://www.linkedin.com/jobs/view/example-role-123/",
        raw_data={"application_method": "unsupported_job_board"},
    )

    assert _needs_linkedin_reresolution(job) is True


def test_direct_employer_job_does_not_require_reresolution():
    job = SimpleNamespace(
        url="https://jobs.rbc.com/ca/en/hvhapply?jobSeqNo=example",
        raw_data={"application_method": "external_url"},
    )

    assert _needs_linkedin_reresolution(job) is False
