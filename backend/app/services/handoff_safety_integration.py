"""Install Day 6 safety guards around retained-browser handoff lifecycle calls."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from app.models.application import Application, ManualReviewReason, ManualReviewTask
from app.models.handoff import ManualHandoffSession
from app.models.job import Job
from app.models.user import User
from app.services.operational_safety import (
    HandoffReasonPolicy,
    OperationalSafetyViolation,
    build_handoff_target_binding,
    classify_handoff_reason,
    evaluate_execution_safety,
    require_handoff_target_binding,
    rebind_resolved_handoff_target,
)


_INSTALLED = False
_INSTALLING = False


def _target_url(application: Application, job: Job, current_url: str | None = None) -> str:
    raw = dict(job.raw_data or {})
    return str(
        current_url
        or application.application_target_url
        or raw.get("selected_apply_url")
        or job.url
        or ""
    ).strip()


def _records(db, session: ManualHandoffSession):
    application = db.query(Application).filter(Application.id == session.application_id).first()
    review = db.query(ManualReviewTask).filter(ManualReviewTask.id == session.manual_review_id).first()
    job = db.query(Job).filter(Job.id == application.job_id).first() if application else None
    user = db.query(User).filter(User.id == application.user_id).first() if application else None
    if not application or not review or not job or not user:
        raise OperationalSafetyViolation(
            "handoff_records_missing",
            "The retained handoff cannot be verified because its application records are incomplete.",
            metadata={"operator_reason_code": "handoff_records_missing"},
        )
    return application, review, job, user


def _operator_final_submit_review_details(review: ManualReviewTask) -> dict[str, Any]:
    """Read final-submit evidence from both direct and grouped review-task shapes."""

    details = dict(review.details or {})
    if details.get("handoff_stage") == "operator_final_submit":
        return details
    for item in details.get("questions") or []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("reason_code") or "") != ManualReviewReason.operator_final_submit_required.value:
            continue
        nested = item.get("details")
        if isinstance(nested, Mapping):
            return dict(nested)
    return {}


def _operator_final_submit_reason_policy(
    review: ManualReviewTask,
    metadata: Optional[Mapping[str, Any]],
) -> Optional[HandoffReasonPolicy]:
    """Certify only the dedicated, fail-safe Lever owner-final-click boundary.

    The global Day 6 reason matrix deliberately does not treat
    ``operator_final_submit_required`` as generically resumable. This scoped policy
    exists only when persisted review evidence and the retained browser snapshot
    jointly prove that the handoff came from the operator-assisted preparation lane.
    """

    final_reason = ManualReviewReason.operator_final_submit_required.value
    if str(review.reason_code or "") != final_reason:
        return None

    review_details = _operator_final_submit_review_details(review)
    snapshot = dict(metadata or {})
    supervised_target = dict(snapshot.get("supervised_target") or {})

    review_identity_hash = str(review_details.get("target_identity_hash") or "")
    snapshot_identity_hash = str(snapshot.get("operator_target_identity_hash") or "")
    target_identity_hash = str(supervised_target.get("identity_hash") or "")
    snapshot_adapter_version = str(snapshot.get("adapter_version") or "")
    target_adapter_version = str(supervised_target.get("adapter_version") or "")

    certified = bool(
        review_details.get("handoff_stage") == "operator_final_submit"
        and review_details.get("operator_final_click_required") is True
        and review_details.get("submit_clicked") is False
        and review_details.get("automated_submission_authorized") is False
        and review_details.get("queue_submission_authorized") is False
        and snapshot.get("operator_assisted_final_submit") is True
        and snapshot.get("operator_final_click_required") is True
        and snapshot.get("automated_submission_authorized") is False
        and snapshot.get("queue_submission_authorized") is False
        and snapshot.get("dry_run") is True
        and str(snapshot.get("adapter") or "") == "lever"
        and snapshot_adapter_version
        and supervised_target.get("verified") is True
        and not list(supervised_target.get("blockers") or [])
        and str(supervised_target.get("platform") or "") == "lever"
        and str(supervised_target.get("adapter") or "") == "lever"
        and target_adapter_version == snapshot_adapter_version
        and review_identity_hash
        and review_identity_hash == snapshot_identity_hash == target_identity_hash
    )
    if not certified:
        return HandoffReasonPolicy(
            reason_code=final_reason,
            disposition="non_resumable",
            resumable=False,
            operator_reason_code="operator_final_submit_not_certified",
            explanation=(
                "The final-submit review is not bound to a certified operator-assisted "
                "Lever snapshot with automated and queue authority disabled."
            ),
        )

    return HandoffReasonPolicy(
        reason_code=final_reason,
        disposition="operator_final_submit",
        resumable=True,
        operator_reason_code="operator_final_submit_owner_boundary",
        explanation=(
            "A retained Lever form may be opened only after exact owner approval, and "
            "only the dedicated once-only final Submit action is permitted."
        ),
    )


def _ensure_target_binding(
    session: ManualHandoffSession,
    application: Application,
    review: ManualReviewTask,
    job: Job,
) -> None:
    """Backfill a missing Day 6 binding from authoritative legacy records.

    Existing retained sessions can predate the binding field. The migration never
    trusts client input: it derives identity only from the persisted application,
    review, job, and target URL, then records that the migration occurred.
    """

    metadata = dict(session.handoff_metadata or {})
    if metadata.get("target_binding"):
        return
    resolved_url = _target_url(application, job, session.current_url)
    if not resolved_url:
        raise OperationalSafetyViolation(
            "handoff_binding_migration_failed",
            "A legacy retained handoff has no authoritative target URL to bind.",
            metadata={"operator_reason_code": "handoff_target_unverifiable"},
        )
    session.current_url = resolved_url
    metadata["target_binding"] = build_handoff_target_binding(
        application,
        job,
        review,
        current_url=resolved_url,
        current_fingerprint=session.current_fingerprint,
        target_resolution_only=bool(metadata.get("target_resolution_only")),
    )
    metadata["target_binding_migration"] = {
        "source": "authoritative_legacy_records",
        "migrated_at": datetime.utcnow().isoformat(),
    }
    session.handoff_metadata = metadata


def _verification_proves_application_target(verification) -> bool:
    """Require browser evidence before converting a resolution-only binding."""
    return bool(
        verification.get("target_resolved")
        and (
            verification.get("application_form_detected")
            or verification.get("trusted_ats_adapter")
        )
    )


def _raise_handoff_conflict(exc: OperationalSafetyViolation):
    from app.services.handoff_session import HandoffSessionConflict

    reason_code = exc.metadata.get("operator_reason_code") or exc.code
    raise HandoffSessionConflict(f"[{exc.code}] {exc} (operator_reason_code={reason_code})")


def install_handoff_safety_integration() -> None:
    """Patch every retained-handoff entry point with the same fail-closed checks."""

    global _INSTALLED, _INSTALLING
    if _INSTALLED or _INSTALLING:
        return
    _INSTALLING = True
    try:
        from app.services import handoff_integration
        from app.services import handoff_session

        original_issue = handoff_session.issue_handoff_session
        original_mark_ready = handoff_session.mark_handoff_ready
        original_begin_resume = handoff_session.begin_handoff_resume

        def guarded_issue_handoff_session(
            db,
            application,
            review,
            *,
            browser_provider,
            browser_session_id=None,
            browser_endpoint=None,
            browser_node_id=None,
            browser_process_id=None,
            browser_profile_path=None,
            active_page_hint=None,
            current_url=None,
            current_fingerprint=None,
            storage_state_path=None,
            storage_state_hash=None,
            screenshot_path=None,
            metadata=None,
            ttl_minutes=None,
        ):
            safe_metadata = dict(metadata or {})
            policy = classify_handoff_reason(review.reason_code)
            if not policy.resumable:
                operator_policy = _operator_final_submit_reason_policy(review, safe_metadata)
                if operator_policy is not None:
                    policy = operator_policy
            if not policy.resumable:
                _raise_handoff_conflict(OperationalSafetyViolation(
                    "handoff_reason_not_resumable",
                    policy.explanation,
                    metadata={"operator_reason_code": policy.operator_reason_code},
                ))

            job = db.query(Job).filter(Job.id == application.job_id).first()
            user = db.query(User).filter(User.id == application.user_id).first()
            if not job or not user:
                _raise_handoff_conflict(OperationalSafetyViolation(
                    "handoff_records_missing",
                    "The retained handoff cannot be created without its job and user records.",
                    metadata={"operator_reason_code": "handoff_records_missing"},
                ))

            dry_run = bool(safe_metadata.get("dry_run", True))
            resolved_url = _target_url(application, job, current_url)
            execution = evaluate_execution_safety(
                db,
                user,
                url=resolved_url,
                dry_run=dry_run,
                requires_handoff=True,
            )
            if not execution.allowed:
                _raise_handoff_conflict(OperationalSafetyViolation(
                    execution.code,
                    execution.reason,
                    metadata=execution.metadata,
                ))

            safe_metadata["handoff_reason_policy"] = policy.to_dict()
            safe_metadata["execution_safety"] = execution.to_dict()
            safe_metadata["target_binding"] = build_handoff_target_binding(
                application,
                job,
                review,
                current_url=resolved_url,
                current_fingerprint=current_fingerprint,
                target_resolution_only=bool(safe_metadata.get("target_resolution_only")),
            )
            return original_issue(
                db,
                application,
                review,
                browser_provider=browser_provider,
                browser_session_id=browser_session_id,
                browser_endpoint=browser_endpoint,
                browser_node_id=browser_node_id,
                browser_process_id=browser_process_id,
                browser_profile_path=browser_profile_path,
                active_page_hint=active_page_hint,
                current_url=resolved_url,
                current_fingerprint=current_fingerprint,
                storage_state_path=storage_state_path,
                storage_state_hash=storage_state_hash,
                screenshot_path=screenshot_path,
                metadata=safe_metadata,
                ttl_minutes=ttl_minutes,
            )

        def guarded_mark_handoff_ready(
            db,
            session,
            *,
            user_id,
            lease_token,
            verification,
        ):
            try:
                application, review, job, user = _records(db, session)
                _ensure_target_binding(session, application, review, job)
                current_url = verification.get("current_url") or session.current_url
                binding = dict((session.handoff_metadata or {}).get("target_binding") or {})
                if binding.get("target_resolution_only"):
                    if _verification_proves_application_target(verification):
                        rebind_resolved_handoff_target(
                            db,
                            session,
                            application,
                            job,
                            review,
                            user,
                            resolved_url=current_url,
                            current_fingerprint=verification.get("current_fingerprint"),
                        )
                    else:
                        # Clearing CAPTCHA/login is not target proof. Keep the handoff
                        # in resolution mode so the worker can prove the application
                        # form or strict ATS surface after the human boundary.
                        dry_run = bool((session.handoff_metadata or {}).get("dry_run", True))
                        execution = evaluate_execution_safety(
                            db,
                            user,
                            url=current_url,
                            dry_run=dry_run,
                            requires_handoff=True,
                        )
                        if not execution.allowed:
                            raise OperationalSafetyViolation(
                                execution.code,
                                execution.reason,
                                metadata=execution.metadata,
                            )
                        require_handoff_target_binding(
                            session,
                            application,
                            job,
                            review,
                            current_url=current_url,
                        )
                else:
                    require_handoff_target_binding(
                        session,
                        application,
                        job,
                        review,
                        current_url=current_url,
                    )
            except OperationalSafetyViolation as exc:
                _raise_handoff_conflict(exc)
            return original_mark_ready(
                db,
                session,
                user_id=user_id,
                lease_token=lease_token,
                verification=verification,
            )

        def guarded_begin_handoff_resume(db, session):
            try:
                application, review, job, user = _records(db, session)
                _ensure_target_binding(session, application, review, job)
                dry_run = bool((session.handoff_metadata or {}).get("dry_run", True))
                execution = evaluate_execution_safety(
                    db,
                    user,
                    url=_target_url(application, job, session.current_url),
                    dry_run=dry_run,
                    requires_handoff=True,
                )
                if not execution.allowed:
                    raise OperationalSafetyViolation(
                        execution.code,
                        execution.reason,
                        metadata=execution.metadata,
                    )
                require_handoff_target_binding(
                    session,
                    application,
                    job,
                    review,
                    current_url=session.current_url,
                )
            except OperationalSafetyViolation as exc:
                _raise_handoff_conflict(exc)
            return original_begin_resume(db, session)

        handoff_session.issue_handoff_session = guarded_issue_handoff_session
        handoff_session.mark_handoff_ready = guarded_mark_handoff_ready
        handoff_session.begin_handoff_resume = guarded_begin_handoff_resume

        # These modules import the functions directly. Patch their bound references so
        # API, Celery, and compatibility paths all share one enforcement point.
        handoff_integration.issue_handoff_session = guarded_issue_handoff_session
        try:
            from app.api import handoffs as handoff_api

            handoff_api.mark_handoff_ready = guarded_mark_handoff_ready
        except ImportError:
            pass
        try:
            from app.tasks import handoffs as handoff_tasks

            handoff_tasks.begin_handoff_resume = guarded_begin_handoff_resume
        except ImportError:
            pass

        _INSTALLED = True
    finally:
        _INSTALLING = False


__all__ = ["install_handoff_safety_integration"]
