from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationEvent, ApplicationStatus, FollowUp
from app.models.evaluation import OpportunityEvaluation
from app.models.intelligence import CareerMemory, KnowledgeNode


_MESSAGE_RULES: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    (
        "rejection",
        (
            "not moving forward",
            "will not be moving forward",
            "decided not to proceed",
            "pursue other candidates",
            "other candidates whose qualifications",
            "we regret to inform",
            "unfortunately, we",
            "not selected",
        ),
        ApplicationStatus.rejected.value,
    ),
    (
        "offer",
        (
            "pleased to offer",
            "extend an offer",
            "offer letter",
            "job offer",
            "employment offer",
            "formal offer",
        ),
        ApplicationStatus.offer.value,
    ),
    (
        "interview",
        (
            "schedule an interview",
            "interview availability",
            "invite you to interview",
            "next round",
            "next interview",
            "meet with the team",
            "meet with our team",
            "schedule a call",
            "interview",
        ),
        ApplicationStatus.interviewing.value,
    ),
    (
        "assessment",
        (
            "coding challenge",
            "take-home assignment",
            "take home assignment",
            "technical assessment",
            "online assessment",
            "case study",
            "assessment",
        ),
        None,
    ),
    (
        "application_received",
        (
            "application received",
            "received your application",
            "thank you for applying",
            "thanks for applying",
            "application has been received",
        ),
        None,
    ),
    (
        "status_update",
        (
            "application status",
            "still reviewing",
            "under review",
            "reviewing your application",
            "update on your application",
        ),
        None,
    ),
)


_ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    ApplicationStatus.pending.value: {
        ApplicationStatus.applied.value,
        ApplicationStatus.interviewing.value,
        ApplicationStatus.offer.value,
        ApplicationStatus.rejected.value,
        ApplicationStatus.withdrawn.value,
    },
    ApplicationStatus.applying.value: {
        ApplicationStatus.applied.value,
        ApplicationStatus.interviewing.value,
        ApplicationStatus.offer.value,
        ApplicationStatus.rejected.value,
        ApplicationStatus.withdrawn.value,
    },
    ApplicationStatus.applied.value: {
        ApplicationStatus.interviewing.value,
        ApplicationStatus.offer.value,
        ApplicationStatus.rejected.value,
        ApplicationStatus.withdrawn.value,
    },
    ApplicationStatus.interviewing.value: {
        ApplicationStatus.offer.value,
        ApplicationStatus.rejected.value,
        ApplicationStatus.withdrawn.value,
    },
    ApplicationStatus.offer.value: {
        ApplicationStatus.rejected.value,
        ApplicationStatus.withdrawn.value,
    },
    ApplicationStatus.rejected.value: set(),
    ApplicationStatus.withdrawn.value: set(),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def employer_message_hash(
    *,
    sender_email: str,
    subject: str,
    body: str,
    received_at: datetime,
) -> str:
    canonical = "\n".join(
        [
            sender_email.strip().casefold(),
            normalize_text(subject).casefold(),
            normalize_text(body),
            ensure_aware(received_at).isoformat(),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_employer_message(subject: str, body: str) -> dict[str, Any]:
    """Classify an inbound employer message with deterministic, inspectable rules.

    The classifier intentionally proposes, but never applies, application-status
    transitions. Any status mutation requires a separate authenticated confirmation.
    """
    text = f"{normalize_text(subject)} {normalize_text(body)}".casefold()
    best_category = "other"
    best_status = None
    best_matches: list[str] = []

    for category, phrases, proposed_status in _MESSAGE_RULES:
        matches = [phrase for phrase in phrases if phrase in text]
        if not matches:
            continue
        if len(matches) > len(best_matches):
            best_category = category
            best_status = proposed_status
            best_matches = matches

    if best_matches:
        confidence = min(0.99, 0.72 + 0.08 * (len(best_matches) - 1))
    else:
        outreach_markers = (
            "talent acquisition",
            "recruiter",
            "career opportunity",
            "position with",
        )
        outreach_matches = [marker for marker in outreach_markers if marker in text]
        if outreach_matches:
            best_category = "recruiter_outreach"
            best_matches = outreach_matches
            confidence = min(0.9, 0.68 + 0.06 * (len(outreach_matches) - 1))
        else:
            confidence = 0.35

    return {
        "category": best_category,
        "confidence": round(float(confidence), 2),
        "matched_phrases": best_matches,
        "proposed_status": best_status,
        "requires_confirmation": bool(best_status),
        "classifier_version": "post-application-rules-v1",
    }


def can_transition_application_status(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in _ALLOWED_STATUS_TRANSITIONS.get(current, set())


def recent_message_duplicate(
    db: Session,
    *,
    application_id: int,
    message_hash: str,
) -> ApplicationEvent | None:
    events = (
        db.query(ApplicationEvent)
        .filter(
            ApplicationEvent.application_id == application_id,
            ApplicationEvent.event_type == "inbound_employer_message",
        )
        .order_by(ApplicationEvent.created_at.desc())
        .limit(250)
        .all()
    )
    for event in events:
        payload = dict(event.payload or {})
        if payload.get("message_hash") == message_hash:
            return event
    return None


def _requirements_from_job(application: Application) -> list[str]:
    job = application.job
    source = normalize_text(getattr(job, "requirements", None))
    if not source:
        source = normalize_text(getattr(job, "description", None))
    if not source:
        return []

    chunks = re.split(r"(?:\n|[.;])\s*", source)
    candidates: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        item = normalize_text(chunk)
        if len(item) < 18 or len(item) > 280:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(item)
        if len(candidates) >= 8:
            break
    return candidates


def build_interview_prep_packet(
    db: Session,
    *,
    user_id: int,
    application: Application,
) -> dict[str, Any]:
    """Build a source-backed preparation packet without inventing candidate facts."""
    job = application.job
    requirements = _requirements_from_job(application)
    memories = (
        db.query(CareerMemory)
        .filter(
            CareerMemory.user_id == user_id,
            CareerMemory.is_active.is_(True),
        )
        .order_by(CareerMemory.confidence.desc(), CareerMemory.updated_at.desc())
        .limit(10)
        .all()
    )
    company_nodes = (
        db.query(KnowledgeNode)
        .filter(
            KnowledgeNode.user_id == user_id,
            KnowledgeNode.node_type == "company",
            KnowledgeNode.label.ilike(f"%{job.company}%"),
        )
        .order_by(KnowledgeNode.confidence.desc(), KnowledgeNode.updated_at.desc())
        .limit(8)
        .all()
    )

    evidence_points = [
        {
            "content": memory.content,
            "kind": memory.kind,
            "confidence": float(memory.confidence),
            "source": memory.source,
            "source_ref": memory.source_ref,
        }
        for memory in memories
    ]
    company_context = [
        {
            "label": node.label,
            "payload": node.payload or {},
            "confidence": float(node.confidence),
            "source_url": node.source_url,
        }
        for node in company_nodes
    ]

    question_prompts: list[str] = []
    for requirement in requirements[:5]:
        question_prompts.append(
            f"Prepare one concrete, truthful example that demonstrates: {requirement}"
        )
    question_prompts.extend(
        [
            f"Why is {job.company} and this {job.title} role a strong fit based only on verified experience?",
            "Prepare one example of a difficult decision, the evidence used, and the measurable result.",
            "Prepare two questions about team expectations, success measures, and the first 90 days.",
        ]
    )

    return {
        "application_id": application.id,
        "generated_at": utc_now(),
        "role": job.title,
        "company": job.company,
        "location": job.location,
        "interview_at": ensure_aware(application.interview_at),
        "requirements": requirements,
        "candidate_evidence": evidence_points,
        "company_context": company_context,
        "question_prompts": question_prompts,
        "provenance_policy": (
            "Candidate claims must come from the attached career-memory evidence or be confirmed by the user."
        ),
    }


def build_offer_comparison(db: Session, *, user_id: int) -> dict[str, Any]:
    applications = (
        db.query(Application)
        .filter(
            Application.user_id == user_id,
            Application.status == ApplicationStatus.offer,
        )
        .order_by(Application.offer_received_at.desc(), Application.created_at.desc())
        .all()
    )

    rows: list[dict[str, Any]] = []
    for application in applications:
        job = application.job
        evaluation = (
            db.query(OpportunityEvaluation)
            .filter(
                OpportunityEvaluation.user_id == user_id,
                OpportunityEvaluation.application_id == application.id,
            )
            .order_by(OpportunityEvaluation.created_at.desc())
            .first()
        )
        market_midpoint = None
        if job.salary_min is not None and job.salary_max is not None:
            market_midpoint = round((job.salary_min + job.salary_max) / 2)
        rows.append(
            {
                "application_id": application.id,
                "job_id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "salary_offered": application.salary_offered,
                "salary_currency": job.salary_currency,
                "market_salary_min": job.salary_min,
                "market_salary_max": job.salary_max,
                "market_salary_midpoint": market_midpoint,
                "weighted_fit_score": (
                    float(evaluation.weighted_score) if evaluation is not None else None
                ),
                "recommendation": evaluation.recommendation if evaluation is not None else None,
                "offer_received_at": ensure_aware(application.offer_received_at),
                "notes": application.notes,
            }
        )

    salary_rows = [row for row in rows if row["salary_offered"] is not None]
    fit_rows = [row for row in rows if row["weighted_fit_score"] is not None]
    return {
        "offers": rows,
        "offer_count": len(rows),
        "highest_salary_application_id": (
            max(salary_rows, key=lambda row: row["salary_offered"])["application_id"]
            if salary_rows
            else None
        ),
        "highest_fit_application_id": (
            max(fit_rows, key=lambda row: row["weighted_fit_score"])["application_id"]
            if fit_rows
            else None
        ),
        "decision_note": (
            "Comparison exposes recorded compensation and existing evaluation evidence; it does not choose an offer for the user."
        ),
    }


def upsert_outcome_memory(
    db: Session,
    *,
    user_id: int,
    application: Application,
    event: ApplicationEvent,
    outcome: str,
    detail: str | None,
) -> CareerMemory:
    job = application.job
    key = f"application_outcome:{application.id}"
    detail_text = normalize_text(detail)
    content = f"{job.company} — {job.title}: {outcome}."
    if detail_text:
        content += f" Recorded detail: {detail_text}"
    memory = (
        db.query(CareerMemory)
        .filter(CareerMemory.user_id == user_id, CareerMemory.key == key)
        .first()
    )
    source_ref = f"post_application:application:{application.id}:event:{event.id}"
    metadata = {
        "application_id": application.id,
        "job_id": job.id,
        "company": job.company,
        "title": job.title,
        "outcome": outcome,
        "event_id": event.id,
        "learning_scope": "observed_outcome_only",
    }
    if memory is None:
        memory = CareerMemory(
            user_id=user_id,
            kind="application_outcome",
            key=key,
            content=content,
            confidence=1.0,
            source="post_application_outcome",
            source_ref=source_ref,
            memory_metadata=metadata,
            is_active=True,
        )
        db.add(memory)
    else:
        memory.content = content
        memory.confidence = 1.0
        memory.source = "post_application_outcome"
        memory.source_ref = source_ref
        memory.memory_metadata = metadata
        memory.is_active = True
    return memory


def post_application_summary(db: Session, *, user_id: int) -> dict[str, Any]:
    applications = (
        db.query(Application)
        .filter(Application.user_id == user_id)
        .order_by(Application.updated_at.desc(), Application.created_at.desc())
        .all()
    )
    eligible = [
        app
        for app in applications
        if app.status
        in {
            ApplicationStatus.applied,
            ApplicationStatus.interviewing,
            ApplicationStatus.offer,
            ApplicationStatus.rejected,
            ApplicationStatus.withdrawn,
        }
    ]
    app_ids = [app.id for app in eligible]
    events = []
    if app_ids:
        events = (
            db.query(ApplicationEvent)
            .filter(
                ApplicationEvent.application_id.in_(app_ids),
                ApplicationEvent.event_type.in_(
                    [
                        "inbound_employer_message",
                        "post_application_status_confirmed",
                        "interview_scheduled",
                        "application_outcome_recorded",
                    ]
                ),
            )
            .order_by(ApplicationEvent.created_at.desc())
            .limit(80)
            .all()
        )

    followup_count = 0
    if app_ids:
        followup_count = (
            db.query(FollowUp)
            .filter(
                FollowUp.application_id.in_(app_ids),
                FollowUp.status.in_(
                    ["needs_recipient", "draft", "approved", "delivery_uncertain"]
                ),
            )
            .count()
        )

    return {
        "generated_at": utc_now(),
        "summary": {
            "post_application_total": len(eligible),
            "applied": sum(1 for app in eligible if app.status == ApplicationStatus.applied),
            "interviewing": sum(
                1 for app in eligible if app.status == ApplicationStatus.interviewing
            ),
            "offers": sum(1 for app in eligible if app.status == ApplicationStatus.offer),
            "rejected": sum(1 for app in eligible if app.status == ApplicationStatus.rejected),
            "withdrawn": sum(
                1 for app in eligible if app.status == ApplicationStatus.withdrawn
            ),
            "followups_requiring_attention": followup_count,
        },
        "applications": [
            {
                "application_id": app.id,
                "job_id": app.job.id,
                "title": app.job.title,
                "company": app.job.company,
                "status": app.status.value if hasattr(app.status, "value") else str(app.status),
                "applied_at": ensure_aware(app.applied_at),
                "interview_at": ensure_aware(app.interview_at),
                "offer_received_at": ensure_aware(app.offer_received_at),
                "salary_offered": app.salary_offered,
            }
            for app in eligible
        ],
        "events": [
            {
                "event_id": event.id,
                "application_id": event.application_id,
                "event_type": event.event_type,
                "from_state": event.from_state,
                "to_state": event.to_state,
                "payload": event.payload or {},
                "created_at": ensure_aware(event.created_at),
            }
            for event in events
        ],
    }
