from pathlib import Path

from app.services.browser_runtime import _chromium_environment, chromium_stability_args


REPO_ROOT = Path(__file__).resolve().parents[2]


def _active_env_lines() -> set[str]:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    return {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_target_resolution_allows_a_fifteen_minute_operator_window():
    active_lines = _active_env_lines()

    assert "APPLICATION_TARGET_HUMAN_WAIT_SECONDS=900" in active_lines
    assert "APPLICATION_TARGET_HUMAN_WAIT_SECONDS=0" not in active_lines
    assert "APPLICATION_TARGET_HUMAN_WAIT_SECONDS=180" not in active_lines


def test_retained_browser_uses_software_rendering_stability_flags():
    args = chromium_stability_args()

    assert "--disable-gpu" in args
    assert "--disable-gpu-compositing" in args
    assert "--disable-gpu-rasterization" in args
    assert "--disable-webgl" in args
    assert any(
        arg.startswith("--disable-features=")
        and "Vulkan" in arg
        and "UseSkiaRenderer" in arg
        for arg in args
    )


def test_compose_serializes_the_shared_application_browser_profile():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    command = (
        "command: celery -A app.celery_app worker --loglevel=info "
        "--pool=solo --concurrency=1 -Q celery,scraping,applications,followup"
    )

    assert command in compose


def test_compose_published_ports_default_to_loopback_only():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    for port in (5432, 6379, 8000, 3000):
        assert f'"127.0.0.1:{port}:{port}"' in compose
        assert f'"{port}:{port}"' not in compose.replace(
            f'"127.0.0.1:{port}:{port}"',
            "",
        )


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


def test_chromium_stability_flags_disable_software_3d_crash_paths():
    args = chromium_stability_args()

    assert "--disable-gpu" in args
    assert "--disable-software-rasterizer" in args
    assert "--disable-3d-apis" in args
    assert any(
        argument.startswith("--disable-features=") and "WebGPU" in argument
        for argument in args
    )


def test_chromium_environment_drops_invalid_dbus_address(monkeypatch):
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "autolaunch:")

    assert "DBUS_SESSION_BUS_ADDRESS" not in _chromium_environment()


def test_chromium_environment_preserves_valid_dbus_address(monkeypatch):
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")

    assert (
        _chromium_environment()["DBUS_SESSION_BUS_ADDRESS"]
        == "unix:path=/run/user/1000/bus"
    )
