from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BROWSER = ROOT / "backend" / "scripts" / "start_android_browser_cdp.sh"


def test_browser_launcher_discovers_display_for_background_termux_commands():
    source = BROWSER.read_text(encoding="utf-8")

    assert "resolve_display()" in source
    assert "JOBTOMATIK_ANDROID_DISPLAY" in source
    assert "CALLER_DISPLAY" in source
    assert "/proc/[0-9]*/environ" in source
    assert ".X11-unix" in source
    assert "ANDROID_BROWSER_DISPLAY_RESOLVED" in source


def test_browser_launcher_does_not_hardcode_colon_zero_as_background_fallback():
    source = BROWSER.read_text(encoding="utf-8")

    assert 'DISPLAY_VALUE="${DISPLAY:-:0}"' not in source
    assert 'export DISPLAY="$DISPLAY_VALUE"' in source
    assert "ANDROID_BROWSER_DISPLAY_UNAVAILABLE" in source
