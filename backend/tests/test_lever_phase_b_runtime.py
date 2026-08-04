import json
from pathlib import Path

import pytest

from app.models.application import Application, ApplicationAutomationState
from app.models.job import Job, JobSource, JobStatus
from app.services import lever_phase_b_launch as launch_service
from app.services import lever_phase_b_runtime as runtime_service
from app.services.lever_phase_b_runtime import canonical_lever_application_url


EVIDENCE_ROOT = Path(__file__).resolve().parents[1] / "evidence"
CANONICAL_LAUNCH = EVIDENCE_ROOT / "lever-phase-b-launch.json"
CIN7_POSTING_ID = "7d4a0f39-7771-4d19-b328-e8705cac1623"
CIN7_HOSTED_URL = f"https://jobs.lever.co/cin7/{CIN7_POSTING_ID}"
CIN7_APPLY_URL = f"{CIN7_HOSTED_URL}/apply"


@pytest.fixture(autouse=True)
def use_canonical_launch(monkeypatch):
    monkeypatch.setattr(
        launch_service.settings,
        "lever_phase_b_launch_path",
        str(CANONICAL_LAUNCH),
    )
    monkeypatch.setattr(
        runtime_service.settings,
        "lever_phase_b_launch_path",
        str(CANONICAL_LAUNCH),
    )


def _copy_launch_tree(tmp_path: Path) -> dict:
    launch = json.loads(CANONICAL_LAUNCH.read_text(encoding="utf-8"))
    retained_paths = [launch["selection_receipt"]["path"]]
    for item in launch["applications"]:
        retained_paths.extend(
            [
                item["dossier"]["artifact_path"],
                item["dry_preview"]["source_report_path"],
            ]
        )
    for relative in retained_paths:
        source = EVIDENCE_ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    (tmp_path / "lever-phase-b-launch.json").write_bytes(
        CANONICAL_LAUNCH.read_bytes()
    )
    return launch


def test_lever_hosted_and_apply_urls_share_one_exact_identity():
    assert canonical_lever_application_url(CIN7_HOSTED_URL) == CIN7_APPLY_URL
    assert canonical_lever_application_url(CIN7_APPLY_URL) == CIN7_APPLY_URL


@pytest.mark.parametrize(
    "url",
    [
        "http://jobs.lever.co/cin7/123/apply",
        "https://user:pass@jobs.lever.co/cin7/123/apply",
        "https://jobs.lever.co.attacker.example/cin7/123/apply",
        "https://jobs.lever.co/cin7",
        "https://jobs.lever.co/cin7/123/submit",
        "https://jobs.lever.co/cin7/123/apply?token=unsafe",
        "https://jobs.lever.co:8443/cin7/123/apply",
    ],
)
def test_runtime_rejects_unsafe_or_non_exact_lever_urls(url):
    with pytest.raises(ValueError):
        canonical_lever_application_url(url)


def test_materialization_reuses_official_discovery_hosted_url(
    auth_client,
    db_session,
):
    existing_job = Job(
        external_id=f"lever:cin7:{CIN7_POSTING_ID}",
        title="Customer Success Manager",
        company="Cin7",
        location="Toronto, CAN",
        url=CIN7_HOSTED_URL,
        source=JobSource.lever,
        status=JobStatus.queued,
        raw_data={
            "official_public_ats": True,
            "application_method": "external_url",
            "selected_apply_url": CIN7_HOSTED_URL,
            "ats_provider": "lever",
            "ats_identifier": "cin7",
            "provider_job_id": CIN7_POSTING_ID,
        },
    )
    db_session.add(existing_job)
    db_session.commit()

    response = auth_client.post(
        "/api/supervised-pilot/lever-launch/D8-026/materialize"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_job"] is False
    assert payload["created_application"] is True
    assert payload["job_id"] == existing_job.id
    assert payload["application_url"] == CIN7_APPLY_URL
    assert db_session.query(Job).count() == 1

    application = db_session.query(Application).one()
    assert application.job_id == existing_job.id
    assert application.automation_state == ApplicationAutomationState.preparing.value
    assert application.application_target_url == CIN7_APPLY_URL
    assert application.submission_attempt_count == 0


def test_runtime_rejects_tampered_phase_a_source_report(
    auth_client,
    db_session,
    monkeypatch,
    tmp_path,
):
    launch = _copy_launch_tree(tmp_path)
    cin7 = next(
        item
        for item in launch["applications"]
        if item["selection_reference"].endswith("#D8-026")
    )
    source_path = tmp_path / cin7["dry_preview"]["source_report_path"]
    report = json.loads(source_path.read_text(encoding="utf-8"))
    report["passed"] = False
    source_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    launch_path = tmp_path / "lever-phase-b-launch.json"
    monkeypatch.setattr(
        launch_service.settings,
        "lever_phase_b_launch_path",
        str(launch_path),
    )
    monkeypatch.setattr(
        runtime_service.settings,
        "lever_phase_b_launch_path",
        str(launch_path),
    )

    status = auth_client.get("/api/supervised-pilot/lever-launch")
    materialize = auth_client.post(
        "/api/supervised-pilot/lever-launch/D8-026/materialize"
    )

    assert status.status_code == 409
    assert materialize.status_code == 409
    assert "source report hash mismatch" in status.json()["detail"]
    assert db_session.query(Job).count() == 0
    assert db_session.query(Application).count() == 0
