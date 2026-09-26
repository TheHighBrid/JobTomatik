from pathlib import Path


def test_supported_host_is_ashby_jobs_host():
    adapter = Path("backend/app/services/ats_ashby.py").read_text(encoding="utf-8")
    assert 'ASHBY_JOBS_HOST = "jobs.ashbyhq.com"' in adapter
    assert "supported_hosts = (ASHBY_JOBS_HOST,)" in adapter
