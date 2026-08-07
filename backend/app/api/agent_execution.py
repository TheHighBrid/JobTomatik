from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.intelligence import AgentRun, SelectorStrategy
from app.models.user import User
from app.schemas.agent_execution import (
    AgentExecutionSnapshotOut,
    AgentRunApprovalRequest,
    AgentRunControlRequest,
    AgentRunDispatchOut,
    SelectorDiagnosticOut,
    SelectorStrategyControlUpdate,
)
from app.services.agent_execution import (
    APPROVAL_APPROVED,
    EXECUTION_SCOPE,
    approve_run,
    cancel_run,
    execution_snapshot,
    pause_run,
    refresh_run_status,
    reject_run,
    resume_run,
)
from app.services.intelligence_foundation import selector_health_score
from app.tasks.agent_execution import dispatch_agent_run_task


router = APIRouter(prefix="/intelligence", tags=["agent execution"])


def _owned_run(db: Session, user_id: int, run_id: int) -> AgentRun:
    run = (
        db.query(AgentRun)
        .filter(AgentRun.id == run_id, AgentRun.user_id == user_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    _ = run.tasks
    return run


def _approval_phrase(run_id: int) -> str:
    return f"APPROVE BOUNDED RUN {run_id}"


@router.get(
    "/agent-runs/{run_id}/execution",
    response_model=AgentExecutionSnapshotOut,
)
def get_agent_execution(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _owned_run(db, current_user.id, run_id)
    refresh_run_status(run)
    snapshot = execution_snapshot(run)
    db.commit()
    return snapshot


@router.post(
    "/agent-runs/{run_id}/approve",
    response_model=AgentExecutionSnapshotOut,
)
def approve_agent_execution(
    run_id: int,
    payload: AgentRunApprovalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _owned_run(db, current_user.id, run_id)
    expected = _approval_phrase(run_id)
    if payload.acknowledgment.strip() != expected:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Exact bounded-run acknowledgment required",
                "expected": expected,
                "scope": EXECUTION_SCOPE,
                "submission_authorized": False,
                "outreach_authorized": False,
            },
        )
    try:
        approve_run(run, user_id=current_user.id, note=payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return execution_snapshot(run)


@router.post(
    "/agent-runs/{run_id}/reject",
    response_model=AgentExecutionSnapshotOut,
)
def reject_agent_execution(
    run_id: int,
    payload: AgentRunControlRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _owned_run(db, current_user.id, run_id)
    try:
        reject_run(run, user_id=current_user.id, reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return execution_snapshot(run)


@router.post(
    "/agent-runs/{run_id}/dispatch",
    response_model=AgentRunDispatchOut,
)
def dispatch_agent_execution(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _owned_run(db, current_user.id, run_id)
    snapshot = execution_snapshot(run)
    if snapshot["cancellation_requested"]:
        raise HTTPException(status_code=409, detail="Agent run is cancelled")
    if snapshot["paused"]:
        raise HTTPException(status_code=409, detail="Agent run is paused")
    if run.requires_approval and snapshot["approval_state"] != APPROVAL_APPROVED:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Bounded execution approval is required",
                "expected_acknowledgment": _approval_phrase(run_id),
                "submission_authorized": False,
                "outreach_authorized": False,
            },
        )
    db.commit()
    task = dispatch_agent_run_task.delay(run.id)
    return {
        "run_id": run.id,
        "status": "queued",
        "celery_task_id": task.id,
        "snapshot": snapshot,
    }


@router.post(
    "/agent-runs/{run_id}/pause",
    response_model=AgentExecutionSnapshotOut,
)
def pause_agent_execution(
    run_id: int,
    payload: AgentRunControlRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _owned_run(db, current_user.id, run_id)
    try:
        pause_run(run, reason=payload.reason, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return execution_snapshot(run)


@router.post(
    "/agent-runs/{run_id}/resume",
    response_model=AgentRunDispatchOut,
)
def resume_agent_execution(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _owned_run(db, current_user.id, run_id)
    try:
        resume_run(run, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    snapshot = execution_snapshot(run)
    if run.requires_approval and snapshot["approval_state"] != APPROVAL_APPROVED:
        raise HTTPException(status_code=409, detail="Bounded execution approval is required")
    db.commit()
    task = dispatch_agent_run_task.delay(run.id)
    return {
        "run_id": run.id,
        "status": "queued",
        "celery_task_id": task.id,
        "snapshot": snapshot,
    }


@router.post(
    "/agent-runs/{run_id}/cancel",
    response_model=AgentExecutionSnapshotOut,
)
def cancel_agent_execution(
    run_id: int,
    payload: AgentRunControlRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _owned_run(db, current_user.id, run_id)
    cancel_run(run, user_id=current_user.id, reason=payload.reason)
    db.commit()
    return execution_snapshot(run)


def _selector_diagnostic(strategy: SelectorStrategy) -> dict:
    health = selector_health_score(
        confidence=strategy.confidence,
        success_count=strategy.success_count,
        failure_count=strategy.failure_count,
    )
    if strategy.is_disabled:
        circuit_state = "open"
    elif health < 0.35:
        circuit_state = "critical"
    elif health < 0.55:
        circuit_state = "degraded"
    else:
        circuit_state = "healthy"
    return {
        "id": strategy.id,
        "platform": strategy.platform,
        "page_signature": strategy.page_signature,
        "intent": strategy.intent,
        "selector": strategy.selector,
        "strategy_type": strategy.strategy_type,
        "confidence": strategy.confidence,
        "success_count": strategy.success_count,
        "failure_count": strategy.failure_count,
        "health_score": health,
        "circuit_state": circuit_state,
        "is_disabled": strategy.is_disabled,
        "last_success_at": strategy.last_success_at.isoformat() if strategy.last_success_at else None,
        "last_failure_at": strategy.last_failure_at.isoformat() if strategy.last_failure_at else None,
        "last_failure_reason": strategy.last_failure_reason,
        "strategy_metadata": strategy.strategy_metadata or {},
    }


@router.get("/selectors", response_model=list[SelectorDiagnosticOut])
def list_selector_diagnostics(
    platform: str | None = None,
    circuit_state: str | None = Query(default=None),
    include_disabled: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(SelectorStrategy).filter(SelectorStrategy.user_id == current_user.id)
    if platform:
        query = query.filter(SelectorStrategy.platform == platform)
    if not include_disabled:
        query = query.filter(SelectorStrategy.is_disabled.is_(False))
    diagnostics = [
        _selector_diagnostic(strategy)
        for strategy in query.order_by(
            SelectorStrategy.platform,
            SelectorStrategy.intent,
            SelectorStrategy.updated_at.desc(),
        ).all()
    ]
    if circuit_state:
        diagnostics = [item for item in diagnostics if item["circuit_state"] == circuit_state]
    return diagnostics


@router.patch(
    "/selectors/{strategy_id}/control",
    response_model=SelectorDiagnosticOut,
)
def update_selector_control(
    strategy_id: int,
    payload: SelectorStrategyControlUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    strategy = (
        db.query(SelectorStrategy)
        .filter(
            SelectorStrategy.id == strategy_id,
            SelectorStrategy.user_id == current_user.id,
        )
        .first()
    )
    if strategy is None:
        raise HTTPException(status_code=404, detail="Selector strategy not found")
    strategy.is_disabled = payload.is_disabled
    strategy.strategy_metadata = {
        **dict(strategy.strategy_metadata or {}),
        "control_reason": payload.reason,
        "controlled_by_user_id": current_user.id,
        "control_state": "disabled" if payload.is_disabled else "enabled",
    }
    db.commit()
    db.refresh(strategy)
    return _selector_diagnostic(strategy)
