from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models.intelligence import (
    AgentRun,
    AgentTask,
    CareerMemory,
    KnowledgeEdge,
    KnowledgeNode,
    RecruiterContact,
    RecruiterInteraction,
    SelectorStrategy,
)
from app.models.user import User
from app.schemas.intelligence import (
    AgentRunCreate,
    AgentRunOut,
    AgentTaskOut,
    AgentTaskUpdate,
    CareerMemoryCreate,
    CareerMemoryOut,
    IntelligenceOverview,
    KnowledgeEdgeCreate,
    KnowledgeEdgeOut,
    KnowledgeNodeCreate,
    KnowledgeNodeOut,
    RecruiterContactCreate,
    RecruiterContactOut,
    RecruiterInteractionCreate,
    RecruiterInteractionOut,
    SelectorOutcome,
    SelectorStrategyOut,
)
from app.services.intelligence_foundation import (
    build_adaptive_plan,
    confidence_after_outcome,
    derive_run_status,
    selector_health_score,
)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


def _get_owned_contact(db: Session, user_id: int, contact_id: int) -> RecruiterContact:
    contact = (
        db.query(RecruiterContact)
        .filter(RecruiterContact.id == contact_id, RecruiterContact.user_id == user_id)
        .first()
    )
    if contact is None:
        raise HTTPException(status_code=404, detail="Recruiter contact not found")
    return contact


def _selector_out(strategy: SelectorStrategy) -> SelectorStrategyOut:
    return SelectorStrategyOut(
        id=strategy.id,
        platform=strategy.platform,
        page_signature=strategy.page_signature,
        intent=strategy.intent,
        selector=strategy.selector,
        strategy_type=strategy.strategy_type,
        confidence=strategy.confidence,
        success_count=strategy.success_count,
        failure_count=strategy.failure_count,
        health_score=selector_health_score(
            confidence=strategy.confidence,
            success_count=strategy.success_count,
            failure_count=strategy.failure_count,
        ),
        last_success_at=strategy.last_success_at,
        last_failure_at=strategy.last_failure_at,
        last_failure_reason=strategy.last_failure_reason,
        strategy_metadata=strategy.strategy_metadata or {},
        is_disabled=strategy.is_disabled,
    )


@router.get("/overview", response_model=IntelligenceOverview)
def get_intelligence_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    selector_strategies = db.query(SelectorStrategy).filter(SelectorStrategy.is_disabled.is_(False)).all()
    recent_runs = (
        db.query(AgentRun)
        .options(selectinload(AgentRun.tasks))
        .filter(AgentRun.user_id == current_user.id)
        .order_by(AgentRun.created_at.desc())
        .limit(5)
        .all()
    )
    upcoming_followups = (
        db.query(RecruiterContact)
        .filter(
            RecruiterContact.user_id == current_user.id,
            RecruiterContact.next_followup_at.is_not(None),
        )
        .order_by(RecruiterContact.next_followup_at.asc())
        .limit(5)
        .all()
    )
    followups_due = (
        db.query(RecruiterContact)
        .filter(
            RecruiterContact.user_id == current_user.id,
            RecruiterContact.next_followup_at.is_not(None),
            RecruiterContact.next_followup_at <= now,
        )
        .count()
    )
    healthy_selectors = sum(
        1
        for strategy in selector_strategies
        if selector_health_score(
            confidence=strategy.confidence,
            success_count=strategy.success_count,
            failure_count=strategy.failure_count,
        ) >= 0.65
    )
    active_run_states = {"planned", "running", "blocked"}

    return IntelligenceOverview(
        memories=(
            db.query(CareerMemory)
            .filter(CareerMemory.user_id == current_user.id, CareerMemory.is_active.is_(True))
            .count()
        ),
        recruiter_contacts=(
            db.query(RecruiterContact).filter(RecruiterContact.user_id == current_user.id).count()
        ),
        followups_due=followups_due,
        knowledge_nodes=(
            db.query(KnowledgeNode).filter(KnowledgeNode.user_id == current_user.id).count()
        ),
        knowledge_edges=(
            db.query(KnowledgeEdge).filter(KnowledgeEdge.user_id == current_user.id).count()
        ),
        selector_strategies=len(selector_strategies),
        healthy_selectors=healthy_selectors,
        agent_runs=(db.query(AgentRun).filter(AgentRun.user_id == current_user.id).count()),
        active_agent_runs=(
            db.query(AgentRun)
            .filter(AgentRun.user_id == current_user.id, AgentRun.status.in_(active_run_states))
            .count()
        ),
        recent_runs=recent_runs,
        upcoming_followups=upcoming_followups,
    )


