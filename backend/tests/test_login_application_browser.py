import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "login_application_browser.py"
SPEC = importlib.util.spec_from_file_location("login_application_browser", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
login_helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(login_helper)


def test_interactive_login_requires_a_graphical_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    with pytest.raises(RuntimeError, match="visible graphical display"):
        login_helper._require_interactive_display()


def test_interactive_login_accepts_x11_display(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    login_helper._require_interactive_display()


def test_interactive_login_forces_visible_browser_even_when_default_is_headless(monkeypatch):
    captured = {}
    expected_runtime = object()
    fake_playwright = object()

    async def fake_launch_retainable_browser(playwright, **kwargs):
        captured["playwright"] = playwright
        captured.update(kwargs)
        return expected_runtime

    monkeypatch.setattr(
        login_helper,
        "get_settings",
        lambda: SimpleNamespace(
            application_browser_profile_dir="browser_profiles/jobtomatik-operator",
            application_browser_headless=True,
            application_browser_executable="",
        ),
    )
    monkeypatch.setattr(
        login_helper,
        "launch_retainable_browser",
        fake_launch_retainable_browser,
    )

    runtime = asyncio.run(login_helper._launch_interactive_browser(fake_playwright))

    assert runtime is expected_runtime
    assert captured["playwright"] is fake_playwright
    assert captured["headless"] is False
    assert captured["profile_dir"] == Path("browser_profiles/jobtomatik-operator")
    assert captured["executable_path"] == ""
