from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application, ApplicationEvent, ApplicationStatus
from app.models.intelligence import RecruiterContact, RecruiterInteraction
from app.models.user import User
from app.schemas.post_application import (
    ConfirmMessageStatusRequest,
    EmployerMessageCreate,
    EmployerMessageOut,
    InterviewPrepOut,
    InterviewScheduleOut,
    InterviewScheduleRequest,
    OfferComparisonOut,
    OutcomeRecordOut,
    OutcomeRecordRequest,
    PostApplicationWorkspaceOut,
    StatusConfirmationOut,
)
from app.services.post_application_operations import (
    build_interview_prep_packet,
    build_offer_comparison,
    can_transition_application_status,
    classify_employer_message,
    employer_message_hash,
    ensure_aware,
    post_application_summary,
    recent_message_duplicate,
    upsert_outcome_memory,
    utc_now,
)


router = APIRouter(prefix="/post-application", tags=["post-application"])


def _status_value(application: Application) -> str:
    value = application.status
    return value.value if hasattr(value, "value") else str(value)


def _get_owned_application(db: Session, user_id: int, application_id: int) -> Application:
    application = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == user_id)
        .first()
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def _event_to_message_out(event: ApplicationEvent, *, duplicate: bool) -> EmployerMessageOut:
    payload = dict(event.payload or {})
    return EmployerMessageOut(
        event_id=event.id,
        application_id=event.application_id,
        message_hash=str(payload.get("message_hash") or ""),
        duplicate=duplicate,
        sender_name=payload.get("sender_name"),
        sender_email=str(payload.get("sender_email") or ""),
        subject=str(payload.get("subject") or ""),
        received_at=payload.get("received_at") or event.created_at or utc_now(),
        source_reference=str(payload.get("source_reference") or ""),
        classification=dict(payload.get("classification") or {}),
        recruiter_contact_id=payload.get("recruiter_contact_id"),
        recruiter_interaction_id=payload.get("recruiter_interaction_id"),
    )


