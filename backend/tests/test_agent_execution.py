from types import SimpleNamespace

from app.api import agent_execution as agent_execution_api
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.intelligence import AgentRun, AgentTask, SelectorStrategy
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.agent_execution import (
    HandlerResult,
    approve_run,
    claim_task,
    execute_handler,
    execution_snapshot,
    persist_handler_result,
    queue_ready_tasks,
    settle_dependency_failures,
)
from app.services.discovery_pipeline import persist_discovery_results


def _current_user(db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").first()
    if user is None:
        user = User(
            email="test@example.com",
            hashed_password="phase4-test-only-password-hash",
            full_name="Phase 4 Test User",
            profile_data={},
            job_preferences={},
            automation_settings={},
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
    return user


def _run_with_tasks(db_session, user, *, requires_approval=True):
    plan = [
        {
            "id": "research",
            "name": "Research role",
            "agent_type": "company_research",
            "dependencies": [],
            "input": {},
        },
        {
            "id": "evaluate",
            "name": "Evaluate role",
            "agent_type": "evaluation",
            "dependencies": ["research"],
            "input": {},
        },
    ]
    run = AgentRun(
        user_id=user.id,
        objective="Research and evaluate a role",
        status="planned",
        autonomy_level="reviewed",
        risk_level="low",
        requires_approval=requires_approval,
        plan=plan,
        run_context={},
    )
    db_session.add(run)
    db_session.flush()
    first = AgentTask(
        run_id=run.id,
        sequence=0,
        name="Research role",
        agent_type="company_research",
        status="pending",
        dependencies=[],
        task_input={},
    )
    second = AgentTask(
        run_id=run.id,
        sequence=1,
        name="Evaluate role",
        agent_type="evaluation",
        status="pending",
        dependencies=["research"],
        task_input={},
    )
    db_session.add_all([first, second])
    db_session.flush()
    db_session.refresh(run)
    return run, first, second


def _register_and_login(client, email):
    register = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "testpass123",
            "full_name": email.split("@")[0],
        },
    )
    assert register.status_code == 201, register.text
    login = client.post(
        "/api/auth/login",
        data={"username": email, "password": "testpass123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_approval_scope_never_authorizes_submission_or_outreach(
    auth_client,
    monkeypatch,
):
    created = auth_client.post(
        "/api/intelligence/agent-runs",
        json={
            "objective": "Research and apply to a role, then contact the recruiter",
            "autonomy_level": "reviewed",
            "run_context": {},
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    snapshot = auth_client.get(f"/api/intelligence/agent-runs/{run_id}/execution")
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["approval_state"] == "pending"
    assert snapshot.json()["submission_authorized"] is False
    assert snapshot.json()["outreach_authorized"] is False

    blocked_dispatch = auth_client.post(
        f"/api/intelligence/agent-runs/{run_id}/dispatch"
    )
    assert blocked_dispatch.status_code == 409

    wrong = auth_client.post(
        f"/api/intelligence/agent-runs/{run_id}/approve",
        json={"acknowledgment": "APPROVE EVERYTHING"},
    )
    assert wrong.status_code == 422

    approved = auth_client.post(
        f"/api/intelligence/agent-runs/{run_id}/approve",
        json={
            "acknowledgment": f"APPROVE BOUNDED RUN {run_id}",
            "note": "Prepare evidence and readiness only.",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_state"] == "approved"
    assert approved.json()["execution_scope"] == "bounded_local_execution"
    assert approved.json()["submission_authorized"] is False
    assert approved.json()["outreach_authorized"] is False

    monkeypatch.setattr(
        agent_execution_api.dispatch_agent_run_task,
        "delay",
        lambda approved_run_id: SimpleNamespace(id=f"dispatch-{approved_run_id}"),
    )
    queued = auth_client.post(f"/api/intelligence/agent-runs/{run_id}/dispatch")
    assert queued.status_code == 200, queued.text
    assert queued.json()["celery_task_id"] == f"dispatch-{run_id}"
    assert queued.json()["snapshot"]["submission_authorized"] is False


def test_dependency_ordering_and_claim_lease_are_idempotent(db_session):
    user = _current_user(db_session)
    run, first, second = _run_with_tasks(
        db_session,
        user,
        requires_approval=False,
    )

    queued = queue_ready_tasks(run)
    assert [task_id for task_id, _ in queued] == [first.id]
    assert first.status == "queued"
    assert second.status == "pending"

    claimed, reason = claim_task(run, first, celery_task_id="worker-one")
    assert claimed is True
    assert reason == "claimed"
    assert first.status == "running"
    assert first.attempt_count == 1

    duplicate_claim, duplicate_reason = claim_task(
        run,
        first,
        celery_task_id="worker-two",
    )
    assert duplicate_claim is False
    assert duplicate_reason == "task_already_claimed"
    assert first.attempt_count == 1

    persist_handler_result(
        run,
        first,
        HandlerResult("completed", {"proof": "retained-data-only"}),
    )
    next_wave = queue_ready_tasks(run)
    assert [task_id for task_id, _ in next_wave] == [second.id]
    assert second.status == "queued"


def test_blocked_dependency_skips_downstream_task(db_session):
    user = _current_user(db_session)
    run, first, second = _run_with_tasks(
        db_session,
        user,
        requires_approval=False,
    )
    first.status = "blocked"
    first.error = "Evidence missing"

    changed = settle_dependency_failures(run)

    assert changed == [second.id]
    assert second.status == "skipped"
    assert "dependency" in second.error.lower()
    assert second.task_output["dependency_failures"][0]["task_id"] == first.id


def test_application_agent_is_preflight_only_and_fails_closed(db_session):
    user = _current_user(db_session)
    job = Job(
        external_id="phase4-preflight-role",
        title="Fraud Analyst",
        company="Example Bank",
        location="Ottawa, Ontario",
        url="https://example.com/jobs/phase4",
        source=JobSource.manual,
        status=JobStatus.approved,
        skills=["fraud", "investigation"],
    )
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.preparing.value,
        source_listing_url=job.url,
        submission_idempotency_key=f"phase4-preflight-{user.id}-{job.id}",
        submission_attempt_count=0,
    )
    db_session.add(application)
    db_session.flush()

    plan = [
        {
            "id": "prepare_application",
            "name": "Prepare application",
            "agent_type": "application",
            "dependencies": [],
            "input": {"application_id": application.id},
        }
    ]
    run = AgentRun(
        user_id=user.id,
        objective="Prepare application readiness",
        status="planned",
        autonomy_level="reviewed",
        risk_level="high",
        requires_approval=True,
        plan=plan,
        run_context={"application_id": application.id},
    )
    db_session.add(run)
    db_session.flush()
    task = AgentTask(
        run_id=run.id,
        sequence=0,
        name="Prepare application",
        agent_type="application",
        dependencies=[],
        task_input={"application_id": application.id},
    )
    db_session.add(task)
    db_session.flush()
    approve_run(run, user_id=user.id)

    result = execute_handler(db_session, run, task)

    assert result.status == "blocked"
    assert result.output["submission_attempted"] is False
    assert result.output["submission_authorized"] is False
    assert result.output["ready_for_separate_submission_preflight"] is False
    blocker_codes = {item["code"] for item in result.output["blockers"]}
    assert "application_target_missing" in blocker_codes
    assert "cover_letter_missing" in blocker_codes
    assert "resume_summary_missing" in blocker_codes
    assert application.submission_attempt_count == 0
    assert application.status == ApplicationStatus.pending
    assert application.automation_state == ApplicationAutomationState.preparing.value


def test_selector_diagnostics_and_control_are_user_scoped(
    client,
    db_session,
):
    user_a = _register_and_login(client, "phase4-selector-a@example.com")
    user_b = _register_and_login(client, "phase4-selector-b@example.com")

    created = client.post(
        "/api/intelligence/selectors/outcomes",
        headers=user_a,
        json={
            "platform": "lever",
            "page_signature": "phase4-application-v1",
            "intent": "continue",
            "selector": "button[data-qa='next']",
            "strategy_type": "css",
            "success": False,
            "failure_reason": "button missing",
        },
    )
    assert created.status_code == 200, created.text
    strategy_id = created.json()["id"]

    diagnostics = client.get("/api/intelligence/selectors", headers=user_a)
    assert diagnostics.status_code == 200, diagnostics.text
    assert [item["id"] for item in diagnostics.json()] == [strategy_id]
    assert diagnostics.json()[0]["circuit_state"] in {"degraded", "critical"}

    hidden = client.get("/api/intelligence/selectors", headers=user_b)
    assert hidden.status_code == 200
    assert hidden.json() == []

    forbidden = client.patch(
        f"/api/intelligence/selectors/{strategy_id}/control",
        headers=user_b,
        json={"is_disabled": True, "reason": "Not my strategy"},
    )
    assert forbidden.status_code == 404

    disabled = client.patch(
        f"/api/intelligence/selectors/{strategy_id}/control",
        headers=user_a,
        json={"is_disabled": True, "reason": "Circuit opened after repeated failure"},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["is_disabled"] is True
    assert disabled.json()["circuit_state"] == "open"


def test_agent_run_execution_is_account_scoped(client):
    user_a = _register_and_login(client, "phase4-run-a@example.com")
    user_b = _register_and_login(client, "phase4-run-b@example.com")

    created = client.post(
        "/api/intelligence/agent-runs",
        headers=user_a,
        json={
            "objective": "Evaluate an opportunity",
            "autonomy_level": "reviewed",
            "run_context": {},
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    hidden = client.get(
        f"/api/intelligence/agent-runs/{run_id}/execution",
        headers=user_b,
    )
    assert hidden.status_code == 404


def test_discovery_pipeline_can_reuse_parent_agent_run(db_session):
    user = _current_user(db_session)
    before = db_session.query(AgentRun).filter(AgentRun.user_id == user.id).count()

    result = persist_discovery_results(
        db_session,
        user,
        [],
        keywords="fraud analyst",
        search_params={"keywords": "fraud analyst", "sources": []},
        track_agent_run=False,
    )

    after = db_session.query(AgentRun).filter(AgentRun.user_id == user.id).count()
    assert result["agent_run_id"] is None
    assert result["total_found"] == 0
    assert after == before


def test_selector_control_persists_reason(db_session):
    user = _current_user(db_session)
    strategy = SelectorStrategy(
        user_id=user.id,
        platform="greenhouse",
        page_signature="phase4-form",
        intent="submit",
        selector="button[type='submit']",
        confidence=0.2,
        failure_count=4,
    )
    db_session.add(strategy)
    db_session.commit()

    snapshot = execution_snapshot(
        AgentRun(
            id=999,
            user_id=user.id,
            objective="Inspect only",
            status="planned",
            autonomy_level="reviewed",
            risk_level="low",
            requires_approval=False,
            plan=[],
            run_context={},
            tasks=[],
        )
    )
    assert snapshot["submission_authorized"] is False
    assert snapshot["outreach_authorized"] is False
