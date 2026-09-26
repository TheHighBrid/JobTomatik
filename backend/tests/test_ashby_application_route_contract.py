from pathlib import Path


def test_application_route_is_preferred_and_does_not_require_reclick():
    source = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'endswith("/application")' in source
    assert 'a[href*="/application"]' in source
    assert 'iframe[src*="jobs.ashbyhq.com" i][src*="/application" i]' in source