@router.get("/workspace", response_model=PostApplicationWorkspaceOut)
def get_post_application_workspace(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return post_application_summary(db, user_id=current_user.id)


@router.post(
    "/applications/{application_id}/messages",
    response_model=EmployerMessageOut,
    status_code=status.HTTP_201_CREATED,
)
def ingest_employer_message(
    application_id: int,
    payload: EmployerMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = _get_owned_application(db, current_user.id, application_id)
    received_at = ensure_aware(payload.received_at) or utc_now()
    message_hash = employer_message_hash(
        sender_email=str(payload.sender_email),
        subject=payload.subject,
        body=payload.body,
        received_at=received_at,
    )
    duplicate = recent_message_duplicate(
        db,
        application_id=application.id,
        message_hash=message_hash,
    )
    if duplicate is not None:
        return _event_to_message_out(duplicate, duplicate=True)

    classification = classify_employer_message(payload.subject, payload.body)
    recruiter_contact_id = None
    recruiter_interaction_id = None
    sender_email = str(payload.sender_email).strip().casefold()
    account_email = str(current_user.email or "").strip().casefold()

    if payload.create_recruiter_contact and sender_email != account_email:
        contact = (
            db.query(RecruiterContact)
            .filter(
                RecruiterContact.user_id == current_user.id,
                RecruiterContact.company == application.job.company,
                RecruiterContact.email.ilike(sender_email),
            )
            .first()
        )
        if contact is None:
            sender_name = (payload.sender_name or "").strip()
            if not sender_name:
                local_part = sender_email.split("@", 1)[0]
                sender_name = local_part.replace(".", " ").replace("_", " ").strip().title()
            if not sender_name:
                sender_name = "Employer contact"
            contact = RecruiterContact(
                user_id=current_user.id,
                company=application.job.company,
                full_name=sender_name,
                email=sender_email,
                relationship_stage="conversation",
                last_contacted_at=received_at,
                contact_metadata={
                    "created_from": "post_application_inbound_message",
                    "source_reference": payload.source_reference,
                },
            )
            db.add(contact)
            db.flush()
        else:
            contact.last_contacted_at = received_at
            if contact.relationship_stage == "identified":
                contact.relationship_stage = "conversation"
        recruiter_contact_id = contact.id

        interaction = RecruiterInteraction(
            contact_id=contact.id,
            application_id=application.id,
            direction="inbound",
            channel="email",
            interaction_type=classification["category"],
            summary=payload.subject,
            occurred_at=received_at,
            interaction_metadata={
                "source_reference": payload.source_reference,
                "message_hash": message_hash,
                "classification": classification,
            },
        )
        db.add(interaction)
        db.flush()
        recruiter_interaction_id = interaction.id

    event_payload = {
        "message_hash": message_hash,
        "sender_name": payload.sender_name,
        "sender_email": sender_email,
        "subject": payload.subject,
        # Preserve only the bounded body needed for operator review; the hash binds the
        # complete submitted text without duplicating an arbitrarily large message.
        "body_preview": payload.body[:5000],
        "received_at": received_at.isoformat(),
        "source_reference": payload.source_reference,
        "classification": classification,
        "recruiter_contact_id": recruiter_contact_id,
        "recruiter_interaction_id": recruiter_interaction_id,
        "status_applied": False,
    }
    event = ApplicationEvent(
        application_id=application.id,
        event_type="inbound_employer_message",
        from_state=_status_value(application),
        to_state=None,
        payload=event_payload,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_to_message_out(event, duplicate=False)


@router.post(
    "/applications/{application_id}/messages/{event_id}/apply-status",
    response_model=StatusConfirmationOut,
)
def confirm_message_status(
    application_id: int,
    event_id: int,
    payload: ConfirmMessageStatusRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = _get_owned_application(db, current_user.id, application_id)
    event = (
        db.query(ApplicationEvent)
        .filter(
            ApplicationEvent.id == event_id,
            ApplicationEvent.application_id == application.id,
            ApplicationEvent.event_type == "inbound_employer_message",
        )
        .first()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Inbound employer message not found")

    event_payload = dict(event.payload or {})
    classification = dict(event_payload.get("classification") or {})
    target_status = str(classification.get("proposed_status") or "")
    if not target_status:
        raise HTTPException(
            status_code=409,
            detail="This message does not contain a deterministic status proposal",
        )
    expected_ack = f"CONFIRM STATUS {target_status.upper()}"
    if payload.acknowledgment != expected_ack:
        raise HTTPException(
            status_code=422,
            detail=f"Acknowledgment must exactly match: {expected_ack}",
        )

    current_status = _status_value(application)
    if not can_transition_application_status(current_status, target_status):
        raise HTTPException(
            status_code=409,
            detail=f"Application status cannot transition from {current_status} to {target_status}",
        )

    if current_status == target_status and event_payload.get("status_applied"):
        existing_event_id = event_payload.get("status_confirmation_event_id")
        return StatusConfirmationOut(
            application_id=application.id,
            event_id=int(existing_event_id or event.id),
            from_status=current_status,
            to_status=target_status,
            source_message_event_id=event.id,
        )

    application.status = ApplicationStatus(target_status)
    now = utc_now()
    if target_status == ApplicationStatus.interviewing.value and application.interview_at is None:
        # The message proves an interview-stage transition, not a specific schedule.
        pass
    elif target_status == ApplicationStatus.offer.value:
        application.offer_received_at = application.offer_received_at or now
    elif target_status == ApplicationStatus.rejected.value:
        application.rejection_reason = application.rejection_reason or (
            f"Confirmed from inbound employer message {event.id}"
        )

    confirmation = ApplicationEvent(
        application_id=application.id,
        event_type="post_application_status_confirmed",
        from_state=current_status,
        to_state=target_status,
        payload={
            "source_message_event_id": event.id,
            "source_reference": event_payload.get("source_reference"),
            "classification": classification,
            "acknowledgment": payload.acknowledgment,
            "confirmed_at": now.isoformat(),
        },
    )
    db.add(confirmation)
    db.flush()
    event_payload["status_applied"] = True
    event_payload["status_confirmation_event_id"] = confirmation.id
    event.payload = event_payload
    db.commit()
    db.refresh(confirmation)

    return StatusConfirmationOut(
        application_id=application.id,
        event_id=confirmation.id,
        from_status=current_status,
        to_status=target_status,
        source_message_event_id=event.id,
    )


@router.post(
    "/applications/{application_id}/interview",
    response_model=InterviewScheduleOut,
)
def schedule_interview(
    application_id: int,
    payload: InterviewScheduleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = _get_owned_application(db, current_user.id, application_id)
    current_status = _status_value(application)
    if current_status in {
        ApplicationStatus.offer.value,
        ApplicationStatus.rejected.value,
        ApplicationStatus.withdrawn.value,
    }:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot schedule an interview for application status {current_status}",
        )
    interview_at = ensure_aware(payload.interview_at)
    if interview_at is None:
        raise HTTPException(status_code=422, detail="interview_at is required")

    application.interview_at = interview_at
    if current_status != ApplicationStatus.interviewing.value:
        if not can_transition_application_status(
            current_status, ApplicationStatus.interviewing.value
        ):
            raise HTTPException(
                status_code=409,
                detail=f"Application status cannot transition from {current_status} to interviewing",
            )
        application.status = ApplicationStatus.interviewing

    event = ApplicationEvent(
        application_id=application.id,
        event_type="interview_scheduled",
        from_state=current_status,
        to_state=ApplicationStatus.interviewing.value,
        payload={
            "interview_at": interview_at.isoformat(),
            "interview_format": payload.interview_format,
            "location_or_url": payload.location_or_url,
            "notes": payload.notes,
            "source_reference": payload.source_reference,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return InterviewScheduleOut(
        application_id=application.id,
        event_id=event.id,
        status=ApplicationStatus.interviewing.value,
        interview_at=interview_at,
        interview_format=payload.interview_format,
        location_or_url=payload.location_or_url,
        notes=payload.notes,
        source_reference=payload.source_reference,
    )


@router.get(
    "/applications/{application_id}/interview-prep",
    response_model=InterviewPrepOut,
)
def interview_prep(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = _get_owned_application(db, current_user.id, application_id)
    if _status_value(application) not in {
        ApplicationStatus.interviewing.value,
        ApplicationStatus.offer.value,
    }:
        raise HTTPException(
            status_code=409,
            detail="Interview preparation is available once the application reaches interviewing",
        )
    return build_interview_prep_packet(
        db,
        user_id=current_user.id,
        application=application,
    )


@router.post(
    "/applications/{application_id}/outcome",
    response_model=OutcomeRecordOut,
)
def record_application_outcome(
    application_id: int,
    payload: OutcomeRecordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = _get_owned_application(db, current_user.id, application_id)
    current_status = _status_value(application)
    target_status = payload.outcome
    if not can_transition_application_status(current_status, target_status):
        if current_status != target_status:
            raise HTTPException(
                status_code=409,
                detail=f"Application status cannot transition from {current_status} to {target_status}",
            )

    now = datetime.now(timezone.utc)
    application.status = ApplicationStatus(target_status)
    if target_status == ApplicationStatus.offer.value:
        application.offer_received_at = application.offer_received_at or now
        if payload.salary_offered is not None:
            application.salary_offered = payload.salary_offered
    elif target_status == ApplicationStatus.rejected.value:
        application.rejection_reason = payload.detail

    event = ApplicationEvent(
        application_id=application.id,
        event_type="application_outcome_recorded",
        from_state=current_status,
        to_state=target_status,
        payload={
            "outcome": target_status,
            "salary_offered": payload.salary_offered,
            "detail": payload.detail,
            "source_reference": payload.source_reference,
            "recorded_at": now.isoformat(),
            "provenance": "explicit_user_record",
        },
    )
    db.add(event)
    db.flush()
    memory = upsert_outcome_memory(
        db,
        user_id=current_user.id,
        application=application,
        event=event,
        outcome=target_status,
        detail=payload.detail,
    )
    db.flush()
    db.commit()
    db.refresh(event)
    db.refresh(memory)

    return OutcomeRecordOut(
        application_id=application.id,
        event_id=event.id,
        outcome=target_status,
        from_status=current_status,
        to_status=target_status,
        salary_offered=application.salary_offered,
        detail=payload.detail,
        source_reference=payload.source_reference,
        memory_id=memory.id,
    )


@router.get("/offers", response_model=OfferComparisonOut)
def compare_offers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return build_offer_comparison(db, user_id=current_user.id)
