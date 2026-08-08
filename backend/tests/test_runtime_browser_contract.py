import asyncio
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

from app.config import Settings
from app.services import browser_runtime
from app.services.browser_navigation import wait_for_external_application_target
from app.services.browser_runtime import _chromium_environment, chromium_stability_args


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
    assert "APPLICATION_TARGET_HUMAN_WAIT_SECONDS=900" not in active_lines
    assert "APPLICATION_TARGET_HUMAN_WAIT_SECONDS=180" not in active_lines


def test_unresolved_target_resolution_returns_promptly_under_default_profile(monkeypatch):
    monkeypatch.delenv("APPLICATION_TARGET_HUMAN_WAIT_SECONDS", raising=False)
    settings = Settings(_env_file=None)
    source_url = "https://www.linkedin.com/jobs/view/1234567890"

    class UnresolvedPage:
        def __init__(self):
            self.url = source_url
            self.context = SimpleNamespace(pages=[self])
            self.wait_calls = 0

        async def wait_for_timeout(self, _milliseconds):
            self.wait_calls += 1

    page = UnresolvedPage()
    log = []
    started = monotonic()
    target = asyncio.run(
        wait_for_external_application_target(
            page,
            source_url,
            timeout_seconds=settings.application_target_human_wait_seconds,
            log=log,
        )
    )
    elapsed = monotonic() - started

    assert settings.application_target_human_wait_seconds == 0
    assert target is None
    assert page.wait_calls == 0
    assert elapsed < 0.25
    assert not any(
        item.get("action") == "application_target_human_window_started"
        for item in log
    )


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


def test_playwright_attachment_gets_fresh_budget_after_slow_cdp_startup(
    monkeypatch,
    tmp_path,
):
    class FakeLoop:
        def __init__(self):
            # Simulate CDP becoming ready after consuming 119 of its 120 seconds.
            self.now = 119.0

        def time(self):
            return self.now

    class FakeProcess:
        returncode = None

        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    class FakeLogHandle:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    loop = FakeLoop()
    attempts = []
    expected_browser = object()

    class FakeChromium:
        async def connect_over_cdp(self, endpoint, timeout):
            attempts.append((loop.time(), endpoint, timeout))
            if len(attempts) == 1:
                raise RuntimeError("CDP websocket still stabilizing")
            return expected_browser

    async def fake_sleep(seconds):
        loop.now += seconds

    monkeypatch.setattr(browser_runtime.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(browser_runtime.asyncio, "sleep", fake_sleep)

    process = FakeProcess()
    log_handle = FakeLogHandle()
    endpoint = "http://127.0.0.1:9222"
    browser = asyncio.run(
        browser_runtime._connect_playwright_over_cdp(
            SimpleNamespace(chromium=FakeChromium()),
            process,
            endpoint,
            log_handle,
            tmp_path / "chromium.log",
        )
    )

    assert browser is expected_browser
    assert len(attempts) == 2
    assert attempts[0] == (119.0, endpoint, 15_000)
    assert attempts[1] == (120.0, endpoint, 15_000)
    assert process.terminated is False
    assert log_handle.closed is False


def test_compose_serializes_the_shared_application_browser_profile():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    worker_command = (
        "exec celery -A app.celery_app worker --loglevel=info "
        "--pool=solo --concurrency=1 -Q celery,scraping,applications,followup"
    )

    # Phase 12 intentionally prepends exact-build attestation, but the worker remains
    # serialized through the same solo/concurrency=1 application browser profile.
    assert "check_runtime_identity.py --require-sensitive" in compose
    assert worker_command in compose


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
