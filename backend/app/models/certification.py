import os

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, event
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
    __table_args__ = (
        UniqueConstraint(
            "approved_by_user_id",
            "approval_reference",
            name="uq_release_authorization_owner_reference",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String(80), nullable=False, index=True)
    release_version = Column(String(80), nullable=False, index=True)
    commit_sha = Column(String(64), nullable=False, index=True)
    approval_reference = Column(String(255), nullable=False, index=True)
    payload_hash = Column(String(128), nullable=False)
    status = Column(String(40), nullable=False, default="approved", index=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    authorization_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ShadowRunSession(Base):
    """Durable full-stack no-submit campaign used to collect real shadow evidence."""

    __tablename__ = "shadow_run_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Non-terminal campaigns retain ``user:<id>`` here. Terminal campaigns clear it.
    # The unique constraint works on SQLite and PostgreSQL and closes the race that
    # ``SELECT ... FOR UPDATE`` alone cannot close on Android/SQLite.
    active_guard = Column(String(100), nullable=True, unique=True, index=True)
    candidate_revision = Column(String(64), nullable=False, index=True)
    target_evidence_type = Column(String(40), nullable=False, index=True)
    requested_duration_seconds = Column(Integer, nullable=False)
    cycle_interval_seconds = Column(Integer, nullable=False, default=900)
    status = Column(String(40), nullable=False, default="scheduled", index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    expected_end_at = Column(DateTime(timezone=True), nullable=False)
    settle_deadline_at = Column(DateTime(timezone=True), nullable=True)
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
    final_report = Column(JSON, default=dict)
    report_sha256 = Column(String(128), nullable=True, index=True)
    failure_reason = Column(String(1000), nullable=True)
    certification_evidence_id = Column(
        Integer,
        ForeignKey("certification_evidence.id"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ShadowRunCycle(Base):
    """One bounded scheduler cycle retained inside a full-stack shadow campaign."""

    __tablename__ = "shadow_run_cycles"
    __table_args__ = (
        UniqueConstraint("session_id", "cycle_number", name="uq_shadow_run_session_cycle"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("shadow_run_sessions.id"), nullable=False, index=True)
    cycle_number = Column(Integer, nullable=False, index=True)
    status = Column(String(40), nullable=False, default="running", index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    scheduler_result = Column(JSON, default=dict)
    observability_snapshot = Column(JSON, default=dict)
    reconciliation_snapshot = Column(JSON, default=dict)
    error_detail = Column(String(2000), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


_ANDROID_TIMED_SHADOW_TARGETS = frozenset({"shadow_run_4h", "shadow_run_8h", "shadow_run_24h"})


def _require_android_shadow_admission(target: ShadowRunSession) -> None:
    """Make timed Android evidence impossible to start without device/canary proof.

    The guard sits at the ORM insert boundary so an API, CLI, test helper, or future
    internal caller cannot bypass the qualification receipt merely by skipping the
    current UI/preflight route. Non-Android environments retain their existing test
    and development behavior. The 8h/24h stages intentionally remain closed until a
    legitimate 4h campaign has passed and a duration-specific admission gate lands.
    """

    if os.environ.get("JOBTOMATIK_RUNTIME_MODE") != "android_managed":
        return
    evidence_type = str(target.target_evidence_type or "")
    if evidence_type not in _ANDROID_TIMED_SHADOW_TARGETS:
        return
    if evidence_type != "shadow_run_4h":
        raise ValueError(
            "Android 8h/24h shadow evidence is intentionally locked until the 4h stage passes."
        )

    from app.services.runtime_acceptance import canary_receipt_status

    admission = canary_receipt_status(int(target.user_id), max_age_seconds=60 * 60)
    if not admission.get("ok"):
        blockers = ",".join(admission.get("blockers") or []) or "qualification_receipt_invalid"
        raise ValueError(
            "Android shadow_run_4h requires a fresh exact-runtime application-path canary: "
            + blockers
        )
    receipt = dict(admission.get("receipt") or {})
    if receipt.get("type") != "shadow_qualification_canary":
        raise ValueError("Android shadow_run_4h qualification receipt has the wrong type")
    if receipt.get("certification_eligible") is not False:
        raise ValueError("Shadow qualification canary must remain explicitly non-certifying")
    if str(receipt.get("revision") or "") != str(target.candidate_revision or ""):
        raise ValueError("Shadow qualification canary revision does not match the campaign revision")


@event.listens_for(ShadowRunSession, "before_insert")
def _require_shadow_admission_before_insert(_mapper, _connection, target: ShadowRunSession) -> None:
    _require_android_shadow_admission(target)


@event.listens_for(ShadowRunSession, "before_insert")
@event.listens_for(ShadowRunSession, "before_update")
def _maintain_shadow_active_guard(_mapper, _connection, target: ShadowRunSession) -> None:
    if target.status in {"scheduled", "running", "settling", "stopping"}:
        target.active_guard = f"user:{int(target.user_id)}"
    else:
        target.active_guard = None
