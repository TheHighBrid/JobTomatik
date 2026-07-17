from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "greenhouse-live-certification.yml"
)


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_exercise_mode_uses_generated_synthetic_profile():
    workflow = _workflow_text()

    assert "--exercise" in workflow
    assert "--synthetic-profile" in workflow
    assert "--synthetic-resume-path" in workflow
    assert "GREENHOUSE_CERT_RESUME_PATH: ./greenhouse-synthetic-resume.pdf" in workflow


def test_workflow_does_not_require_certification_secrets():
    workflow = _workflow_text()

    assert "GREENHOUSE_CERT_PROFILE_JSON" not in workflow
    assert "GREENHOUSE_CERT_RESUME_B64" not in workflow
    assert "GREENHOUSE_CERT_COVER_LETTER" not in workflow
    assert "base64 --decode" not in workflow
    assert "Prepare synthetic certification resume" not in workflow


def test_workflow_keeps_real_submission_disabled_and_asserts_safety():
    workflow = _workflow_text()

    assert 'ALLOW_REAL_APPLICATION_SUBMIT: "false"' in workflow
    assert "Assert no final submit action occurred" in workflow
    assert 'report.get("final_submit_clicked") is False' in workflow
    assert "backend/greenhouse-synthetic-resume.pdf" in workflow


def test_pilot_push_trigger_is_narrow_manifest_driven_and_synthetic():
    workflow = _workflow_text()

    assert '      - "agent/greenhouse-pilot-*"' in workflow
    assert '      - "backend/greenhouse-pilot-urls.txt"' in workflow
    assert "GREENHOUSE_PILOT_URL_MANIFEST: ./greenhouse-pilot-urls.txt" in workflow
    assert 'if [[ "$GITHUB_EVENT_NAME" == "push" ]]' in workflow
    assert 'export GREENHOUSE_CERT_URLS="$(cat "$GREENHOUSE_PILOT_URL_MANIFEST")"' in workflow
    assert 'exercise_mode="true"' in workflow
    assert "Pilot URL manifest is missing or empty" in workflow
    assert "github.event_name == 'push'" in workflow
