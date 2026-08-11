from pathlib import Path
import subprocess


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_android_manager_uses_bash_source_for_repo_root_resolution():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(encoding="utf-8")

    assert 'SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"' in manager
    assert 'dirname -- "$SCRIPT_SOURCE"' in manager
    assert 'dirname -- "$0"' not in manager


def test_android_manager_keeps_worker_and_beat_children_of_long_lived_supervisor():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    assert "source" in wrapper
    assert "manage_android_stack.sh" in wrapper
    assert "exec sleep infinity" in wrapper


def test_android_manager_uses_runtime_revisioned_worker_hostname():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(encoding="utf-8")

    assert 'RUNTIME_REVISION_SHORT="${RUNTIME_REVISION:0:12}"' in manager
    assert 'WORKER_NODE_PREFIX="jobtomatik-android-${RUNTIME_REVISION_SHORT}@"' in manager
    assert '--hostname="jobtomatik-android-${RUNTIME_REVISION_SHORT}@%h"' in manager


def test_android_manager_requires_exact_runtime_revision_before_startup():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(encoding="utf-8")

    assert 'EXPECTED_RUNTIME_REVISION="${JOBTOMATIK_EXPECTED_REVISION:-$RUNTIME_REVISION}"' in manager
    assert 'if [[ "$EXPECTED_RUNTIME_REVISION" != "$RUNTIME_REVISION" ]]' in manager
    assert "JOBTOMATIK_EXPECTED_REVISION must equal the Android runtime revision" in manager


def test_android_manager_exports_android_managed_runtime_mode():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(encoding="utf-8")

    assert "export JOBTOMATIK_RUNTIME_MODE='android_managed'" in manager


def test_android_manager_frontend_runtime_is_static_artifact_only():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(encoding="utf-8")

    assert 'FRONTEND_RUNTIME_MODE="${JOBTOMATIK_FRONTEND_RUNTIME_MODE:-static_artifact}"' in manager
    assert 'if [[ "$FRONTEND_RUNTIME_MODE" != "static_artifact" ]]' in manager
    assert 'export JOBTOMATIK_FRONTEND_RUNTIME_MODE="$FRONTEND_RUNTIME_MODE"' in manager
    assert "npm run dev" not in manager
    assert "serve_static_frontend.py" in manager


def test_android_manager_resolves_repo_root_from_script_when_sourced(tmp_path):
    repo = tmp_path / "JobTomatik"
    backend = repo / "backend"
    scripts = backend / "scripts"
    scripts.mkdir(parents=True)
    manager = scripts / "manage_android_stack.sh"
    manager.write_text(
        """
#!/usr/bin/env bash
SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"
BACKEND_ROOT="$(cd -- "$(dirname -- "$SCRIPT_SOURCE")/.." && pwd)"
REPO_ROOT="$(cd -- "$BACKEND_ROOT/.." && pwd)"
printf '%s\n' "$SCRIPT_SOURCE"
printf '%s\n' "$BACKEND_ROOT"
printf '%s\n' "$REPO_ROOT"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$0" "$1"',
            str(manager),
            "restart",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.splitlines()
    assert lines[0] == str(manager)
    assert lines[1] == str(tmp_path / "backend")
    assert lines[2] == str(tmp_path)


def test_android_wrapper_propagates_managed_runtime_and_static_frontend_modes_to_manager():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    foreground = (
        "export JOBTOMATIK_RUNTIME_MODE=android_managed "
        "JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE' && "
        "bash backend/scripts/manage_android_stack.sh '$action'"
    )
    detached = (
        "export JOBTOMATIK_RUNTIME_MODE=android_managed "
        "JOBTOMATIK_FRONTEND_RUNTIME_MODE='$FRONTEND_RUNTIME_MODE' && "
        r"exec bash -c 'source \"\$0\" \"\$1\" && exec sleep infinity' "
        "backend/scripts/manage_android_stack.sh '$action'"
    )

    assert foreground in wrapper
    assert detached in wrapper
