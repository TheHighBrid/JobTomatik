from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CareerMemoryCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=50)
    key: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = Field(default="user", min_length=1, max_length=80)
    source_ref: str | None = Field(default=None, max_length=1000)
    memory_metadata: dict[str, Any] = Field(default_factory=dict)


class CareerMemoryOut(CareerMemoryCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class RecruiterContactCreate(BaseModel):
    company: str = Field(min_length=1, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    linkedin_url: str | None = Field(default=None, max_length=1000)
    relationship_stage: str = Field(default="identified", max_length=50)
    relationship_score: float = Field(default=0.0, ge=0.0, le=100.0)
    next_followup_at: datetime | None = None
    notes: str | None = None
    contact_metadata: dict[str, Any] = Field(default_factory=dict)


class RecruiterContactOut(RecruiterContactCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    last_contacted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class RecruiterInteractionCreate(BaseModel):
    application_id: int | None = None
    direction: Literal["inbound", "outbound", "internal"] = "outbound"
    channel: str = Field(default="email", min_length=1, max_length=40)
    interaction_type: str = Field(default="message", min_length=1, max_length=80)
    summary: str = Field(min_length=1)
    occurred_at: datetime | None = None
    interaction_metadata: dict[str, Any] = Field(default_factory=dict)


class RecruiterInteractionOut(RecruiterInteractionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_id: int
    occurred_at: datetime
    created_at: datetime


class KnowledgeNodeCreate(BaseModel):
    node_type: str = Field(min_length=1, max_length=60)
    external_key: str | None = Field(default=None, max_length=500)
    label: str = Field(min_length=1, max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_url: str | None = Field(default=None, max_length=1000)
    observed_at: datetime | None = None


class KnowledgeNodeOut(KnowledgeNodeCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime | None = None


class KnowledgeEdgeCreate(BaseModel):
    from_node_id: int
    to_node_id: int
    relation: str = Field(min_length=1, max_length=100)
    weight: float = Field(default=1.0, ge=0.0)
    evidence: dict[str, Any] = Field(default_factory=dict)


class KnowledgeEdgeOut(KnowledgeEdgeCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class SelectorOutcome(BaseModel):
    platform: str = Field(min_length=1, max_length=80)
    page_signature: str = Field(min_length=1, max_length=255)
    intent: str = Field(min_length=1, max_length=120)
    selector: str = Field(min_length=1, max_length=1000)
    strategy_type: str = Field(default="css", max_length=50)
    success: bool
    failure_reason: str | None = None
    strategy_metadata: dict[str, Any] = Field(default_factory=dict)


class SelectorStrategyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure_reason: str | None = None
    strategy_metadata: dict[str, Any] = Field(default_factory=dict)
    is_disabled: bool


class AgentRunCreate(BaseModel):
    objective: str = Field(min_length=3)
    autonomy_level: Literal["assistive", "reviewed", "bounded_autonomous"] = "reviewed"
    run_context: dict[str, Any] = Field(default_factory=dict)


class AgentTaskUpdate(BaseModel):
    status: Literal["pending", "running", "blocked", "completed", "failed", "skipped"]
    task_output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    sequence: int
    name: str
    agent_type: str
    status: str
    dependencies: list[str]
    task_input: dict[str, Any]
    task_output: dict[str, Any]
    error: str | None = None
    attempt_count: int
    max_attempts: int
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    objective: str
    status: str
    autonomy_level: str
    risk_level: str
    requires_approval: bool
    plan: list[dict[str, Any]]
    run_context: dict[str, Any]
    result: dict[str, Any]
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    tasks: list[AgentTaskOut] = Field(default_factory=list)


class IntelligenceOverview(BaseModel):
    memories: int
    recruiter_contacts: int
    followups_due: int
    knowledge_nodes: int
    knowledge_edges: int
    selector_strategies: int
    healthy_selectors: int
    agent_runs: int
    active_agent_runs: int
    recent_runs: list[AgentRunOut] = Field(default_factory=list)
    upcoming_followups: list[RecruiterContactOut] = Field(default_factory=list)
