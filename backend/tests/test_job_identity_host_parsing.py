from app.services.job_identity import canonical_employer_apply_url


def test_canonical_employer_url_rejects_embedded_host_spoofs() -> None:
    assert canonical_employer_apply_url(
        "https://evil.example/jobs.lever.co/acme/123"
    ) is None
    assert canonical_employer_apply_url(
        "https://notgreenhouse.io/boards.greenhouse.io/acme/jobs/1"
    ) is None
    assert canonical_employer_apply_url(
        "https://prefix-myworkdayjobs.com/acme/job/1"
    ) is None


def test_canonical_employer_url_accepts_real_ats_hosts() -> None:
    lever = canonical_employer_apply_url("https://jobs.lever.co/acme/abcd")
    assert lever == "https://jobs.lever.co/acme/abcd"
    workday = canonical_employer_apply_url(
        "https://acme.myworkdayjobs.com/en-US/careers/job/123"
    )
    assert workday == "https://acme.myworkdayjobs.com/en-US/careers/job/123"
    greenhouse = canonical_employer_apply_url(
        "https://boards.greenhouse.io/acme/jobs/1?gh_jid=99&utm=x"
    )
    assert greenhouse == "https://boards.greenhouse.io/acme/jobs/1?gh_jid=99"
