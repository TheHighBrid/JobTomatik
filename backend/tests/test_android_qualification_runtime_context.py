from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _qualification_function(wrapper: str) -> str:
    return wrapper.split("run_shadow_qualification() {", 1)[1].split("\n}\n", 1)[0]


def test_android_shadow_qualification_runs_from_backend_runtime_root():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    qualification = _qualification_function(wrapper)

    assert "cd '$PROOT_REPO/backend'" in qualification
    assert ".venv/bin/python scripts/run_shadow_qualification_canary.py" in qualification
    assert "cd '$PROOT_REPO';" not in qualification
    assert "backend/.venv/bin/python backend/scripts/run_shadow_qualification_canary.py" not in qualification


def test_android_shadow_qualification_keeps_managed_runtime_identity_context():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    qualification = _qualification_function(wrapper)

    assert "JOBTOMATIK_RUNTIME_MODE=android_managed" in qualification
    assert "JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE'" in qualification
