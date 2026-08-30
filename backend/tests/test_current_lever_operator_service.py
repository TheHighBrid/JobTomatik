from __future__ import annotations

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.material import ApplicationMaterial
from app.models.submission_integrity import SubmissionAttempt, SubmissionAttemptStatus
from app.models.user import User
from app.services import lever_phase_b_current_operator as operator
from app.services.lever_phase_b_current_materials import LeverPhaseBReviewedMaterialsError


POSTING_SHA = "b" * 64
EVIDENCE_DIGEST = "a" * 64


def _application(db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    job = Job(
        external_id="lever:getmaple:operator-service",
        title="Client Success Associate (Bilingual, French/English)",
        company="Maple",
        location="Remote within Canada",
        url="https://jobs.lever.co/getmaple/e8df92c9-23ed-4688-9b2c-4e5db504d24b/apply",
        source=JobSource.lever,
        status=JobStatus.queued,
        raw_data={"selection_source": "manual_lever_phase_b_current"},
    )
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.needs_review.value,
    )
    db_session.add(application)
    db_session.flush()
    return user, application


def _bundle(db_session, user, application):
    materials = {}
    for material_type, content in (
        ("cover_letter", "Verified cover letter"),
        ("resume_summary", "Verified resume summary"),
    ):
        material = ApplicationMaterial(
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
        db_session.add(material)
        materials[material_type] = material
    db_session.commit()
    return materials


def _binding(materials):
    return {
        "material_ids": {
            material_type: material.id
            for material_type, material in materials.items()
        },
        "material_versions": {
            material_type: material.version
            for material_type, material in materials.items()
        },
        "posting_sha256": POSTING_SHA,
        "evidence_digest": EVIDENCE_DIGEST,
    }


def test_uncertain_attempt_blocks_prepare_and_review_before_delegate(
    auth_client,
    db_session,
    monkeypatch,
):
    user, application = _application(db_session)
    attempt = SubmissionAttempt(
        reference="attempt-current-lever-operator-uncertain",
        application_id=application.id,
        user_id=user.id,
        approval_reference="approval-current-lever-operator-uncertain",
        attempt_number=1,
        task_id="task-current-lever-operator-uncertain",
        status=SubmissionAttemptStatus.uncertain.value,
        binding_hash="c" * 64,
        identity_digest="d" * 64,
        combined_payload_hash="e" * 64,
        adapter_version="1.1.0",
    )
    db_session.add(attempt)
    db_session.commit()

    calls = []
    monkeypatch.setattr(
        operator.v5,
        "prepare_current_lever_materials",
        lambda *_args, **_kwargs: calls.append("prepare"),
    )
    monkeypatch.setattr(
        operator.v5,
        "review_current_lever_materials",
        lambda *_args, **_kwargs: calls.append("review"),
    )

    with pytest.raises(LeverPhaseBReviewedMaterialsError, match="quarantined"):
        operator.prepare_current_lever_operator_materials(
            db_session,
            user,
            application_id=application.id,
        )

    with pytest.raises(LeverPhaseBReviewedMaterialsError, match="quarantined"):
        operator.review_current_lever_operator_materials(
            db_session,
            user,
            application_id=application.id,
            approved=True,
            notes=None,
            material_ids={"cover_letter": 1, "resume_summary": 2},
            material_versions={"cover_letter": 1, "resume_summary": 1},
            posting_sha256=POSTING_SHA,
            evidence_digest=EVIDENCE_DIGEST,
        )

    assert calls == []


def test_review_rejects_stale_displayed_bundle_before_delegate(
    auth_client,
    db_session,
    monkeypatch,
):
    user, application = _application(db_session)
    materials = _bundle(db_session, user, application)
    binding = _binding(materials)
    stale_ids = dict(binding["material_ids"])
    stale_ids["cover_letter"] += 1000

    calls = []
    monkeypatch.setattr(
        operator.v5,
        "review_current_lever_materials",
        lambda *_args, **_kwargs: calls.append("review"),
    )

    with pytest.raises(LeverPhaseBReviewedMaterialsError, match="MATERIAL_BUNDLE_STALE"):
        operator.review_current_lever_operator_materials(
            db_session,
            user,
            application_id=application.id,
            approved=True,
            notes=None,
            material_ids=stale_ids,
            material_versions=binding["material_versions"],
            posting_sha256=binding["posting_sha256"],
            evidence_digest=binding["evidence_digest"],
        )

    assert calls == []


def test_review_delegates_only_when_exact_displayed_bundle_still_matches(
    auth_client,
    db_session,
    monkeypatch,
):
    user, application = _application(db_session)
    materials = _bundle(db_session, user, application)
    binding = _binding(materials)
    calls = []

    def review(_db, _user, *, application_id, approved, notes):
        calls.append((application_id, approved, notes))
        return {
            "application_id": application_id,
            "approved": approved,
            "approval_issued": False,
            "submission_queued": False,
            "runtime_flags_changed": False,
        }

    monkeypatch.setattr(operator.v5, "review_current_lever_materials", review)
    result = operator.review_current_lever_operator_materials(
        db_session,
        user,
        application_id=application.id,
        approved=False,
        notes="Reviewed exact displayed bundle",
        **binding,
    )

    assert calls == [
        (application.id, False, "Reviewed exact displayed bundle")
    ]
    assert result["submission_queued"] is False
    assert result["approval_issued"] is False
