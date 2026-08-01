from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from app.database import Base


class OpportunityEvaluation(Base):
    __tablename__ = "opportunity_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True, index=True)
    framework_version = Column(String(80), nullable=False, default="jobtomatik-opportunity-v1")
    status = Column(String(30), nullable=False, default="completed", index=True)
    recommendation = Column(String(40), nullable=False, index=True)
    weighted_score = Column(Float, nullable=False, index=True)
    dimension_scores = Column(JSON, nullable=False, default=dict)
    analysis_blocks = Column(JSON, nullable=False, default=dict)
    legitimacy_status = Column(String(40), nullable=False, default="unknown", index=True)
    hard_blockers = Column(JSON, nullable=False, default=list)
    source_snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
