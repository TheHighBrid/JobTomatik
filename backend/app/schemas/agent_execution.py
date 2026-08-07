from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentRunApprovalRequest(BaseModel):
    acknowledgment: str = Field(min_length=8, max_length=120)
    note: str | None = Field(default=None, max_length=1000)


class AgentRunControlRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class AgentRunDispatchOut(BaseModel):
    run_id: int
    status: str
    celery_task_id: str | None = None
    snapshot: dict[str, Any] = Field(default_factory=dict)


class AgentExecutionSnapshotOut(BaseModel):
    run_id: int
    status: str
    objective: str
    risk_level: str
    requires_approval: bool
    approval_state: str
    execution_scope: str
    paused: bool
    cancellation_requested: bool
    submission_authorized: bool
    outreach_authorized: bool
    ready_task_ids: list[int] = Field(default_factory=list)
    task_counts: dict[str, int] = Field(default_factory=dict)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    control: dict[str, Any] = Field(default_factory=dict)


class SubmissionHandoffCreateRequest(BaseModel):
    acknowledgment: str = Field(min_length=12, max_length=160)


class SubmissionHandoffReviewRequest(BaseModel):
    acknowledgment: str = Field(min_length=12, max_length=160)
    note: str | None = Field(default=None, max_length=1000)


class SubmissionHandoffOut(BaseModel):
    run_id: int
    application_id: int | None = None
    status: str
    exists: bool
    eligible: bool
    blockers: list[str] = Field(default_factory=list)
    drifted: bool
    drift_reasons: list[str] = Field(default_factory=list)
    expected_create_acknowledgment: str
    expected_review_acknowledgment: str
    current_snapshot: dict[str, Any] | None = None
    stored_snapshot: dict[str, Any] | None = None
    submission_authorized: bool
    approval_issued: bool
    queue_attempted: bool


class SelectorStrategyControlUpdate(BaseModel):
    is_disabled: bool
    reason: str = Field(min_length=3, max_length=500)


class SelectorDiagnosticOut(BaseModel):
    id: int
    platform: str
    page_signature: str
    intent: str
    selector: str
    strategy_type: str
    confidence: float
    success_count: int
    failure_count: int
    health_score: float
    circuit_state: str
    is_disabled: bool
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_failure_reason: str | None = None
    strategy_metadata: dict[str, Any] = Field(default_factory=dict)