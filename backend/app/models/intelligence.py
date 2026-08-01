from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class CareerMemory(Base):
    __tablename__ = "career_memories"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(50), nullable=False, index=True)
    key = Column(String(255), nullable=False, index=True)
    content = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False, default=1.0)
    source = Column(String(80), nullable=False, default="user")
    source_ref = Column(String(1000))
    memory_metadata = Column(JSON, default=dict)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class RecruiterContact(Base):
    __tablename__ = "recruiter_contacts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    company = Column(String(255), nullable=False, index=True)
    full_name = Column(String(255), nullable=False, index=True)
    title = Column(String(255))
    email = Column(String(320), index=True)
    linkedin_url = Column(String(1000))
    relationship_stage = Column(String(50), nullable=False, default="identified", index=True)
    relationship_score = Column(Float, nullable=False, default=0.0)
    last_contacted_at = Column(DateTime(timezone=True))
    next_followup_at = Column(DateTime(timezone=True), index=True)
    notes = Column(Text)
    contact_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    interactions = relationship(
        "RecruiterInteraction",
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="RecruiterInteraction.occurred_at",
    )


class RecruiterInteraction(Base):
    __tablename__ = "recruiter_interactions"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("recruiter_contacts.id"), nullable=False, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), index=True)
    direction = Column(String(20), nullable=False, default="outbound")
    channel = Column(String(40), nullable=False, default="email")
    interaction_type = Column(String(80), nullable=False, default="message")
    summary = Column(Text, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    interaction_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    contact = relationship("RecruiterContact", back_populates="interactions")


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    node_type = Column(String(60), nullable=False, index=True)
    external_key = Column(String(500), index=True)
    label = Column(String(500), nullable=False, index=True)
    payload = Column(JSON, default=dict)
    confidence = Column(Float, nullable=False, default=1.0)
    source_url = Column(String(1000))
    observed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    from_node_id = Column(Integer, ForeignKey("knowledge_nodes.id"), nullable=False, index=True)
    to_node_id = Column(Integer, ForeignKey("knowledge_nodes.id"), nullable=False, index=True)
    relation = Column(String(100), nullable=False, index=True)
    weight = Column(Float, nullable=False, default=1.0)
    evidence = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SelectorStrategy(Base):
    __tablename__ = "selector_strategies"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(80), nullable=False, index=True)
    page_signature = Column(String(255), nullable=False, index=True)
    intent = Column(String(120), nullable=False, index=True)
    selector = Column(String(1000), nullable=False)
    strategy_type = Column(String(50), nullable=False, default="css")
    confidence = Column(Float, nullable=False, default=0.5)
    success_count = Column(Integer, nullable=False, default=0)
    failure_count = Column(Integer, nullable=False, default=0)
    last_success_at = Column(DateTime(timezone=True))
    last_failure_at = Column(DateTime(timezone=True))
    last_failure_reason = Column(Text)
    strategy_metadata = Column(JSON, default=dict)
    is_disabled = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    objective = Column(Text, nullable=False)
    status = Column(String(40), nullable=False, default="planned", index=True)
    autonomy_level = Column(String(40), nullable=False, default="reviewed")
    risk_level = Column(String(20), nullable=False, default="low")
    requires_approval = Column(Boolean, nullable=False, default=True)
    plan = Column(JSON, default=list)
    run_context = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    error = Column(Text)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tasks = relationship(
        "AgentTask",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentTask.sequence",
    )


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False, default=0)
    name = Column(String(255), nullable=False)
    agent_type = Column(String(80), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="pending", index=True)
    dependencies = Column(JSON, default=list)
    task_input = Column(JSON, default=dict)
    task_output = Column(JSON, default=dict)
    error = Column(Text)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=2)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    run = relationship("AgentRun", back_populates="tasks")
