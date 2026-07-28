from __future__ import annotations

from app.models.application import Application, ManualReviewReason
from app.models.job import Job
from app.services.application_state import create_manual_review_task
from app.services.submission_integrity import (
    DuplicateSubmissionIdentityError,
    active_submission_attempt,
    approval_submission_binding_hash,
    build_submission_identity_aliases,
    claim_submission_identity_aliases,
    prepare_submission_evidence_receipt,
    register_submission_evidence_receipt,
)


_INSTALLED = False


def install_submission_integrity_guards() -> None:
    """Install replay guards after task and API modules imported their references."""

    global _INSTALLED
    if _INSTALLED:
        return

    from app.api import supervised_submissions as supervised_api
    from app.services import application_state
    from app.services import application_target_task_integration as target_integration
    from app.services import supervised_submission
    from app.services import supervised_submission_integration as supervised_integration
    from app.tasks import applications as application_tasks

    original_record_evidence = application_state.record_submission_evidence
    original_initialize_target = target_integration.initialize_application_target
    original_record_target = target_integration.record_application_target
    original_preflight = supervised_submission.build_supervised_preflight
    original_issue_approval = supervised_submission.issue_supervised_approval
    original_validate_approval = supervised_submission.validate_supervised_approval

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

    def guarded_preflight(db, application, user, job, **kwargs):
        result = original_preflight(db, application, user, job, **kwargs)
        active = active_submission_attempt(db, application.id)
        if active:
            blocker = f"active_submission_attempt:{active.reference}:{active.status}"
            result["blockers"] = list(dict.fromkeys([*result.get("blockers", []), blocker]))
            result["ready"] = False
        return result

    def guarded_issue_approval(db, application, user, job, **kwargs):
        active = active_submission_attempt(db, application.id)
        if active:
            raise supervised_submission.SupervisedSubmissionApprovalError(
                f"Application already has active submission attempt {active.reference}."
            )
        approval = original_issue_approval(db, application, user, job, **kwargs)
        db.flush()
        approval.approval_metadata = {
            **dict(approval.approval_metadata or {}),
            "submission_binding_hash": approval_submission_binding_hash(approval),
        }
        return approval

    def guarded_validate_approval(db, application, user, job, **kwargs):
        approval = original_validate_approval(db, application, user, job, **kwargs)
        expected = approval_submission_binding_hash(approval)
        stored = str((approval.approval_metadata or {}).get("submission_binding_hash") or "")
        if stored and stored != expected:
            raise supervised_submission.SupervisedSubmissionApprovalMismatch(
                "Approved submission binding changed"
            )
        return approval

    application_state.record_submission_evidence = guarded_record_submission_evidence
    application_tasks.record_submission_evidence = guarded_record_submission_evidence
    target_integration.initialize_application_target = guarded_initialize_application_target
    target_integration.record_application_target = guarded_record_application_target

    supervised_api.build_supervised_preflight = guarded_preflight
    supervised_api.issue_supervised_approval = guarded_issue_approval
    supervised_api.validate_supervised_approval = guarded_validate_approval
    supervised_integration.validate_supervised_approval = guarded_validate_approval
    _INSTALLED = True


__all__ = ["install_submission_integrity_guards"]
