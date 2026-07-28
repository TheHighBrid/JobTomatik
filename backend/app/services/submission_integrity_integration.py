from __future__ import annotations

from app.models.application import Application, ManualReviewReason
from app.models.job import Job
from app.services.application_state import create_manual_review_task
from app.services.submission_integrity import (
    DuplicateSubmissionIdentityError,
    build_submission_identity_aliases,
    claim_submission_identity_aliases,
    prepare_submission_evidence_receipt,
    register_submission_evidence_receipt,
)


_INSTALLED = False


def install_submission_integrity_guards() -> None:
    """Install replay guards after task modules have imported their service references."""

    global _INSTALLED
    if _INSTALLED:
        return

    from app.services import application_state
    from app.services import application_target_task_integration as target_integration
    from app.tasks import applications as application_tasks

    original_record_evidence = application_state.record_submission_evidence
    original_initialize_target = target_integration.initialize_application_target
    original_record_target = target_integration.record_application_target

    def guarded_record_submission_evidence(
        db,
        application,
        evidence_type,
        *,
        is_sufficient,
        final_url=None,
        confirmation_text=None,
        selector=None,
        external_application_id=None,
        screenshot_path=None,
        html_snapshot_path=None,
        payload_hash=None,
        metadata=None,
    ):
        evidence_type_value = str(getattr(evidence_type, "value", evidence_type))
        fingerprint, existing = prepare_submission_evidence_receipt(
            db,
            application,
            evidence_type=evidence_type_value,
            final_url=final_url,
            confirmation_text=confirmation_text,
            external_application_id=external_application_id,
            payload_hash=payload_hash,
            metadata=metadata,
        )
        if existing:
            return existing
        evidence = original_record_evidence(
            db,
            application,
            evidence_type,
            is_sufficient=is_sufficient,
            final_url=final_url,
            confirmation_text=confirmation_text,
            selector=selector,
            external_application_id=external_application_id,
            screenshot_path=screenshot_path,
            html_snapshot_path=html_snapshot_path,
            payload_hash=payload_hash,
            metadata=metadata,
        )
        db.flush()
        register_submission_evidence_receipt(
            db,
            application,
            evidence,
            fingerprint=fingerprint,
            evidence_type=evidence_type_value,
            final_url=final_url,
            external_application_id=external_application_id,
            payload_hash=payload_hash,
            metadata=metadata,
        )
        job = db.query(Job).filter(Job.id == application.job_id).first()
        if job:
            aliases = build_submission_identity_aliases(
                job,
                application=application,
                final_url=final_url,
            )
            claim_submission_identity_aliases(db, application, aliases)
        return evidence

    def _claim_target_aliases(db, application_id: int, target_url: str) -> None:
        application = db.query(Application).filter(Application.id == application_id).first()
        job = db.query(Job).filter(Job.id == application.job_id).first() if application else None
        if not application or not job:
            return
        aliases = build_submission_identity_aliases(
            job,
            application=application,
            final_url=target_url,
        )
        try:
            claim_submission_identity_aliases(db, application, aliases)
        except DuplicateSubmissionIdentityError as exc:
            application.application_target_metadata = {
                **dict(application.application_target_metadata or {}),
                "duplicate_submission_identity": {
                    "existing_application_id": exc.existing_application_id,
                    "alias_type": exc.alias_type,
                    "alias_key": exc.alias_key,
                },
            }
            create_manual_review_task(
                db,
                application,
                ManualReviewReason.safety_gate_blocked,
                "Another application already owns the resolved employer posting.",
                details={
                    "reason": "duplicate_submission_identity",
                    "existing_application_id": exc.existing_application_id,
                    "alias_type": exc.alias_type,
                },
                blocking_url=target_url,
            )
            db.commit()
            raise

    def guarded_initialize_application_target(db, application, job):
        target = original_initialize_target(db, application, job)
        if target:
            _claim_target_aliases(db, application.id, target)
        return target

    def guarded_record_application_target(db, application, **kwargs):
        target = original_record_target(db, application, **kwargs)
        _claim_target_aliases(db, application.id, target)
        return target

    application_state.record_submission_evidence = guarded_record_submission_evidence
    application_tasks.record_submission_evidence = guarded_record_submission_evidence
    target_integration.initialize_application_target = guarded_initialize_application_target
    target_integration.record_application_target = guarded_record_application_target
    _INSTALLED = True


__all__ = ["install_submission_integrity_guards"]
