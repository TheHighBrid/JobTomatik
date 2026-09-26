import json
import subprocess
import sys


def test_verifier_cli_fails_closed_without_real_evidence(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"adapter": "ashby"}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "backend/scripts/verify_ashby_real_certification.py", str(evidence)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["certified"] is False
    assert "missing_application_id" in payload["blockers"]
    assert "confirmation_not_sufficient" in payload["blockers"]
