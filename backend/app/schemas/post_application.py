from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class EmployerMessageCreate(BaseModel):
    sender_name: str | None = Field(default=None, max_length=255)
    sender_email: EmailStr
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=30000)
    received_at: datetime | None = None
    source_reference: str = Field(min_length=1, max_length=1000)
    create_recruiter_contact: bool = True

    @field_validator("sender_name", "subject", "body", "source_reference")
    @classmethod
    def normalize_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class MessageClassification(BaseModel):
    category: Literal[
        "rejection",
        "offer",
        "interview",
        "assessment",
        "application_received",
        "status_update",
        "recruiter_outreach",
        "other",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    matched_phrases: list[str] = Field(default_factory=list)
    proposed_status: str | None = None
    requires_confirmation: bool
    classifier_version: str


class EmployerMessageOut(BaseModel):
    event_id: int
    application_id: int
    message_hash: str
    duplicate: bool = False
    sender_name: str | None = None
    sender_email: str
    subject: str
    received_at: datetime
    source_reference: str
    classification: MessageClassification
    recruiter_contact_id: int | None = None
    recruiter_interaction_id: int | None = None


class ConfirmMessageStatusRequest(BaseModel):
    acknowledgment: str = Field(min_length=1, max_length=80)

    @field_validator("acknowledgment")
    @classmethod
    def normalize_acknowledgment(cls, value: str) -> str:
        return " ".join(value.strip().split())


class StatusConfirmationOut(BaseModel):
    application_id: int
    event_id: int
    from_status: str
    to_status: str
    source_message_event_id: int


class InterviewScheduleRequest(BaseModel):
    interview_at: datetime
    interview_format: Literal["video", "phone", "onsite", "other"] = "video"
    location_or_url: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=5000)
    source_reference: str = Field(min_length=1, max_length=1000)

    @field_validator("location_or_url", "notes", "source_reference")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class InterviewScheduleOut(BaseModel):
    application_id: int
    event_id: int
    status: str
    interview_at: datetime
    interview_format: str
    location_or_url: str | None = None
    notes: str | None = None
    source_reference: str


class InterviewPrepEvidence(BaseModel):
    content: str
    kind: str
    confidence: float
    source: str
    source_ref: str | None = None


class InterviewCompanyContext(BaseModel):
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float
    source_url: str | None = None


class InterviewPrepOut(BaseModel):
    application_id: int
    generated_at: datetime
    role: str
    company: str
    location: str | None = None
    interview_at: datetime | None = None
    requirements: list[str] = Field(default_factory=list)
    candidate_evidence: list[InterviewPrepEvidence] = Field(default_factory=list)
    company_context: list[InterviewCompanyContext] = Field(default_factory=list)
    question_prompts: list[str] = Field(default_factory=list)
    provenance_policy: str


class OutcomeRecordRequest(BaseModel):
    outcome: Literal["offer", "rejected", "withdrawn"]
    salary_offered: int | None = Field(default=None, ge=0, le=10000000)
    detail: str | None = Field(default=None, max_length=5000)
    source_reference: str = Field(min_length=1, max_length=1000)

    @field_validator("detail", "source_reference")
    @classmethod
    def normalize_outcome_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_outcome_fields(self):
        if self.salary_offered is not None and self.outcome != "offer":
            raise ValueError("salary_offered is only valid for an offer outcome")
        return self


class OutcomeRecordOut(BaseModel):
    application_id: int
    event_id: int
    outcome: str
    from_status: str
    to_status: str
    salary_offered: int | None = None
    detail: str | None = None
    source_reference: str
    memory_id: int


class PostApplicationApplicationItem(BaseModel):
    application_id: int
    job_id: int
    title: str
    company: str
    status: str
    applied_at: datetime | None = None
    interview_at: datetime | None = None
    offer_received_at: datetime | None = None
    salary_offered: int | None = None


class PostApplicationEventItem(BaseModel):
    event_id: int
    application_id: int
    event_type: str
    from_state: str | None = None
    to_state: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class PostApplicationWorkspaceOut(BaseModel):
    generated_at: datetime
    summary: dict[str, int]
    applications: list[PostApplicationApplicationItem] = Field(default_factory=list)
    events: list[PostApplicationEventItem] = Field(default_factory=list)


class OfferComparisonItem(BaseModel):
    application_id: int
    job_id: int
    title: str
    company: str
    location: str | None = None
    salary_offered: int | None = None
    salary_currency: str | None = None
    market_salary_min: int | None = None
    market_salary_max: int | None = None
    market_salary_midpoint: int | None = None
    weighted_fit_score: float | None = None
    recommendation: str | None = None
    offer_received_at: datetime | None = None
    notes: str | None = None


class OfferComparisonOut(BaseModel):
    offers: list[OfferComparisonItem] = Field(default_factory=list)
    offer_count: int
    highest_salary_application_id: int | None = None
    highest_fit_application_id: int | None = None
    decision_note: str
