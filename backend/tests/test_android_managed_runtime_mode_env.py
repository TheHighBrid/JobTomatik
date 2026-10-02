from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _function_section(script: str, function_name: str) -> str:
    return script.split(f"{function_name}() {{", 1)[1].split("\n}\n", 1)[0]


def test_isolated_managed_android_processes_keep_runtime_mode():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    for function_name in ("start_api", "start_worker", "start_beat"):
        section = _function_section(manager, function_name)
        assert "nohup env -i" in section
        assert "JOBTOMATIK_RUNTIME_MODE=android_managed" in section
        assert "JOBTOMATIK_RUNTIME_REVISION=" in section
        assert "JOBTOMATIK_EXPECTED_REVISION=" in section
        assert "JOBTOMATIK_RUNTIME_ROLE=" in section


def test_managed_api_preserves_mode_required_by_native_control_boundary():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )
    api_section = _function_section(manager, "start_api")

    mode = api_section.index("JOBTOMATIK_RUNTIME_MODE=android_managed")
    revision = api_section.index("JOBTOMATIK_RUNTIME_REVISION=")
    role = api_section.index("JOBTOMATIK_RUNTIME_ROLE=api")
    uvicorn = api_section.index('"$VENV/bin/uvicorn" app.main:app')

    assert mode < uvicorn
    assert revision < uvicorn
    assert role < uvicorn