@router.get("/memories", response_model=list[CareerMemoryOut])
def list_memories(
    kind: str | None = None,
    active_only: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(CareerMemory).filter(CareerMemory.user_id == current_user.id)
    if kind:
        query = query.filter(CareerMemory.kind == kind)
    if active_only:
        query = query.filter(CareerMemory.is_active.is_(True))
    return query.order_by(CareerMemory.updated_at.desc(), CareerMemory.created_at.desc()).all()


@router.post("/memories", response_model=CareerMemoryOut, status_code=status.HTTP_201_CREATED)
def create_memory(
    payload: CareerMemoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    memory = CareerMemory(user_id=current_user.id, **payload.model_dump())
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_memory(
    memory_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    memory = (
        db.query(CareerMemory)
        .filter(CareerMemory.id == memory_id, CareerMemory.user_id == current_user.id)
        .first()
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    memory.is_active = False
    db.commit()


@router.get("/recruiters", response_model=list[RecruiterContactOut])
def list_recruiters(
    company: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(RecruiterContact).filter(RecruiterContact.user_id == current_user.id)
    if company:
        query = query.filter(RecruiterContact.company.ilike(f"%{company}%"))
    return query.order_by(RecruiterContact.next_followup_at.asc(), RecruiterContact.updated_at.desc()).all()


@router.post("/recruiters", response_model=RecruiterContactOut, status_code=status.HTTP_201_CREATED)
def create_recruiter(
    payload: RecruiterContactCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = RecruiterContact(user_id=current_user.id, **payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.post(
    "/recruiters/{contact_id}/interactions",
    response_model=RecruiterInteractionOut,
    status_code=status.HTTP_201_CREATED,
)
def add_recruiter_interaction(
    contact_id: int,
    payload: RecruiterInteractionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = _get_owned_contact(db, current_user.id, contact_id)
    values = payload.model_dump()
    if values["occurred_at"] is None:
        values["occurred_at"] = datetime.now(timezone.utc)
    interaction = RecruiterInteraction(contact_id=contact.id, **values)
    contact.last_contacted_at = values["occurred_at"]
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction


@router.get("/knowledge/nodes", response_model=list[KnowledgeNodeOut])
def list_knowledge_nodes(
    node_type: str | None = None,
    query: str | None = Query(default=None, max_length=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = db.query(KnowledgeNode).filter(KnowledgeNode.user_id == current_user.id)
    if node_type:
        statement = statement.filter(KnowledgeNode.node_type == node_type)
    if query:
        statement = statement.filter(KnowledgeNode.label.ilike(f"%{query}%"))
    return statement.order_by(KnowledgeNode.updated_at.desc(), KnowledgeNode.created_at.desc()).all()


@router.post(
    "/knowledge/nodes",
    response_model=KnowledgeNodeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_node(
    payload: KnowledgeNodeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    node = KnowledgeNode(user_id=current_user.id, **payload.model_dump())
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@router.post(
    "/knowledge/edges",
    response_model=KnowledgeEdgeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_edge(
    payload: KnowledgeEdgeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    node_ids = {payload.from_node_id, payload.to_node_id}
    owned_nodes = (
        db.query(KnowledgeNode.id)
        .filter(KnowledgeNode.user_id == current_user.id, KnowledgeNode.id.in_(node_ids))
        .all()
    )
    if {node_id for (node_id,) in owned_nodes} != node_ids:
        raise HTTPException(status_code=404, detail="Knowledge node not found")
    edge = KnowledgeEdge(user_id=current_user.id, **payload.model_dump())
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return edge


@router.get("/selectors/recommendation", response_model=SelectorStrategyOut)
def recommend_selector(
    platform: str,
    page_signature: str,
    intent: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del current_user  # Authentication is required; selector telemetry contains no applicant data.
    candidates = (
        db.query(SelectorStrategy)
        .filter(
            SelectorStrategy.platform == platform,
            SelectorStrategy.page_signature == page_signature,
            SelectorStrategy.intent == intent,
            SelectorStrategy.is_disabled.is_(False),
        )
        .all()
    )
    if not candidates:
        raise HTTPException(status_code=404, detail="No selector strategy is known for this intent")
    best = max(
        candidates,
        key=lambda item: selector_health_score(
            confidence=item.confidence,
            success_count=item.success_count,
            failure_count=item.failure_count,
        ),
    )
    return _selector_out(best)


@router.post("/selectors/outcomes", response_model=SelectorStrategyOut)
def record_selector_outcome(
    payload: SelectorOutcome,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del current_user
    strategy = (
        db.query(SelectorStrategy)
        .filter(
            SelectorStrategy.platform == payload.platform,
            SelectorStrategy.page_signature == payload.page_signature,
            SelectorStrategy.intent == payload.intent,
            SelectorStrategy.selector == payload.selector,
        )
        .first()
    )
    if strategy is None:
        strategy = SelectorStrategy(
            platform=payload.platform,
            page_signature=payload.page_signature,
            intent=payload.intent,
            selector=payload.selector,
            strategy_type=payload.strategy_type,
            strategy_metadata=payload.strategy_metadata,
        )
        db.add(strategy)
        db.flush()

    now = datetime.now(timezone.utc)
    if payload.success:
        strategy.success_count += 1
        strategy.last_success_at = now
        strategy.last_failure_reason = None
    else:
        strategy.failure_count += 1
        strategy.last_failure_at = now
        strategy.last_failure_reason = payload.failure_reason
    strategy.confidence = confidence_after_outcome(
        confidence=strategy.confidence,
        success_count=strategy.success_count,
        failure_count=strategy.failure_count,
    )
    if payload.strategy_metadata:
        strategy.strategy_metadata = {
            **(strategy.strategy_metadata or {}),
            **payload.strategy_metadata,
        }
    db.commit()
    db.refresh(strategy)
    return _selector_out(strategy)


@router.get("/agent-runs", response_model=list[AgentRunOut])
def list_agent_runs(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(AgentRun)
        .options(selectinload(AgentRun.tasks))
        .filter(AgentRun.user_id == current_user.id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/agent-runs", response_model=AgentRunOut, status_code=status.HTTP_201_CREATED)
def create_agent_run(
    payload: AgentRunCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = build_adaptive_plan(
        payload.objective,
        autonomy_level=payload.autonomy_level,
        run_context=payload.run_context,
    )
    run = AgentRun(
        user_id=current_user.id,
        objective=payload.objective,
        autonomy_level=payload.autonomy_level,
        risk_level=plan["risk_level"],
        requires_approval=plan["requires_approval"],
        plan=plan["tasks"],
        run_context={**payload.run_context, "guardrails": plan["guardrails"]},
    )
    db.add(run)
    db.flush()
    for sequence, task_spec in enumerate(plan["tasks"]):
        db.add(
            AgentTask(
                run_id=run.id,
                sequence=sequence,
                name=task_spec["name"],
                agent_type=task_spec["agent_type"],
                dependencies=task_spec["dependencies"],
                task_input=task_spec.get("input", {}),
            )
        )
    db.commit()
    return (
        db.query(AgentRun)
        .options(selectinload(AgentRun.tasks))
        .filter(AgentRun.id == run.id)
        .one()
    )


@router.patch("/agent-runs/{run_id}/tasks/{task_id}", response_model=AgentTaskOut)
def update_agent_task(
    run_id: int,
    task_id: int,
    payload: AgentTaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = (
        db.query(AgentTask)
        .join(AgentRun, AgentRun.id == AgentTask.run_id)
        .filter(
            AgentTask.id == task_id,
            AgentTask.run_id == run_id,
            AgentRun.user_id == current_user.id,
        )
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found")

    now = datetime.now(timezone.utc)
    task.status = payload.status
    task.task_output = payload.task_output
    task.error = payload.error
    if payload.status == "running":
        task.attempt_count += 1
        task.started_at = task.started_at or now
    if payload.status in {"completed", "failed", "skipped"}:
        task.completed_at = now

    run = db.query(AgentRun).filter(AgentRun.id == run_id).one()
    task_states = [row.status for row in run.tasks]
    run.status = derive_run_status(task_states)
    if run.status == "running":
        run.started_at = run.started_at or now
    if run.status in {"completed", "failed"}:
        run.completed_at = now
    db.commit()
    db.refresh(task)
    return task
