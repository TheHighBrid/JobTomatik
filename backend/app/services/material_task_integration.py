from __future__ import annotations

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ManualReviewReason,
)
from app.models.job import Job
from app.models.user import User
from app.services.application_state import (
    create_manual_review_task,
    normalize_state,
    transition_application_state,
)
from app.services.autonomous_material_verification import (
    generate_autonomy_verified_material,
)


_INSTALLED = False
_ORIGINAL_RUN = None


def install_verified_material_task_integration() -> None:
    """Replace legacy cover-letter task output with Day 31 verified material."""
    global _INSTALLED, _ORIGINAL_RUN
    if _INSTALLED:
        return

    from app.tasks import applications as application_tasks

    task = application_tasks.generate_cover_letter_task
    _ORIGINAL_RUN = task.run

    def wrapped_run(application_id: int, **_kwargs):
        db = application_tasks.SessionLocal()
        try:
            application = (
                db.query(Application)
                .filter(Application.id == application_id)
                .with_for_update()
                .first()
            )
            if not application:
                return {"error": "Application not found"}
            job = db.query(Job).filter(Job.id == application.job_id).first()
            user = db.query(User).filter(User.id == application.user_id).first()
            if not job or not user:
                return {"error": "Missing job or user"}

            material, verification = generate_autonomy_verified_material(
                db,
                application,
                user,
                job,
                material_type="cover_letter",
            )
            warnings = list(material.warnings or [])
            current_state = normalize_state(application.automation_state)
            requires_review = bool(verification["requires_manual_review"])

            event_payload = {
                "material_id": material.id,
                "material_version": material.version,
                "material_status": material.status,
                "warning_count": len(warnings),
                "verification_policy": verification["policy_version"],
                "verification_sha256": verification["verification_sha256"],
                "content_sha256": verification["content_sha256"],
                "resume_sha256": verification["resume"].get("sha256"),
                "blockers": list(verification["blockers"]),
            }

            if requires_review:
                create_manual_review_task(
                    db,
                    application,
                    ManualReviewReason.validation_error,
                    "Application materials require review before autonomous use.",
                    details={
                        **event_payload,
                        "material_type": material.material_type,
                        "warnings": warnings,
                        "advisories": list(verification["advisories"]),
                        "stage": "day31_autonomous_material_verification",
                    },
                    blocking_url=job.url,
                    target_state=ApplicationAutomationState.needs_review,
                )
            elif current_state == ApplicationAutomationState.preparing.value:
                transition_application_state(
                    db,
                    application,
                    ApplicationAutomationState.ready_to_apply,
                    "autonomous_material_verified",
                    event_payload,
                )
            else:
                db.add(
                    ApplicationEvent(
                        application_id=application.id,
                        event_type="autonomous_material_verified",
                        from_state=current_state,
                        to_state=current_state,
                        payload=event_payload,
                    )
                )

            db.commit()
            return {
                "application_id": application_id,
                "generated": True,
                "material_id": material.id,
                "material_version": material.version,
                "material_status": material.status,
                "claim_count": len(material.claims or []),
                "warning_count": len(warnings),
                "requires_manual_review": requires_review,
                "verification_policy": verification["policy_version"],
                "verification_sha256": verification["verification_sha256"],
                "content_sha256": verification["content_sha256"],
                "resume_sha256": verification["resume"].get("sha256"),
                "blockers": list(verification["blockers"]),
            }
        except Exception as exc:
            db.rollback()
            raise task.retry(exc=exc, countdown=30, max_retries=2)
        finally:
            db.close()

    task.run = wrapped_run
    _INSTALLED = True
