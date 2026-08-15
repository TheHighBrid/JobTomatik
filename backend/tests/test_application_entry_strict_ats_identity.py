from app.services.application_entry_runtime import _strict_ats_surface


def test_strict_ats_surface_accepts_canonical_posting_identity():
    assert (
        _strict_ats_surface(
            "https://jobs.lever.co/eqbank/"
            "7ef2757a-99f9-4000-8bd6-82fc3d2bc844/apply"
        )
        == "lever"
    )
    assert (
        _strict_ats_surface(
            "https://job-boards.greenhouse.io/acme/jobs/1234567"
        )
        == "greenhouse"
    )
    assert (
        _strict_ats_surface(
            "https://jobs.ashbyhq.com/acme/"
            "123e4567-e89b-12d3-a456-426614174000/application"
        )
        == "ashby"
    )
    assert (
        _strict_ats_surface(
            "https://jobs.smartrecruiters.com/acme/"
            "744000137613800-security-engineer"
        )
        == "smartrecruiters"
    )
    assert (
        _strict_ats_surface(
            "https://jobs.smartrecruiters.com/oneclick-ui/company/acme/"
            "publication/846c9735-28eb-464c-b3aa-4c0407979e0f"
        )
        == "smartrecruiters"
    )
    assert (
        _strict_ats_surface(
            "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/Ottawa/"
            "Information-Security-Analyst_R-123/apply"
        )
        == "workday"
    )


def test_strict_ats_surface_rejects_reserved_or_malformed_identity_routes():
    rejected = [
        "https://jobs.lever.co/account/login",
        "https://jobs.lever.co/help/article",
        "https://jobs.lever.co/privacy/cookies",
        "https://jobs.lever.co/acme/not-a-posting-id",
        "https://boards.greenhouse.io/privacy?gh_jid=1234567",
        "https://app.greenhouse.io/users/sign_in?gh_jid=1234567",
        "https://job-boards.greenhouse.io/acme/jobs/privacy",
        "https://jobs.ashbyhq.com/acme/privacy",
        "https://jobs.smartrecruiters.com/oneclick-ui/company/acme/publication/privacy",
        "https://jobs.smartrecruiters.com/oneclick-ui/company/acme/publication/login",
        "https://jobs.smartrecruiters.com/acme/privacy-role",
        "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/account/login",
        "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/privacy/cookies",
    ]

    for url in rejected:
        assert _strict_ats_surface(url) is None, url
