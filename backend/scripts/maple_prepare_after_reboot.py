from __future__ import annotations

import json

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.application import Application, ManualReviewStatus, ManualReviewTask
from app.models.handoff import ManualHandoffSession
from app.tasks.operator_assisted import prepare_operator_assisted_application_task

APP_ID = 247
EXPECTED_URL = "https://jobs.lever.co/getmaple/e8df92c9-23ed-4688-9b2c-4e5db504d24b/apply"


def out(payload):
    print(json.dumps(payload, indent=2, default=str), flush=True)


def main() -> int:
    task = prepare_operator_assisted_application_task.apply_async(
        args=[APP_ID],
        queue="applications",
    )
    print(f"MAPLE_PREPARE_TASK_ID={task.id}", flush=True)

    result = task.get(timeout=300, propagate=False)
    if not isinstance(result, dict):
        out({
            "status": "MAPLE_PREPARE_UNEXPECTED_RESULT",
            "task_state": task.state,
            "result_type": type(result).__name__,
        })
        return 2

    db = SessionLocal()
    try:
        app = db.query(Application).filter(Application.id == APP_ID).one()
        handoffs = (
            db.query(ManualHandoffSession)
            .filter(
                ManualHandoffSession.application_id == APP_ID,
                ManualHandoffSession.challenge_type == "final_submit",
            )
            .order_by(ManualHandoffSession.id.desc())
            .limit(5)
            .all()
        )
        reviews = (
            db.query(ManualReviewTask)
            .filter(
                ManualReviewTask.application_id == APP_ID,
                ManualReviewTask.status.in_([
                    ManualReviewStatus.open.value,
                    ManualReviewStatus.in_progress.value,
                ]),
            )
            .order_by(ManualReviewTask.id.desc())
            .limit(5)
            .all()
        )

        safe_log = []
        for item in result.get("log") or []:
            action = str(item.get("action") or "")
            if "handoff" in action or "operator" in action:
                safe_log.append({
                    key: value
                    for key, value in item.items()
                    if key not in {"resume_token", "lease_token", "browser_endpoint"}
                })

        latest = handoffs[0] if handoffs else None
        current_url = str(getattr(latest, "current_url", "") or "") if latest else None

        out({
            "status": "MAPLE_FRESH_PREPARE_RESULT",
            "task_id": task.id,
            "task_state": task.state,
            "success": result.get("success"),
            "ready_to_submit": result.get("ready_to_submit"),
            "requires_manual_review": result.get("requires_manual_review"),
            "message": result.get("message") or result.get("error"),
            "operator_assisted": result.get("operator_assisted"),
            "automated_submission_authorized": result.get("automated_submission_authorized"),
            "final_submit_clicked_by_jobtomatik": result.get("final_submit_clicked_by_jobtomatik"),
            "result_handoff_public_id": result.get("handoff_public_id"),
            "result_handoff_expires_at": result.get("handoff_expires_at"),
            "application_status": app.status,
            "automation_state": app.automation_state,
            "latest_handoff": None if latest is None else {
                "public_id": latest.public_id,
                "manual_review_id": latest.manual_review_id,
                "status": latest.status,
                "challenge_type": latest.challenge_type,
                "expires_at": latest.expires_at,
                "current_url": latest.current_url,
                "current_fingerprint": latest.current_fingerprint,
                "browser_provider": latest.browser_provider,
            },
            "latest_handoff_is_maple": current_url == EXPECTED_URL,
            "open_reviews": [
                {
                    "id": review.id,
                    "reason_code": review.reason_code,
                    "status": review.status,
                }
                for review in reviews
            ],
            "handoff_log": safe_log,
        })
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
