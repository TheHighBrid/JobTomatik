from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _active_env_lines() -> set[str]:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    return {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_target_resolution_handoff_is_nonblocking_by_default():
    active_lines = _active_env_lines()

    assert "APPLICATION_TARGET_HUMAN_WAIT_SECONDS=0" in active_lines
    assert "APPLICATION_TARGET_HUMAN_WAIT_SECONDS=180" not in active_lines


def test_compose_serializes_the_shared_application_browser_profile():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    command = (
        "command: celery -A app.celery_app worker --loglevel=info "
        "--pool=solo --concurrency=1 -Q celery,scraping,applications,followup"
    )

    assert command in compose


def test_sensitive_browser_runtime_directories_are_gitignored():
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "browser_profiles/" in ignored
    assert "handoff_sessions/" in ignored


def test_backend_dependency_manifest_has_no_duplicate_entries():
    requirements = [
        line.strip()
        for line in (REPO_ROOT / "backend" / "requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert len(requirements) == len(set(requirements))
