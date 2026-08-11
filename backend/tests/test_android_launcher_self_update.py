from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _update_case(wrapper: str) -> str:
    return wrapper.split("update)", 1)[1].split(";;", 1)[0]


def test_android_update_reexecutes_freshly_installed_launcher_before_restart():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    update_case = _update_case(wrapper)
    active_lines = [
        line.strip()
        for line in update_case.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert "update_main" in active_lines
    assert "install_native_commands" in active_lines
    assert 'echo "JOBTOMATIK_ANDROID_LAUNCHER_REEXECUTING"' in active_lines
    assert 'exec "${JOBTOMATIK_STACK_COMMAND:-$0}" restart' in active_lines
    assert "activate_stack restart" not in active_lines

    install_index = active_lines.index("install_native_commands")
    reexec_index = active_lines.index('exec "${JOBTOMATIK_STACK_COMMAND:-$0}" restart')
    assert install_index < reexec_index


def test_android_update_documents_why_in_memory_launcher_must_not_restart_directly():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    update_case = _update_case(wrapper)

    assert "pre-update shell" in update_case
    assert "previous" in update_case
    assert "Re-exec the freshly installed launcher" in update_case
