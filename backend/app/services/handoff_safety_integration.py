"""Install Day 6 safety guards around retained-browser handoff lifecycle calls."""

from __future__ import annotations

from app.models.application import Application, ManualReviewTask
from app.models.handoff import ManualHandoffSession
from app.models.job import Job
from app.models.user import User
from app.services.operational_safety import (
    OperationalSafetyViolation,
    build_handoff_target_binding,
    classify_handoff_reason,
    evaluate_execution_safety,
    require_handoff_target_binding,
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
            policy = classify_handoff_reason(review.reason_code)
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

            safe_metadata = dict(metadata or {})
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
                application, review, job, _user = _records(db, session)
                require_handoff_target_binding(
                    session,
                    application,
                    job,
                    review,
                    current_url=verification.get("current_url") or session.current_url,
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
