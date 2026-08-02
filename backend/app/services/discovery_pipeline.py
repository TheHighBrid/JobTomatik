"""Persistence bridge from discovery into JobTomatik's intelligence foundation."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.evaluation import OpportunityEvaluation
from app.models.intelligence import (
    AgentRun,
    AgentTask,
    CareerMemory,
    KnowledgeEdge,
    KnowledgeNode,
)
from app.models.job import Job, JobStatus
from app.models.user import User
from app.services.discovery_scoring import score_discovered_job
from app.services.intelligence_foundation import build_adaptive_plan
from app.services.keyword_tagger import tag_job
from app.services.opportunity_evaluation import evaluate_opportunity


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return normalized[:180] or "unknown"


def _clamp_dimension(value: float) -> float:
    return round(max(1.0, min(float(value), 5.0)), 2)


def _dimension_scores(
    job: dict[str, Any],
    scoring: dict[str, Any],
    preferences: dict[str, Any],
) -> dict[str, float]:
    normalized = float(scoring["normalized_score"])
    matched_terms = scoring.get("matched_terms") or []
    seniority = str(job.get("seniority") or "").lower()
    desired_levels = [
        str(item).lower()
        for item in (
            preferences.get("preferred_seniority")
            or preferences.get("experience_levels")
            or []
        )
    ]

    level_score = 3.0
    if desired_levels and seniority:
        level_score = 4.5 if any(level in seniority for level in desired_levels) else 2.5

    minimum_salary = int(preferences.get("min_salary") or 0)
    salary_min = int(job.get("salary_min") or 0)
    compensation_score = 3.0
    if minimum_salary and salary_min:
        if salary_min >= minimum_salary * 1.2:
            compensation_score = 5.0
        elif salary_min >= minimum_salary:
            compensation_score = 4.0
        else:
            compensation_score = 2.0

    location = str(job.get("location") or "").lower()
    remote_score = 3.0
    if "remote" in location:
        remote_score = 5.0
    elif int(scoring.get("location_points") or 0) > 0:
        remote_score = 4.0
    elif int(scoring.get("location_points") or 0) < 0:
        remote_score = 2.0

    skills = {str(item).lower() for item in (job.get("skills") or [])}
    modern_stack = {
        "python",
        "postgresql",
        "aws",
        "react",
        "typescript",
        "docker",
        "kubernetes",
        "sql",
    }
    tech_score = 4.0 if skills & modern_stack else 3.0

    return {
        "north_star_alignment": _clamp_dimension(1.0 + normalized * 4.0),
        "cv_match": _clamp_dimension(1.5 + min(len(matched_terms), 10) * 0.35),
        "level": _clamp_dimension(level_score),
        "estimated_compensation": _clamp_dimension(compensation_score),
        "growth_trajectory": 3.0,
        "remote_quality": _clamp_dimension(remote_score),
        "company_reputation": 3.0,
        "tech_stack_modernity": _clamp_dimension(tech_score),
        "time_to_offer_speed": 3.0,
        "cultural_signals": 3.0,
    }


def _create_discovery_run(
    db: Session,
    user: User,
    *,
    keywords: str,
    search_params: dict[str, Any],
) -> AgentRun:
    objective = f"Find, deduplicate, score, and evaluate jobs matching {keywords}"
    plan = build_adaptive_plan(
        objective,
        autonomy_level="reviewed",
        run_context={"search_params": search_params, "pipeline": "public_ats_discovery_v1"},
    )
    now = datetime.now(timezone.utc)
    run = AgentRun(
        user_id=user.id,
        objective=objective,
        status="running",
        autonomy_level="reviewed",
        risk_level=plan["risk_level"],
        requires_approval=plan["requires_approval"],
        plan=plan["tasks"],
        run_context={
            "search_params": search_params,
            "pipeline": "public_ats_discovery_v1",
            "guardrails": plan["guardrails"],
        },
        started_at=now,
    )
    db.add(run)
    db.flush()
    for sequence, spec in enumerate(plan["tasks"]):
        db.add(
            AgentTask(
                run_id=run.id,
                sequence=sequence,
                name=spec["name"],
                agent_type=spec["agent_type"],
                status="running" if sequence == 0 else "pending",
                dependencies=spec.get("dependencies", []),
                task_input=spec.get("input", {}),
                started_at=now if sequence == 0 else None,
            )
        )
    db.flush()
    return run


def _complete_discovery_run(db: Session, run: AgentRun, result: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    for task in run.tasks:
        task.status = "completed"
        task.started_at = task.started_at or now
        task.completed_at = now
        task.attempt_count = max(task.attempt_count, 1)
        if task.agent_type == "discovery":
            task.task_output = {"total_found": result["total_found"]}
        elif task.agent_type == "deduplication":
            task.task_output = {"duplicates": result["duplicates"]}
        elif task.agent_type == "evaluation":
            task.task_output = {
                "saved": result["saved"],
                "evaluations_created": result["evaluations_created"],
                "blocked": result["blocked"],
            }
        elif task.agent_type == "memory":
            task.task_output = {"memories_used": result["memories_used"]}
        else:
            task.task_output = {"completed_by": "discovery_pipeline"}
    run.status = "completed"
    run.result = result
    run.completed_at = now


def _upsert_knowledge(
    db: Session,
    user: User,
    job: Job,
    raw: dict[str, Any],
) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    company_key = f"company:{_slug(job.company)}"
    company_node = (
        db.query(KnowledgeNode)
        .filter(
            KnowledgeNode.user_id == user.id,
            KnowledgeNode.external_key == company_key,
        )
        .first()
    )
    nodes_created = 0
    if company_node is None:
        company_node = KnowledgeNode(
            user_id=user.id,
            node_type="company",
            external_key=company_key,
            label=job.company,
            payload={
                "latest_source": str(job.source.value if hasattr(job.source, "value") else job.source),
                "ats_identifier": raw.get("ats_identifier"),
            },
            confidence=0.9 if raw.get("official_public_ats") else 0.7,
            source_url=job.url,
            observed_at=now,
        )
        db.add(company_node)
        db.flush()
        nodes_created += 1
    else:
        company_node.payload = {
            **(company_node.payload or {}),
            "latest_source": str(job.source.value if hasattr(job.source, "value") else job.source),
            "ats_identifier": raw.get("ats_identifier") or (company_node.payload or {}).get("ats_identifier"),
        }
        company_node.source_url = job.url or company_node.source_url
        company_node.observed_at = now

    role_key = f"job:{job.id}"
    role_node = KnowledgeNode(
        user_id=user.id,
        node_type="role",
        external_key=role_key,
        label=job.title,
        payload={
            "job_id": job.id,
            "location": job.location,
            "skills": job.skills or [],
            "seniority": job.seniority,
            "relevance_score": job.relevance_score,
        },
        confidence=0.95 if raw.get("official_public_ats") else 0.75,
        source_url=job.url,
        observed_at=now,
    )
    db.add(role_node)
    db.flush()
    nodes_created += 1

    db.add(
        KnowledgeEdge(
            user_id=user.id,
            from_node_id=company_node.id,
            to_node_id=role_node.id,
            relation="hires_for",
            weight=max(0.1, float(job.relevance_score or 0.0)),
            evidence={
                "job_id": job.id,
                "source_url": job.url,
                "official_public_ats": bool(raw.get("official_public_ats")),
            },
        )
    )
    return nodes_created, 1


def _persist_evaluation(
    db: Session,
    user: User,
    job: Job,
    tagged: dict[str, Any],
    scoring: dict[str, Any],
) -> OpportunityEvaluation:
    raw = dict(tagged.get("raw_data") or {})
    legitimacy = "likely_legitimate" if raw.get("official_public_ats") else "unknown"
    dimensions = _dimension_scores(tagged, scoring, user.job_preferences or {})
    result = evaluate_opportunity(
        dimensions,
        hard_blockers=scoring.get("hard_blockers") or [],
        legitimacy_status=legitimacy,
    )
    matched = scoring.get("matched_terms") or []
    evaluation = OpportunityEvaluation(
        user_id=user.id,
        job_id=job.id,
        framework_version=str(result["framework_version"]),
        status="completed",
        recommendation=str(result["recommendation"]),
        weighted_score=float(result["weighted_score"]),
        dimension_scores=result["dimension_scores"],
        analysis_blocks={
            "A": {
                "role_summary": f"{job.title} at {job.company}",
                "location": job.location,
                "source": str(job.source.value if hasattr(job.source, "value") else job.source),
            },
            "B": {
                "deterministic_match_score": scoring["score_100"],
                "matched_terms": matched[:12],
                "memory_refs": scoring.get("memory_matches") or [],
            },
            "C": {"seniority": job.seniority or "unknown"},
            "D": {
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "salary_currency": job.salary_currency,
            },
            "E": {
                "tailoring_terms": [row["term"] for row in matched[:8]],
                "truthful_evidence_required": True,
            },
            "F": {
                "interview_focus": (job.skills or [])[:8],
                "generated_without_llm": True,
            },
            "G": {
                "legitimacy": legitimacy,
                "official_public_ats": bool(raw.get("official_public_ats")),
                "provider_api_url": raw.get("provider_api_url"),
            },
        },
        legitimacy_status=legitimacy,
        hard_blockers=result["hard_blockers"],
        source_snapshot={
            "url": job.url,
            "source": str(job.source.value if hasattr(job.source, "value") else job.source),
            "external_id": job.external_id,
            "scoring": scoring,
            "provider_api_url": raw.get("provider_api_url"),
            "ats_identifier": raw.get("ats_identifier"),
        },
    )
    db.add(evaluation)
    return evaluation


def persist_discovery_results(
    db: Session,
    user: User,
    raw_jobs: list[dict[str, Any]],
    *,
    keywords: str,
    search_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score, deduplicate, persist, evaluate, and graph-enrich discovered jobs."""

    params = dict(search_params or {})
    params.setdefault("keywords", keywords)
    run = _create_discovery_run(db, user, keywords=keywords, search_params=params)
    preferences = dict(user.job_preferences or {})
    memories = (
        db.query(CareerMemory)
        .filter(CareerMemory.user_id == user.id, CareerMemory.is_active.is_(True))
        .all()
    )
    memory_by_id = {memory.id: memory for memory in memories}

    stats: dict[str, Any] = {
        "agent_run_id": run.id,
        "total_found": len(raw_jobs),
        "saved": 0,
        "duplicates": 0,
        "blocked": 0,
        "evaluations_created": 0,
        "knowledge_nodes_created": 0,
        "knowledge_edges_created": 0,
        "memories_used": 0,
        "blocked_reasons": {},
    }
    used_memory_ids: set[int] = set()

    for raw_job in raw_jobs:
        tagged = tag_job(dict(raw_job), preferences)
        scoring = score_discovered_job(
            tagged,
            preferences,
            search_keywords=keywords,
            memories=memories,
        )
        tagged["relevance_score"] = scoring["normalized_score"]
        tagged_raw = dict(tagged.get("raw_data") or {})
        tagged_raw["discovery_score"] = scoring
        tagged["raw_data"] = tagged_raw

        if scoring["hard_blockers"]:
            stats["blocked"] += 1
            for reason in scoring["hard_blockers"]:
                stats["blocked_reasons"][reason] = stats["blocked_reasons"].get(reason, 0) + 1
            continue

        existing = (
            db.query(Job)
            .filter(Job.external_id == tagged.get("external_id"))
            .first()
        )
        if existing is not None:
            stats["duplicates"] += 1
            continue

        job = Job(
            external_id=tagged.get("external_id"),
            title=tagged["title"],
            company=tagged["company"],
            location=tagged.get("location"),
            salary_min=tagged.get("salary_min"),
            salary_max=tagged.get("salary_max"),
            salary_currency=tagged.get("salary_currency", "CAD"),
            job_type=tagged.get("job_type"),
            description=tagged.get("description"),
            requirements=tagged.get("requirements"),
            url=tagged.get("url"),
            source=tagged.get("source"),
            status=JobStatus.queued,
            tags=tagged.get("tags", []),
            skills=tagged.get("skills", []),
            seniority=tagged.get("seniority"),
            industry=tagged.get("industry"),
            relevance_score=tagged.get("relevance_score", 0.0),
            raw_data=tagged_raw,
        )
        db.add(job)
        db.flush()

        _persist_evaluation(db, user, job, tagged, scoring)
        nodes, edges = _upsert_knowledge(db, user, job, tagged_raw)
        stats["saved"] += 1
        stats["evaluations_created"] += 1
        stats["knowledge_nodes_created"] += nodes
        stats["knowledge_edges_created"] += edges

        for memory_id in scoring.get("memory_matches") or []:
            if memory_id in memory_by_id:
                used_memory_ids.add(memory_id)

    now = datetime.now(timezone.utc)
    for memory_id in used_memory_ids:
        memory_by_id[memory_id].last_used_at = now
    stats["memories_used"] = len(used_memory_ids)

    _complete_discovery_run(db, run, stats)
    db.flush()
    return stats
