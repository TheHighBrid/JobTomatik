from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application, ManualReviewStatus, ManualReviewTask
from app.models.intelligence import CareerMemory, KnowledgeEdge
from app.models.user import User
from app.schemas.intelligence import CareerMemoryOut
from app.schemas.operations import (
    CareerMemoryCorrection,
    KnowledgeEdgeListItem,
    OperationsWorkspaceOut,
)
from app.services.operations_workspace import build_operations_workspace


router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/workspace", response_model=OperationsWorkspaceOut)
def get_operations_workspace(
    agenda_days: int = Query(default=14, ge=1, le=90),
    timeline_limit: int = Query(default=100, ge=1, le=300),
    evaluation_limit: int = Query(default=20, ge=1, le=100),
    pipeline_limit_per_status: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = build_operations_workspace(
        db,
        user_id=current_user.id,
        agenda_days=agenda_days,
        timeline_limit=timeline_limit,
        evaluation_limit=evaluation_limit,
        pipeline_limit_per_status=pipeline_limit_per_status,
    )
    # Summary metrics must describe the complete account dataset, not only the
    # cards retained by the per-column UI display cap.
    workspace["summary"]["open_reviews"] = (
        db.query(ManualReviewTask.id)
        .join(Application, Application.id == ManualReviewTask.application_id)
        .filter(
            Application.user_id == current_user.id,
            ManualReviewTask.status.in_(
                [ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value]
            ),
        )
        .count()
    )
    return workspace


@router.patch("/memories/{memory_id}", response_model=CareerMemoryOut)
def correct_career_memory(
    memory_id: int,
    payload: CareerMemoryCorrection,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    memory = (
        db.query(CareerMemory)
        .filter(
            CareerMemory.id == memory_id,
            CareerMemory.user_id == current_user.id,
        )
        .first()
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    values = payload.model_dump(exclude_unset=True)
    factual_change = "content" in values or "confidence" in values
    if factual_change:
        metadata = dict(memory.memory_metadata or {})
        history = list(metadata.get("correction_history") or [])[-19:]
        history.append(
            {
                "corrected_at": datetime.now(timezone.utc).isoformat(),
                "previous_content": memory.content,
                "previous_confidence": float(memory.confidence),
                "previous_source": memory.source,
                "previous_source_ref": memory.source_ref,
            }
        )
        metadata["correction_history"] = history
        metadata["corrected_by_user"] = True
        memory.memory_metadata = metadata
        memory.source = "user_correction"

    if "content" in values:
        memory.content = values["content"]
    if "confidence" in values:
        memory.confidence = values["confidence"]
    if "is_active" in values:
        memory.is_active = values["is_active"]

    db.commit()
    db.refresh(memory)
    return memory


@router.get("/knowledge/edges", response_model=list[KnowledgeEdgeListItem])
def list_knowledge_edges(
    from_node_id: int | None = Query(default=None, ge=1),
    to_node_id: int | None = Query(default=None, ge=1),
    relation: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=300, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(KnowledgeEdge).filter(KnowledgeEdge.user_id == current_user.id)
    if from_node_id is not None:
        query = query.filter(KnowledgeEdge.from_node_id == from_node_id)
    if to_node_id is not None:
        query = query.filter(KnowledgeEdge.to_node_id == to_node_id)
    if relation:
        query = query.filter(KnowledgeEdge.relation == relation)
    return query.order_by(KnowledgeEdge.created_at.desc()).limit(limit).all()
