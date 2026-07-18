import importlib.util
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "evaluate_greenhouse_pilot_batch.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("greenhouse_pilot_batch_evaluator", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _report(*items):
    return {
        "passed": False,
        "final_submit_clicked": False,
        "reports": list(items),
    }


def _item(*, passed, error=None, final_submit_clicked=False):
    return {
        "passed": passed,
        "error": error,
        "final_submit_clicked": final_submit_clicked,
    }


def test_manifest_batch_accepts_qualifying_and_known_safe_exclusions():
    evaluator = _module()
    payload = _report(
        _item(passed=True, error="A CAPTCHA or human-verification challenge requires manual completion."),
        _item(
            passed=False,
            error=(
                "HTTPStatusError: Client error '404 Not Found' for url "
                "'https://boards-api.greenhouse.io/v1/boards/example/jobs/123?questions=true'"
            ),
        ),
        _item(
            passed=False,
            error="Required application fields need review before the ATS flow can continue.",
        ),
    )

    assert evaluator.evaluate_batch_report(payload) == {
        "targets": 3,
        "qualifying": 1,
        "nonqualifying": 2,
    }


def test_manifest_batch_rejects_unknown_failures():
    evaluator = _module()
    payload = _report(_item(passed=False, error="RuntimeError: browser process crashed"))

    with pytest.raises(ValueError, match="failed unexpectedly"):
        evaluator.evaluate_batch_report(payload)


def test_manifest_batch_rejects_any_final_submit_action():
    evaluator = _module()
    payload = _report(_item(passed=False, error="stale", final_submit_clicked=True))

    with pytest.raises(ValueError, match="final_submit_clicked=false"):
        evaluator.evaluate_batch_report(payload)
