from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session, selectinload

from app.models.application import (
    Application,
    ApplicationEvent,
    FollowUp,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.evaluation import OpportunityEvaluation
from app.models.intelligence import RecruiterContact, RecruiterInteraction
from app.models.job import Job


PIPELINE_ORDER = [
    ("pending", "Pending"),
    ("applying", "Applying"),
    ("applied", "Applied"),
    ("interviewing", "Interviewing"),
    ("offer", "Offer"),
    ("rejected", "Rejected"),
    ("withdrawn", "Withdrawn"),
]

OPEN_REVIEW_STATUSES = {
    ManualReviewStatus.open.value,
    ManualReviewStatus.in_progress.value,
}
CLOSED_FOLLOWUP_STATUSES = {"sent", "cancelled"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _enum_value(value: Any) -> str:
    return str(value.value if hasattr(value, "value") else value)


def _application_sort_key(application: Application) -> datetime:
    candidates = [
        _as_utc(application.offer_received_at),
        _as_utc(application.interview_at),
        _as_utc(application.applied_at),
        _as_utc(application.updated_at),
        _as_utc(application.created_at),
    ]
    return next((value for value in candidates if value is not None), datetime.min.replace(tzinfo=timezone.utc))


def _event_title(event_type: str) -> str:
    known = {
        "application_status_changed": "Application status changed",
        "application_submitted": "Application submitted",
        "submission_confirmed": "Submission confirmed",
        "manual_review_created": "Manual review requested",
        "followup_draft_prepared": "Follow-up draft prepared",
        "supervised_followup_approved": "Recruiter follow-up approved",
        "supervised_followup_sent": "Recruiter follow-up sent",
        "supervised_followup_delivery_uncertain": "Recruiter follow-up delivery uncertain",
        "bounded_submission_handoff_created": "Submission handoff prepared",
        "bounded_submission_handoff_reviewed": "Submission handoff reviewed",
    }
    return known.get(event_type, event_type.replace("_", " ").strip().title())


def _pipeline_item(application: Application) -> dict[str, Any]:
    job = application.job
    latest_event = application.events[-1] if application.events else None
    open_reviews = sum(
        1
        for review in application.manual_reviews
        if str(review.status) in OPEN_REVIEW_STATUSES
    )
    active_followups = sum(
        1 for followup in application.followups if str(followup.status) not in CLOSED_FOLLOWUP_STATUSES
    )
    return {
        "application_id": application.id,
        "job_id": application.job_id,
        "title": str(job.title if job else "Unknown position"),
        "company": str(job.company if job else "Unknown company"),
        "location": job.location if job else None,
        "status": _enum_value(application.status),
        "automation_state": str(application.automation_state or "preparing"),
        "application_target_status": str(application.application_target_status or "unresolved"),
        "applied_at": application.applied_at,
        "interview_at": application.interview_at,
        "offer_received_at": application.offer_received_at,
        "salary_offered": application.salary_offered,
        "latest_event_type": latest_event.event_type if latest_event else None,
        "latest_event_at": latest_event.created_at if latest_event else None,
        "open_review_count": open_reviews,
        "followup_count": active_followups,
    }


def _build_pipeline(applications: list[Application], per_status_limit: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[Application]] = {status: [] for status, _ in PIPELINE_ORDER}
    for application in applications:
        grouped.setdefault(_enum_value(application.status), []).append(application)

    columns: list[dict[str, Any]] = []
    known_statuses = {status for status, _ in PIPELINE_ORDER}
    ordered_statuses = list(PIPELINE_ORDER)
    ordered_statuses.extend(
        (status, status.replace("_", " ").title())
        for status in sorted(grouped)
        if status not in known_statuses
    )
    for status, label in ordered_statuses:
        members = sorted(grouped.get(status, []), key=_application_sort_key, reverse=True)
        columns.append(
            {
                "status": status,
                "label": label,
                "count": len(members),
                "items": [_pipeline_item(item) for item in members[:per_status_limit]],
            }
        )
    return columns


def _timeline_application_items(
    db: Session,
    *,
    user_id: int,
    application_lookup: dict[int, Application],
    limit: int,
) -> list[dict[str, Any]]:
    events = (
        db.query(ApplicationEvent)
        .join(Application, Application.id == ApplicationEvent.application_id)
        .filter(Application.user_id == user_id)
        .order_by(ApplicationEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    result: list[dict[str, Any]] = []
    for event in events:
        occurred_at = _as_utc(event.created_at)
        application = application_lookup.get(event.application_id)
        if occurred_at is None or application is None:
            continue
        job = application.job
        state_bits = [bit for bit in [event.from_state, event.to_state] if bit]
        state_summary = " → ".join(state_bits) if state_bits else None
        result.append(
            {
                "kind": "application_event",
                "occurred_at": occurred_at,
                "title": _event_title(event.event_type),
                "summary": state_summary,
                "application_id": application.id,
                "recruiter_contact_id": None,
                "job_id": application.job_id,
                "company": job.company if job else None,
                "event_type": event.event_type,
                "from_state": event.from_state,
                "to_state": event.to_state,
                "action_url": f"/applications/{application.id}",
            }
        )
    return result


def _timeline_recruiter_items(
    db: Session,
    *,
    user_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    interactions = (
        db.query(RecruiterInteraction)
        .join(RecruiterContact, RecruiterContact.id == RecruiterInteraction.contact_id)
        .filter(RecruiterContact.user_id == user_id)
        .order_by(RecruiterInteraction.occurred_at.desc())
        .limit(limit)
        .all()
    )
    contacts = {
        contact.id: contact
        for contact in db.query(RecruiterContact)
        .filter(RecruiterContact.user_id == user_id)
        .all()
    }
    result: list[dict[str, Any]] = []
    for interaction in interactions:
        occurred_at = _as_utc(interaction.occurred_at)
        contact = contacts.get(interaction.contact_id)
        if occurred_at is None or contact is None:
            continue
        interaction_type = str(interaction.interaction_type or "interaction")
        direction = str(interaction.direction or "").strip()
        result.append(
            {
                "kind": "recruiter_interaction",
                "occurred_at": occurred_at,
                "title": f"{interaction_type.replace('_', ' ').title()} with {contact.full_name}",
                "summary": str(interaction.summary or "")[:500] or None,
                "application_id": interaction.application_id,
                "recruiter_contact_id": contact.id,
                "job_id": None,
                "company": contact.company,
                "event_type": interaction_type,
                "from_state": direction or None,
                "to_state": None,
                "action_url": "/operations",
            }
        )
    return result


def _build_timeline(
    db: Session,
    *,
    user_id: int,
    applications: list[Application],
    limit: int,
) -> list[dict[str, Any]]:
    lookup = {application.id: application for application in applications}
    candidates = _timeline_application_items(
        db,
        user_id=user_id,
        application_lookup=lookup,
        limit=limit,
    ) + _timeline_recruiter_items(db, user_id=user_id, limit=limit)
    candidates.sort(key=lambda item: item["occurred_at"], reverse=True)
    return candidates[:limit]


def _build_evaluation_comparison(
    db: Session,
    *,
    user_id: int,
    applications: list[Application],
    limit: int,
) -> list[dict[str, Any]]:
    evaluations = (
        db.query(OpportunityEvaluation)
        .filter(OpportunityEvaluation.user_id == user_id)
        .order_by(OpportunityEvaluation.created_at.desc())
        .limit(max(limit * 4, limit))
        .all()
    )
    application_lookup = {item.id: item for item in applications}
    job_ids = {item.job_id for item in evaluations if item.job_id is not None}
    job_lookup = {
        job.id: job for job in db.query(Job).filter(Job.id.in_(job_ids)).all()
    } if job_ids else {}

    seen: set[tuple[str, int]] = set()
    result: list[dict[str, Any]] = []
    for evaluation in evaluations:
        if evaluation.application_id is not None:
            key = ("application", evaluation.application_id)
        elif evaluation.job_id is not None:
            key = ("job", evaluation.job_id)
        else:
            key = ("evaluation", evaluation.id)
        if key in seen:
            continue
        seen.add(key)

        application = application_lookup.get(evaluation.application_id) if evaluation.application_id else None
        job = application.job if application and application.job else job_lookup.get(evaluation.job_id)
        result.append(
            {
                "evaluation_id": evaluation.id,
                "job_id": evaluation.job_id,
                "application_id": evaluation.application_id,
                "title": str(job.title if job else "Unlinked opportunity"),
                "company": str(job.company if job else "Unknown company"),
                "weighted_score": float(evaluation.weighted_score or 0.0),
                "recommendation": str(evaluation.recommendation or "unknown"),
                "legitimacy_status": str(evaluation.legitimacy_status or "unknown"),
                "hard_blockers": list(evaluation.hard_blockers or []),
                "dimension_scores": {
                    str(name): float(score)
                    for name, score in dict(evaluation.dimension_scores or {}).items()
                },
                "created_at": evaluation.created_at,
                "action_url": (
                    f"/applications/{evaluation.application_id}"
                    if evaluation.application_id is not None
                    else None
                ),
            }
        )
        if len(result) >= limit:
            break
    return result


def _priority_rank(priority: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(priority, 3)


def _build_agenda(
    db: Session,
    *,
    user_id: int,
    applications: list[Application],
    now: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    agenda: list[dict[str, Any]] = []
    application_lookup = {item.id: item for item in applications}

    for application in applications:
        interview_at = _as_utc(application.interview_at)
        if interview_at and interview_at <= window_end and _enum_value(application.status) in {"interviewing", "offer"}:
            job = application.job
            overdue = interview_at < now
            agenda.append(
                {
                    "item_type": "interview",
                    "scheduled_at": interview_at,
                    "priority": "high" if overdue or interview_at <= now + timedelta(days=1) else "medium",
                    "title": f"Interview: {job.title if job else 'Application'}",
                    "subtitle": job.company if job else None,
                    "status": _enum_value(application.status),
                    "application_id": application.id,
                    "recruiter_contact_id": None,
                    "followup_id": None,
                    "action_url": f"/applications/{application.id}",
                    "overdue": overdue,
                }
            )

    contacts = (
        db.query(RecruiterContact)
        .filter(
            RecruiterContact.user_id == user_id,
            RecruiterContact.next_followup_at.is_not(None),
            RecruiterContact.next_followup_at <= window_end,
        )
        .all()
    )
    for contact in contacts:
        scheduled_at = _as_utc(contact.next_followup_at)
        if scheduled_at is None:
            continue
        overdue = scheduled_at < now
        agenda.append(
            {
                "item_type": "recruiter_followup",
                "scheduled_at": scheduled_at,
                "priority": "high" if overdue else "medium",
                "title": f"Recruiter follow-up: {contact.full_name}",
                "subtitle": contact.company,
                "status": contact.relationship_stage,
                "application_id": None,
                "recruiter_contact_id": contact.id,
                "followup_id": None,
                "action_url": "/followup-review",
                "overdue": overdue,
            }
        )

    followups = (
        db.query(FollowUp)
        .join(Application, Application.id == FollowUp.application_id)
        .filter(
            Application.user_id == user_id,
            FollowUp.status.notin_(list(CLOSED_FOLLOWUP_STATUSES)),
            FollowUp.scheduled_at <= window_end,
        )
        .all()
    )
    for followup in followups:
        scheduled_at = _as_utc(followup.scheduled_at)
        application = application_lookup.get(followup.application_id)
        if scheduled_at is None or application is None:
            continue
        job = application.job
        overdue = scheduled_at < now
        approved = str(followup.status) == "approved"
        agenda.append(
            {
                "item_type": "followup_delivery" if approved else "followup_draft",
                "scheduled_at": scheduled_at,
                "priority": "high" if approved and overdue else "medium",
                "title": (
                    "Approved follow-up due"
                    if approved
                    else "Follow-up draft needs review"
                ),
                "subtitle": f"{job.title if job else 'Application'} · {job.company if job else 'Unknown company'}",
                "status": str(followup.status),
                "application_id": application.id,
                "recruiter_contact_id": followup.recruiter_contact_id,
                "followup_id": followup.id,
                "action_url": "/followup-review",
                "overdue": overdue,
            }
        )

    reviews = (
        db.query(ManualReviewTask)
        .join(Application, Application.id == ManualReviewTask.application_id)
        .filter(
            Application.user_id == user_id,
            ManualReviewTask.status.in_(list(OPEN_REVIEW_STATUSES)),
        )
        .all()
    )
    for review in reviews:
        application = application_lookup.get(review.application_id)
        if application is None:
            continue
        scheduled_at = _as_utc(review.expires_at) or _as_utc(review.created_at) or now
        job = application.job
        agenda.append(
            {
                "item_type": "manual_review",
                "scheduled_at": scheduled_at,
                "priority": "high",
                "title": review.summary,
                "subtitle": f"{job.title if job else 'Application'} · {job.company if job else 'Unknown company'}",
                "status": str(review.status),
                "application_id": application.id,
                "recruiter_contact_id": None,
                "followup_id": None,
                "action_url": f"/applications/{application.id}",
                "overdue": scheduled_at < now,
            }
        )

    agenda.sort(
        key=lambda item: (
            _priority_rank(item["priority"]),
            0 if item["overdue"] else 1,
            item["scheduled_at"],
            item["title"],
        )
    )
    return agenda


def build_operations_workspace(
    db: Session,
    *,
    user_id: int,
    agenda_days: int = 14,
    timeline_limit: int = 100,
    evaluation_limit: int = 20,
    pipeline_limit_per_status: int = 50,
) -> dict[str, Any]:
    now = utcnow()
    window_end = now + timedelta(days=agenda_days)
    applications = (
        db.query(Application)
        .options(
            selectinload(Application.job),
            selectinload(Application.events),
            selectinload(Application.manual_reviews),
            selectinload(Application.followups),
        )
        .filter(Application.user_id == user_id)
        .all()
    )

    pipeline = _build_pipeline(applications, pipeline_limit_per_status)
    timeline = _build_timeline(
        db,
        user_id=user_id,
        applications=applications,
        limit=timeline_limit,
    )
    evaluations = _build_evaluation_comparison(
        db,
        user_id=user_id,
        applications=applications,
        limit=evaluation_limit,
    )
    agenda = _build_agenda(
        db,
        user_id=user_id,
        applications=applications,
        now=now,
        window_end=window_end,
    )

    status_counts = {
        column["status"]: int(column["count"])
        for column in pipeline
    }
    open_reviews = sum(item["open_review_count"] for column in pipeline for item in column["items"])
    overdue_agenda = sum(1 for item in agenda if item["overdue"])
    return {
        "generated_at": now,
        "agenda_window_start": now,
        "agenda_window_end": window_end,
        "summary": {
            "applications": len(applications),
            "active_applications": sum(
                count
                for status, count in status_counts.items()
                if status not in {"rejected", "withdrawn"}
            ),
            "interviewing": status_counts.get("interviewing", 0),
            "offers": status_counts.get("offer", 0),
            "open_reviews": open_reviews,
            "agenda_items": len(agenda),
            "overdue_agenda_items": overdue_agenda,
            "evaluation_candidates": len(evaluations),
            "timeline_items": len(timeline),
        },
        "pipeline": pipeline,
        "timeline": timeline,
        "evaluations": evaluations,
        "agenda": agenda,
    }
