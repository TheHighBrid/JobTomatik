from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from app.database import Base


class CertificationEvidence(Base):
    """Immutable-ish retained evidence used by the Phase 10 release evaluator.

    The payload hash binds the submitted evidence metadata. Review state is kept
    separately so recording evidence can never imply that it has been independently
    verified. Evidence can be revoked or expire without deleting its audit history.
    """

    __tablename__ = "certification_evidence"

    id = Column(Integer, primary_key=True, index=True)
    evidence_key = Column(String(255), nullable=False, unique=True, index=True)
    evidence_type = Column(String(80), nullable=False, index=True)
    adapter = Column(String(80), nullable=True, index=True)
    commit_sha = Column(String(64), nullable=False, index=True)
    environment = Column(String(80), nullable=False, default="unknown", index=True)
    status = Column(String(40), nullable=False, default="recorded", index=True)
    duration_seconds = Column(Integer, nullable=True)
    source_reference = Column(String(1000), nullable=False)
    payload_hash = Column(String(128), nullable=False, index=True)
    evidence_metadata = Column(JSON, default=dict)
    recorded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    review_status = Column(String(40), nullable=False, default="unreviewed", index=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_reference = Column(String(1000), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ReleaseAuthorization(Base):
    """Commit-bound owner authorization that never toggles runtime submission flags."""

    __tablename__ = "release_authorizations"

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String(80), nullable=False, index=True)
    release_version = Column(String(80), nullable=False, index=True)
    commit_sha = Column(String(64), nullable=False, index=True)
    approval_reference = Column(String(255), nullable=False, unique=True, index=True)
    payload_hash = Column(String(128), nullable=False)
    status = Column(String(40), nullable=False, default="approved", index=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    authorization_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ShadowRunSession(Base):
    """Durable unattended dry-run campaign that survives individual Celery tasks.

    A session never stores permission to submit. ``final_submit_allowed`` is persisted
    as a fail-closed invariant and must remain false for the entire session.
    """

    __tablename__ = "shadow_run_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    candidate_revision = Column(String(64), nullable=False, index=True)
    requested_duration_seconds = Column(Integer, nullable=False)
    cycle_interval_seconds = Column(Integer, nullable=False, default=900)
    status = Column(String(40), nullable=False, default="scheduled", index=True)
    started_at = Column(DateTime(timezone=True), nullable=True, index=True)
    expected_end_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_cycle_at = Column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True, index=True)
    cycles_completed = Column(Integer, nullable=False, default=0)
    cycles_failed = Column(Integer, nullable=False, default=0)
    applications_created = Column(Integer, nullable=False, default=0)
    applications_ready_to_submit = Column(Integer, nullable=False, default=0)
    human_boundaries = Column(Integer, nullable=False, default=0)
    unexplained_records = Column(Integer, nullable=False, default=0)
    duplicate_application_ids = Column(Integer, nullable=False, default=0)
    runaway_retry_count = Column(Integer, nullable=False, default=0)
    final_submit_allowed = Column(Boolean, nullable=False, default=False)
    stop_requested = Column(Boolean, nullable=False, default=False)
    configuration_snapshot = Column(JSON, default=dict)
    baseline_snapshot = Column(JSON, default=dict)
    fault_plan = Column(JSON, default=dict)
    final_report = Column(JSON, default=dict)
    report_sha256 = Column(String(128), nullable=True)
    failure_reason = Column(String(1000), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ShadowRunCycle(Base):
    """One short scheduler cycle within a durable full-stack shadow session."""

    __tablename__ = "shadow_run_cycles"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("shadow_run_sessions.id"), nullable=False, index=True)
    cycle_number = Column(Integer, nullable=False, index=True)
    status = Column(String(40), nullable=False, default="running", index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    scheduler_result = Column(JSON, default=dict)
    observability_snapshot = Column(JSON, default=dict)
    reconciliation_snapshot = Column(JSON, default=dict)
    fault_injection = Column(JSON, default=dict)
    error_detail = Column(String(2000), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
