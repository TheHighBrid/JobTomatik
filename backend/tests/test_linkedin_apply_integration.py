from types import SimpleNamespace

from app.services.linkedin_apply_integration import (
    _is_discovery_only_result,
    _needs_linkedin_reresolution,
)


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


def test_discovery_only_result_keeps_existing_review_open():
    result = {
        "error": "LinkedIn listing pages are discovery-only",
        "log": [{"action": "unsupported_job_board"}],
    }

    assert _is_discovery_only_result(result) is True


def test_employer_form_result_allows_stale_review_cleanup():
    result = {
        "error": "Required application fields need review before the ATS flow can continue.",
        "log": [
            {"action": "external_apply_link_found"},
            {"action": "external_apply_navigated"},
            {"action": "ats_adapter_detected"},
        ],
    }

    assert _is_discovery_only_result(result) is False
