from __future__ import annotations

import inspect

from app.api import supervised_submissions
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.material import ApplicationMaterial
from app.models.user import User
from app.services.lever_phase_b_current_operator import (
    show_current_lever_operator_materials,
)


POSTING_ID = "e8df92c9-23ed-4688-9b2c-4e5db504d24b"
APPLICATION_URL = f"https://jobs.lever.co/getmaple/{POSTING_ID}/apply"
POSTING_SHA = "b" * 64
EVIDENCE_DIGEST = "a" * 64


def _seed_frozen_bundle(db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    job = Job(
        external_id=f"lever:getmaple:{POSTING_ID}",
        title="Client Success Associate (Bilingual, French/English)",
        company="Maple",
        location="Remote within Canada",
        url=APPLICATION_URL,
        source=JobSource.lever,
        status=JobStatus.queued,
        raw_data={
            "selection_source": "manual_lever_phase_b_current",
            "lever_official_posting_sha256": POSTING_SHA,
            "supervised_target_metadata": {
                "platform": "lever",
                "adapter": "lever",
                "adapter_version": "1.1.0",
                "verified": True,
                "blockers": [],
                "site": "getmaple",
                "posting_id": POSTING_ID,
                "region": "global",
                "canonical_application_url": APPLICATION_URL,
                "posting_metadata_hash": "c" * 64,
                "identity_hash": "d" * 64,
            },
        },
    )
    db_session.add(job)
    db_session.flush()

    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.submission_uncertain.value,
    )
    db_session.add(application)
    db_session.flush()

    for material_type, content in (
        ("cover_letter", "Frozen verified cover letter"),
        ("resume_summary", "Frozen verified resume summary"),
    ):
        db_session.add(
            ApplicationMaterial(
                user_id=user.id,
                application_id=application.id,
                material_type=material_type,
                version=2,
                status="verified",
                content=content,
                claims=[],
                warnings=[],
                source_snapshot={
                    "lever_phase_b_preparation": {
                        "posting_sha256": POSTING_SHA,
                        "evidence_digest": EVIDENCE_DIGEST,
                        "critical_errors": [],
                    }
                },
                generator_version="verified-material-v5",
            )
        )
    db_session.commit()
    return user, application


def test_frozen_current_lever_materials_remain_readable_when_submission_is_uncertain(
    auth_client,
    db_session,
):
    user, application = _seed_frozen_bundle(db_session)

    result = show_current_lever_operator_materials(
        db_session,
        user,
        application_id=application.id,
    )

    assert result["read_only"] is True
    assert result["automation_state"] == ApplicationAutomationState.submission_uncertain.value
    assert result["application_url"] == APPLICATION_URL
    assert result["posting_sha256"] == POSTING_SHA
    assert result["materials"]["cover_letter"]["content"] == "Frozen verified cover letter"
    assert result["materials"]["resume_summary"]["content"] == "Frozen verified resume summary"


def test_supervised_submit_reservation_holds_application_row_lock_through_validation():
    source = inspect.getsource(supervised_submissions.queue_supervised_submission)

    assert "lock=True" in source
    assert source.index("lock=True") < source.index("validate_supervised_approval")
    assert source.index("validate_supervised_approval") < source.index("reserve_submission_attempt")
    assert source.index("reserve_submission_attempt") < source.index("db.commit()")
