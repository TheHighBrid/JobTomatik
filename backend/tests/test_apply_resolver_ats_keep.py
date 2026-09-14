from app.services.apply_resolver import (
    extract_application_method_from_html,
    is_hosted_ats_url,
)


LEVER_POSTING = (
    "https://jobs.lever.co/magnetforensics/39181882-5eae-41c6-b494-c3d6791c978b"
)


def test_hosted_ats_url_detects_lever_and_greenhouse():
    assert is_hosted_ats_url(LEVER_POSTING) is True
    assert is_hosted_ats_url("https://job-boards.greenhouse.io/gitlab/jobs/8705017002") is True
    assert is_hosted_ats_url("https://www.jobbank.gc.ca/jobsearch/jobposting/50112647") is False
    assert is_hosted_ats_url("https://forces.ca/en/paid-education/") is False


def test_html_extractor_keeps_lever_posting_instead_of_board_root():
    html = """
    <html><body>
      <a href="https://jobs.lever.co/magnetforensics">Jobs</a>
      <a href="https://lever.co/jobs.html">Lever jobs</a>
      <a href="/magnetforensics/39181882-5eae-41c6-b494-c3d6791c978b/apply">Apply</a>
    </body></html>
    """
    result = extract_application_method_from_html(LEVER_POSTING, html)
    assert result["application_method"] == "external_url"
    assert result["selected_apply_url"] == LEVER_POSTING
    assert "hosted ATS" in result["reason"]
