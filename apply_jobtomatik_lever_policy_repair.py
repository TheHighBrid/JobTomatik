#!/usr/bin/env python3
"""Apply the JobTomatik Lever operator-assisted policy-collision repair.

Run from the JobTomatik repository root. The script is deliberately fail-closed:
every edit requires the exact current-main source fragment to be present once.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path.cwd()
CONFIG = ROOT / "backend/app/config.py"
INTEGRATION = ROOT / "backend/app/services/operator_assisted_handoff_integration.py"
RUNTIME_TEST = ROOT / "backend/tests/test_supervised_lever_pilot_runtime_control.py"


def replace_exact(path: Path, old: str, new: str, expected_count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected_count:
        raise RuntimeError(
            f"{path}: expected repair anchor {expected_count} time(s), found {count}. "
            "Refusing to guess against a different source revision."
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> int:
    for path in (CONFIG, INTEGRATION, RUNTIME_TEST):
        if not path.exists():
            raise RuntimeError(f"Run this script from the JobTomatik repo root: missing {path}")

    # 1. Separate the operator-assisted final-action lane from the temporary
    # supervised Lever lease projection without weakening explicit operator config.
    replace_exact(
        CONFIG,
        'SUPERVISED_SUBMISSION_SERVICE_MODULE = "app.services.supervised_submission"\n\n\n'
        'def _supervised_submission_service_on_stack() -> bool:\n',
        'SUPERVISED_SUBMISSION_SERVICE_MODULE = "app.services.supervised_submission"\n'
        'OPERATOR_ASSISTED_FINAL_ACTION_MODULES = frozenset({\n'
        '    "app.services.operator_assisted_auto_submit",\n'
        '    "app.services.operator_assisted_final_action",\n'
        '    "app.services.operator_assisted_handoff_integration",\n'
        '    "app.services.operator_assisted_submission",\n'
        '})\n\n\n'
        'def _supervised_submission_service_on_stack() -> bool:\n',
    )

    replace_exact(
        CONFIG,
        '        frame = frame.f_back\n'
        '    return False\n\n\n'
        'class Settings(BaseSettings):\n',
        '        frame = frame.f_back\n'
        '    return False\n\n\n'
        'def _operator_assisted_final_action_on_stack() -> bool:\n'
        '    """Return true only inside the retained operator-assisted final-action lane."""\n\n'
        '    try:\n'
        '        frame = sys._getframe(2)\n'
        '    except (AttributeError, ValueError):\n'
        '        return False\n'
        '    for _ in range(24):\n'
        '        if frame is None:\n'
        '            break\n'
        '        if str(frame.f_globals.get("__name__") or "") in OPERATOR_ASSISTED_FINAL_ACTION_MODULES:\n'
        '            return True\n'
        '        frame = frame.f_back\n'
        '    return False\n\n\n'
        'class Settings(BaseSettings):\n',
    )

    replace_exact(
        CONFIG,
        '        # Explicit operator-controlled execution flags are authoritative.\n'
        '        if value:\n'
        '            return True\n\n'
        '        configured_greenhouse = bool(\n',
        '        # Explicit operator-controlled execution flags are authoritative.\n'
        '        if value:\n'
        '            return True\n\n'
        '        # The retained operator-assisted lane deliberately requires the persisted\n'
        '        # global + Lever pilot switches to stay OFF. The temporary supervised\n'
        '        # worker lease belongs to a different live-submission lane and must not\n'
        '        # dynamically project those switches true inside this final-action path.\n'
        '        if _operator_assisted_final_action_on_stack():\n'
        '            return value\n\n'
        '        configured_greenhouse = bool(\n',
    )

    # 2. Add a regression that reproduces the exact Android worker collision:
    # active Lever supervised target scope + operator-assisted final action.
    replace_exact(
        RUNTIME_TEST,
        '    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")\n'
        '    assert settings.allow_real_application_submit is False\n'
        '    with supervised_target_scope({"platform": "greenhouse"}):\n',
        '    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")\n'
        '    assert settings.allow_real_application_submit is False\n\n'
        '    monkeypatch.setattr(\n'
        '        config_module,\n'
        '        "_operator_assisted_final_action_on_stack",\n'
        '        lambda: True,\n'
        '    )\n'
        '    with supervised_target_scope({"platform": "lever", "posting_id": "abc"}):\n'
        '        assert settings.allow_real_application_submit is False\n'
        '        assert settings.lever_supervised_pilot_enabled is False\n\n'
        '    monkeypatch.setattr(\n'
        '        config_module,\n'
        '        "_operator_assisted_final_action_on_stack",\n'
        '        lambda: False,\n'
        '    )\n'
        '    with supervised_target_scope({"platform": "greenhouse"}):\n',
    )

    # 3. Instrument the actual final-action path so the next device run reports
    # the exact locked door instead of appearing to "stall at Submit".
    replace_exact(
        INTEGRATION,
        'from __future__ import annotations\n\n'
        'from contextlib import contextmanager\n',
        'from __future__ import annotations\n\n'
        'import logging\n'
        'from contextlib import contextmanager\n',
    )

    replace_exact(
        INTEGRATION,
        'from app.services.operations_settings import get_operations_settings\n\n\n'
        '_OPERATOR_PREP_TARGET:',
        'from app.services.operations_settings import get_operations_settings\n\n\n'
        'logger = logging.getLogger(__name__)\n\n\n'
        '_OPERATOR_PREP_TARGET:',
    )

    replace_exact(
        INTEGRATION,
        '    if bool(core.lever_supervised_pilot_enabled):\n'
        '        blockers.append("operator_assisted_requires_platform_pilot_disabled")\n'
        '    return blockers\n',
        '    if bool(core.lever_supervised_pilot_enabled):\n'
        '        blockers.append("operator_assisted_requires_platform_pilot_disabled")\n'
        '    logger.info(\n'
        '        "JT_LEVER_FINAL stage=gate_check platform=%s global_submit=%s "\n'
        '        "lever_pilot=%s autopilot=%s blockers=%s",\n'
        '        platform,\n'
        '        bool(core.allow_real_application_submit),\n'
        '        bool(core.lever_supervised_pilot_enabled),\n'
        '        bool(operations.autopilot_enabled),\n'
        '        blockers,\n'
        '    )\n'
        '    return blockers\n',
    )

    replace_exact(
        INTEGRATION,
        '        playwright, _, _, page = await browser_handoff._connect_local_cdp(session)\n'
        '        try:\n',
        '        logger.info(\n'
        '            "JT_LEVER_FINAL stage=entry_gate_passed handoff=%s",\n'
        '            str(session.public_id or ""),\n'
        '        )\n'
        '        playwright, _, _, page = await browser_handoff._connect_local_cdp(session)\n'
        '        try:\n'
        '            logger.info("JT_LEVER_FINAL stage=cdp_attached url=%s", str(page.url or ""))\n',
    )

    replace_exact(
        INTEGRATION,
        '            submit_control = await adapter.find_submit_button(surface)\n'
        '            if submit_control is None:\n',
        '            submit_control = await adapter.find_submit_button(surface)\n'
        '            logger.info(\n'
        '                "JT_LEVER_FINAL stage=submit_lookup found=%s",\n'
        '                submit_control is not None,\n'
        '            )\n'
        '            if submit_control is None:\n',
        expected_count=2,
    )

    replace_exact(
        INTEGRATION,
        '                visible = await submit_control.is_visible()\n'
        '                enabled = await submit_control.is_enabled()\n'
        '            except Exception as exc:\n',
        '                visible = await submit_control.is_visible()\n'
        '                enabled = await submit_control.is_enabled()\n'
        '                logger.info(\n'
        '                    "JT_LEVER_FINAL stage=submit_state visible=%s enabled=%s",\n'
        '                    visible,\n'
        '                    enabled,\n'
        '                )\n'
        '            except Exception as exc:\n',
        expected_count=2,
    )

    replace_exact(
        INTEGRATION,
        '            validation_errors = await adapter.extract_validation_errors(surface)\n'
        '            if validation_errors:\n',
        '            validation_errors = await adapter.extract_validation_errors(surface)\n'
        '            logger.info(\n'
        '                "JT_LEVER_FINAL stage=validation error_count=%s",\n'
        '                len(validation_errors),\n'
        '            )\n'
        '            if validation_errors:\n',
        expected_count=2,
    )

    replace_exact(
        INTEGRATION,
        '            await submit_control.click()\n'
        '            await page.wait_for_timeout(900)\n',
        '            logger.info("JT_LEVER_FINAL stage=click_start url=%s", before_url)\n'
        '            await submit_control.click()\n'
        '            logger.info("JT_LEVER_FINAL stage=click_complete url=%s", str(page.url or ""))\n'
        '            await page.wait_for_timeout(900)\n',
    )

    replace_exact(
        INTEGRATION,
        '            confirmation_evidence = [item.as_dict() for item in confirmation_items]\n'
        '            submission_confirmed = any(item.is_sufficient for item in confirmation_items)\n',
        '            confirmation_evidence = [item.as_dict() for item in confirmation_items]\n'
        '            submission_confirmed = any(item.is_sufficient for item in confirmation_items)\n'
        '            logger.info(\n'
        '                "JT_LEVER_FINAL stage=confirmation confirmed=%s evidence_count=%s url=%s",\n'
        '                submission_confirmed,\n'
        '                len(confirmation_evidence),\n'
        '                str(page.url or ""),\n'
        '            )\n',
    )

    print("Repair applied.")
    print("Changed:")
    print(" - backend/app/config.py")
    print(" - backend/app/services/operator_assisted_handoff_integration.py")
    print(" - backend/tests/test_supervised_lever_pilot_runtime_control.py")
    print()

    print("Running git diff --check...")
    subprocess.run(["git", "diff", "--check"], check=True, cwd=ROOT)

    tests = [
        "backend/tests/test_supervised_lever_pilot_runtime_control.py",
        "backend/tests/test_operator_assisted_final_action_runtime_safety.py",
        "backend/tests/test_operator_assisted_auto_submit_trigger.py",
    ]
    print("Running focused regression suite...")
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *tests],
        check=True,
        cwd=ROOT,
    )

    print()
    print("REPAIR_VERIFIED: source checks and focused regressions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
