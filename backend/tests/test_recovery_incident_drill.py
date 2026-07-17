import hashlib
import json
from datetime import datetime
from pathlib import Path

from app.services.recovery_drill import run_recovery_incident_drill


def _hash_without_report_hash(report):
    payload = dict(report)
    payload.pop("report_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_recovery_incident_drill_passes_and_retains_report(tmp_path):
    target = tmp_path / "recovery-incident-drill.json"
    report = run_recovery_incident_drill(
        output_path=target,
        now=datetime(2026, 7, 17, 19, 15, 0),
    )

    assert report["passed"] is True
    assert report["mode"] == "isolated_in_memory"
    assert report["safety"] == {
        "browser_opened": False,
        "network_contacted": False,
        "final_submit_clicked": False,
        "real_submission_enabled": False,
        "autopilot_enabled": False,
    }
    assert report["first_recovery"]["checked"] == 3
    assert report["first_recovery"]["recovered"] == 3
    assert report["first_recovery"]["dry_run_recovered"] == 1
    assert report["first_recovery"]["uncertain_recovered"] == 2
    assert report["replay_recovery"]["checked"] == 0
    assert report["replay_recovery"]["recovered"] == 0
    assert report["counts"] == {
        "applications": 3,
        "manual_reviews": 3,
        "notifications": 3,
        "recovery_events": 3,
        "submitted_or_confirmed": 0,
    }
    assert all(report["assertions"].values())
    assert report["report_sha256"] == _hash_without_report_hash(report)

    persisted = json.loads(target.read_text(encoding="utf-8"))
    assert persisted == report


def test_recovery_incident_drill_is_deterministic_for_same_timestamp():
    now = datetime(2026, 7, 17, 19, 30, 0)
    first = run_recovery_incident_drill(now=now)
    second = run_recovery_incident_drill(now=now)

    assert first == second
    assert first["report_sha256"] == second["report_sha256"]


def test_recovery_incident_workflow_contract():
    workflow = Path(__file__).parents[2] / ".github" / "workflows" / "recovery-incident-drill.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "actions/checkout@v6" in text
    assert "actions/setup-python@v6" in text
    assert "actions/upload-artifact@v6" in text
    assert 'ALLOW_REAL_APPLICATION_SUBMIT: "false"' in text
    assert 'AUTOPILOT_ENABLED: "false"' in text
    assert "run_recovery_incident_drill.py" in text
    assert 'report["passed"] is True' in text
    assert 'report["counts"]["submitted_or_confirmed"] == 0' in text
    assert "recovery-incident-drill-report" in text
