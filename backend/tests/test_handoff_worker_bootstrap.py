import subprocess
import sys


def test_handoff_task_import_installs_review_attachment_bridge():
    script = r'''
from app.services import handoff_integration

assert handoff_integration._INSTALLED is False

from app.tasks import handoffs  # noqa: F401
from app.tasks import applications

assert handoff_integration._INSTALLED is True
assert applications._create_result_review_tasks.__module__ == "app.services.handoff_integration"
assert applications._create_result_review_tasks.__name__ == "wrapped_create_result_review_tasks"
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, (
        f"clean worker import failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
