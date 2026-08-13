from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _qualify_case(wrapper: str) -> str:
    return wrapper.split("  qualify)\n", 1)[1].split("    ;;\n", 1)[0]


def test_android_direct_qualification_cli_is_retired():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    qualify = _qualify_case(wrapper)

    assert "JOBTOMATIK_DIRECT_QUALIFICATION_RETIRED" in qualify
    assert "authenticated Shadow Campaign Center 4-hour start" in qualify
    assert "run_shadow_qualification" not in wrapper
    assert "JOBTOMATIK_SHADOW_CANARY_USER_ID" not in wrapper
    assert "run_shadow_qualification_canary.py" not in wrapper


def test_retired_qualification_cli_performs_no_runtime_or_database_work():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    qualify = _qualify_case(wrapper)

    assert "run_runtime_acceptance" not in qualify
    assert "run_stack_foreground" not in qualify
    assert "run_frontend_guard" not in qualify
    assert "proot-distro" not in qualify
    assert "--user-id" not in qualify
