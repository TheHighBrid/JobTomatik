from __future__ import annotations

from collections.abc import Iterable
from typing import Any


HIGH_RISK_TERMS = {
    "apply",
    "submit",
    "offer",
    "negotiate",
    "withdraw",
    "accept",
    "decline",
}


def selector_health_score(
    *,
    confidence: float,
    success_count: int,
    failure_count: int,
) -> float:
    """Return a stable 0..1 score used to rank selector strategies.

    The prior confidence matters early. Observed outcomes gradually dominate without
    allowing one failure to erase a previously reliable strategy.
    """

    successes = max(0, int(success_count))
    failures = max(0, int(failure_count))
    prior = min(1.0, max(0.0, float(confidence)))
    observed = (successes + 1.0) / (successes + failures + 2.0)
    evidence_weight = min(0.85, (successes + failures) / 12.0)
    return round((prior * (1.0 - evidence_weight)) + (observed * evidence_weight), 4)


def confidence_after_outcome(
    *,
    confidence: float,
    success_count: int,
    failure_count: int,
) -> float:
    return selector_health_score(
        confidence=confidence,
        success_count=success_count,
        failure_count=failure_count,
    )


def _task(
    task_id: str,
    name: str,
    agent_type: str,
    dependencies: Iterable[str] = (),
    **task_input: Any,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "name": name,
        "agent_type": agent_type,
        "dependencies": list(dependencies),
        "input": task_input,
    }


def build_adaptive_plan(
    objective: str,
    *,
    autonomy_level: str = "reviewed",
    run_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic multi-agent plan that an LLM runner can enrich later.

    The planner intentionally separates reasoning from execution. It may prepare a
    submission path, but JobTomatik's existing policy, approval, adapter-maturity,
    idempotency, and confirmation-evidence gates remain authoritative.
    """

    context = run_context or {}
    text = objective.lower()
    tasks: list[dict[str, Any]] = []

    wants_discovery = any(term in text for term in ("find", "discover", "search", "scan", "jobs"))
    wants_application = any(term in text for term in ("apply", "application", "submit"))
    wants_interview = any(term in text for term in ("interview", "practice", "star story"))
    wants_recruiter = any(term in text for term in ("recruiter", "contact", "follow up", "follow-up", "outreach"))
    wants_offer = any(term in text for term in ("offer", "salary", "negotiate", "contract"))

    if wants_discovery:
        tasks.extend(
            [
                _task("discover", "Discover matching roles", "discovery"),
                _task("deduplicate", "Resolve duplicate listings", "deduplication", ["discover"]),
                _task("score", "Evaluate and rank opportunities", "evaluation", ["deduplicate"]),
            ]
        )

    if wants_application or context.get("job_id") or context.get("application_id"):
        dependency = tasks[-1]["id"] if tasks else None
        dependencies = [dependency] if dependency else []
        tasks.extend(
            [
                _task(
                    "research",
                    "Research company and role context",
                    "company_research",
                    dependencies,
                    job_id=context.get("job_id"),
                ),
                _task("evaluate", "Run structured fit evaluation", "evaluation", ["research"]),
                _task("tailor", "Prepare truthful tailored materials", "tailoring", ["evaluate"]),
                _task(
                    "prepare_application",
                    "Prepare adapter-bounded application",
                    "application",
                    ["tailor"],
                    application_id=context.get("application_id"),
                ),
            ]
        )

    if wants_recruiter:
        dependency = "research" if any(task["id"] == "research" for task in tasks) else None
        tasks.append(
            _task(
                "crm",
                "Update recruiter relationship and next action",
                "recruiter_crm",
                [dependency] if dependency else [],
            )
        )

    if wants_interview:
        dependency = "research" if any(task["id"] == "research" for task in tasks) else None
        tasks.extend(
            [
                _task(
                    "story_bank",
                    "Match evidence-backed career stories",
                    "interview_intelligence",
                    [dependency] if dependency else [],
                ),
                _task("practice", "Prepare interview practice brief", "interview_coach", ["story_bank"]),
            ]
        )

    if wants_offer:
        tasks.append(
            _task(
                "offer_analysis",
                "Compare offer terms and negotiation boundaries",
                "offer_intelligence",
            )
        )

    if not tasks:
        tasks.append(_task("evaluate", "Evaluate the requested career objective", "evaluation"))

    terminal_dependencies = [tasks[-1]["id"]]
    tasks.append(
        _task(
            "learn",
            "Persist verified outcomes and reusable memory",
            "memory",
            terminal_dependencies,
        )
    )

    risk_level = "high" if any(term in text for term in HIGH_RISK_TERMS) else "low"
    requires_approval = autonomy_level != "bounded_autonomous" or risk_level == "high"

    return {
        "objective": objective,
        "autonomy_level": autonomy_level,
        "risk_level": risk_level,
        "requires_approval": requires_approval,
        "tasks": tasks,
        "guardrails": {
            "submission_policy_authoritative": True,
            "adapter_maturity_authoritative": True,
            "confirmation_evidence_required": True,
            "captcha_mfa_bypass_forbidden": True,
            "truthful_profile_only": True,
        },
    }


def derive_run_status(task_statuses: Iterable[str]) -> str:
    statuses = list(task_statuses)
    if not statuses:
        return "planned"
    if any(status == "failed" for status in statuses):
        return "failed"
    if any(status == "blocked" for status in statuses):
        return "blocked"
    if all(status in {"completed", "skipped"} for status in statuses):
        return "completed"
    if any(status == "running" for status in statuses):
        return "running"
    return "planned"
