"""Deterministic rollback and incident-response drill for application recovery.

The drill runs entirely against an isolated in-memory SQLite database. It never
opens a browser, contacts an employer, or enables real submission. Its purpose
is to prove the operational response to an interrupted worker:

- dry-run attempts become reviewable, never successful
- live or unknown attempts become ``submission_uncertain``
- replay does not create duplicate recovery records
- safety gates remain disabled throughout the drill
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base
from app.models import (
    Application,
    ApplicationEvent,
    Job,
    ManualReviewTask,
    Notification,
    User,
)
from app.models.application import ApplicationAutomationState, ApplicationStatus
from app.services.application_recovery import recover_stale_application_attempts
from app.services.operations_policy import operations_readiness_manifest


DRILL_VERSION = "1.0.0"


def _canonical_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _create_attempt(
    db,
    *,
    user: User,
    suffix: str,
    now: datetime,
    dry_run: bool | None,
) -> Application:
    job = Job(
        external_id=f"recovery-drill-{suffix}",
        title=f"Recovery Drill {suffix.title()}",
        company="Synthetic Recovery Employer",
        url=f"https://job-boards.greenhouse.io/recoverydrill/jobs/{suffix}",
        raw_data={"application_method": "external_url"},
    )
    db.add(job)
    db.flush()
    started_at = now - timedelta(minutes=60)
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applying,
        automation_state=ApplicationAutomationState.applying.value,
        submission_attempt_count=1,
        last_submission_attempt_at=started_at,
        submission_idempotency_key=f"recovery-drill:{suffix}",
        created_at=started_at,
    )
    db.add(application)
    db.flush()
    if dry_run is not None:
        db.add(ApplicationEvent(
            application_id=application.id,
            event_type="application_attempt_started",
            from_state=ApplicationAutomationState.ready_to_apply.value,
            to_state=ApplicationAutomationState.applying.value,
            payload={"dry_run": dry_run, "attempt": 1, "drill": True},
            created_at=started_at,
        ))
    return application


def run_recovery_incident_drill(
    *,
    output_path: str | Path | None = None,
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Execute the isolated drill and optionally retain a signed JSON report."""

    drill_now = (now or datetime.utcnow()).replace(microsecond=0)
    core = get_settings()
    readiness = operations_readiness_manifest()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    db = Session()
    try:
        user = User(
            email="recovery-drill@example.test",
            hashed_password="synthetic-recovery-drill",
            full_name="Synthetic Recovery Drill",
            is_active=True,
        )
        db.add(user)
        db.flush()
        dry_run = _create_attempt(
            db,
            user=user,
            suffix="dry-run",
            now=drill_now,
            dry_run=True,
        )
        live = _create_attempt(
            db,
            user=user,
            suffix="live",
            now=drill_now,
            dry_run=False,
        )
        unknown = _create_attempt(
            db,
            user=user,
            suffix="unknown",
            now=drill_now,
            dry_run=None,
        )
        db.commit()

        first = recover_stale_application_attempts(
            db,
            now=drill_now,
            timeout_minutes=30,
        )
        db.commit()

        application_ids = [dry_run.id, live.id, unknown.id]
        applications = {
            item.id: item
            for item in db.query(Application).filter(Application.id.in_(application_ids)).all()
        }
        review_count_after_first = db.query(ManualReviewTask).count()
        notification_count_after_first = db.query(Notification).count()
        recovery_event_count_after_first = db.query(ApplicationEvent).filter(
            ApplicationEvent.event_type == "stale_application_attempt_recovered"
        ).count()

        replay = recover_stale_application_attempts(
            db,
            now=drill_now + timedelta(minutes=5),
            timeout_minutes=30,
        )
        db.commit()

        final_review_count = db.query(ManualReviewTask).count()
        final_notification_count = db.query(Notification).count()
        final_recovery_event_count = db.query(ApplicationEvent).filter(
            ApplicationEvent.event_type == "stale_application_attempt_recovered"
        ).count()
        submitted_count = db.query(Application).filter(
            Application.automation_state.in_([
                ApplicationAutomationState.submitted.value,
                ApplicationAutomationState.confirmed.value,
            ])
        ).count()

        assertions = {
            "real_submission_disabled": core.allow_real_application_submit is False,
            "autopilot_disabled": readiness.get("autopilot_enabled") is False,
            "three_stale_attempts_recovered": first.get("recovered") == 3,
            "dry_run_routes_to_review": (
                applications[dry_run.id].automation_state
                == ApplicationAutomationState.needs_review.value
            ),
            "live_routes_to_uncertain": (
                applications[live.id].automation_state
                == ApplicationAutomationState.submission_uncertain.value
            ),
            "unknown_routes_to_uncertain": (
                applications[unknown.id].automation_state
                == ApplicationAutomationState.submission_uncertain.value
            ),
            "no_submitted_states": submitted_count == 0,
            "one_review_per_attempt": review_count_after_first == 3,
            "one_notification_per_attempt": notification_count_after_first == 3,
            "one_recovery_event_per_attempt": recovery_event_count_after_first == 3,
            "replay_recovers_nothing": replay.get("recovered") == 0,
            "replay_creates_no_reviews": final_review_count == review_count_after_first,
            "replay_creates_no_notifications": (
                final_notification_count == notification_count_after_first
            ),
            "replay_creates_no_recovery_events": (
                final_recovery_event_count == recovery_event_count_after_first
            ),
            "idempotency_keys_preserved": all(
                applications[item_id].submission_idempotency_key
                for item_id in application_ids
            ),
            "attempt_counts_preserved": all(
                applications[item_id].submission_attempt_count == 1
                for item_id in application_ids
            ),
        }
        passed = all(assertions.values())
        report: Dict[str, Any] = {
            "version": DRILL_VERSION,
            "generated_at": drill_now.isoformat() + "Z",
            "mode": "isolated_in_memory",
            "passed": passed,
            "safety": {
                "browser_opened": False,
                "network_contacted": False,
                "final_submit_clicked": False,
                "real_submission_enabled": core.allow_real_application_submit,
                "autopilot_enabled": readiness.get("autopilot_enabled"),
            },
            "first_recovery": first,
            "replay_recovery": replay,
            "counts": {
                "applications": len(application_ids),
                "manual_reviews": final_review_count,
                "notifications": final_notification_count,
                "recovery_events": final_recovery_event_count,
                "submitted_or_confirmed": submitted_count,
            },
            "assertions": assertions,
        }
        report["report_sha256"] = _canonical_hash(report)

        if output_path is not None:
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report
    finally:
        db.close()
        engine.dispose()


__all__ = ["DRILL_VERSION", "run_recovery_incident_drill"]
