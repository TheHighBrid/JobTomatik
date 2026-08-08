from types import SimpleNamespace

import pytest

from app.api import recovery as recovery_api
from app.models.intelligence import AgentRun, AgentTask
from app.models.user import User
from app.services.agent_execution import approve_run
from app.services.dead_letter import (
    DeadLetterError,
    checkpoint_hash,
    list_dead_letters,
    requeue_dead_letter,
    resolve_dead_letter,
    route_task_to_dead_letter,
)


def _user(db_session, email="dead-letter@example.test"):
    user = User(
        email=email,
        hashed_password="dead-letter-test-hash",
        full_name="Dead Letter Test",
        profile_data={},
        job_preferences={},
        automation_settings={},
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _run(db_session, user, *, with_downstream=True):
    plan = [
        {
            "id": "primary",
            "name": "Primary bounded task",
            "agent_type": "company_research",
            "dependencies": [],
            "input": {"job_id": 123},
        }
    ]
    if with_downstream:
        plan.append(
            {
                "id": "downstream",
                "name": "Downstream bounded task",
                "agent_type": "evaluation",
                "dependencies": ["primary"],
                "input": {"job_id": 123},
            }
        )
    run = AgentRun(
        user_id=user.id,
        objective="Synthetic dead-letter recovery",
        status="running",
        autonomy_level="reviewed",
        risk_level="low",
        requires_approval=True,
        plan=plan,
        run_context={"job_id": 123},
    )
    db_session.add(run)
    db_session.flush()
    primary = AgentTask(
        run_id=run.id,
        sequence=0,
        name="Primary bounded task",
        agent_type="company_research",
        status="failed",
        dependencies=[],
        task_input={"job_id": 123},
        task_output={"execution": {"failure_class": "worker_exception"}},
        attempt_count=2,
        max_attempts=2,
        error="synthetic worker failure",
    )
    db_session.add(primary)
    downstream = None
    if with_downstream:
        downstream = AgentTask(
            run_id=run.id,
            sequence=1,
            name="Downstream bounded task",
            agent_type="evaluation",
            status="skipped",
            dependencies=["primary"],
            task_input={"job_id": 123},
            task_output={
                "dependency_failures": [
                    {"dependency": "primary", "status": "failed"}
                ]
            },
            error="Skipped because a dependency did not complete safely",
        )
        db_session.add(downstream)
    db_session.flush()
    db_session.refresh(run)
    approve_run(run, user_id=user.id, note="bounded recovery test")
    db_session.flush()
    return run, primary, downstream


def _open_dead_letter(db_session, run, task):
    envelope = route_task_to_dead_letter(
        db_session,
        run,
        task,
        failure_class="attempt_limit_reached",
        error=task.error,
        source="test",
    )
    db_session.flush()
    return envelope


def test_dead_letter_is_durable_fail_closed_and_deduplicated(db_session):
    user = _user(db_session)
    run, task, _ = _run(db_session, user, with_downstream=False)

    first = _open_dead_letter(db_session, run, task)
    second = _open_dead_letter(db_session, run, task)

    assert first["status"] == "open"
    assert first["automatic_retry_allowed"] is False
    assert first["submission_authorized"] is False
    assert first["outreach_authorized"] is False
    assert first["checkpoint_hash"] == checkpoint_hash(run, task)
    assert second == first
    assert task.task_output["dead_letter"]["checkpoint_hash"] == first["checkpoint_hash"]


def test_requeue_requires_exact_checkpoint_and_preserves_attempt_history(db_session):
    user = _user(db_session)
    run, task, downstream = _run(db_session, user)
    envelope = _open_dead_letter(db_session, run, task)

    with pytest.raises(DeadLetterError, match="Exact dead-letter acknowledgment"):
        requeue_dead_letter(
            db_session,
            user_id=user.id,
            task_id=task.id,
            acknowledgment="REQUEUE IT",
        )

    result = requeue_dead_letter(
        db_session,
        user_id=user.id,
        task_id=task.id,
        acknowledgment=envelope["expected_requeue_acknowledgment"],
    )

    assert result["dispatch_required"] is True
    assert result["submission_authorized"] is False
    assert result["outreach_authorized"] is False
    assert task.status == "pending"
    assert task.attempt_count == 2
    assert task.max_attempts == 3
    assert downstream.status == "pending"
    assert downstream.id in result["reset_dependency_task_ids"]


def test_checkpoint_drift_blocks_requeue(db_session):
    user = _user(db_session)
    run, task, _ = _run(db_session, user, with_downstream=False)
    envelope = _open_dead_letter(db_session, run, task)
    task.task_input = {"job_id": 999, "changed": True}
    db_session.flush()

    with pytest.raises(DeadLetterError, match="checkpoint drift"):
        requeue_dead_letter(
            db_session,
            user_id=user.id,
            task_id=task.id,
            acknowledgment=envelope["expected_requeue_acknowledgment"],
        )
    assert task.status == "failed"


def test_dead_letter_queue_is_account_scoped(db_session):
    first_user = _user(db_session, "first-dead-letter@example.test")
    second_user = _user(db_session, "second-dead-letter@example.test")
    run, task, _ = _run(db_session, first_user, with_downstream=False)
    _open_dead_letter(db_session, run, task)

    assert len(list_dead_letters(db_session, user_id=first_user.id)) == 1
    assert list_dead_letters(db_session, user_id=second_user.id) == []
    with pytest.raises(DeadLetterError, match="not found"):
        requeue_dead_letter(
            db_session,
            user_id=second_user.id,
            task_id=task.id,
            acknowledgment="anything",
        )


def test_resolve_acknowledges_without_retrying_failed_task(db_session):
    user = _user(db_session)
    run, task, _ = _run(db_session, user, with_downstream=False)
    envelope = _open_dead_letter(db_session, run, task)

    result = resolve_dead_letter(
        db_session,
        user_id=user.id,
        task_id=task.id,
        acknowledgment=envelope["expected_resolve_acknowledgment"],
        note="Reviewed and intentionally left failed.",
    )

    assert result["dispatch_required"] is False
    assert task.status == "failed"
    assert task.task_output["dead_letter"]["status"] == "resolved"


def test_manual_requeue_limit_is_bounded(db_session):
    user = _user(db_session)
    run, task, _ = _run(db_session, user, with_downstream=False)

    for expected_count in (1, 2):
        envelope = _open_dead_letter(db_session, run, task)
        result = requeue_dead_letter(
            db_session,
            user_id=user.id,
            task_id=task.id,
            acknowledgment=envelope["expected_requeue_acknowledgment"],
        )
        assert result["requeue_count"] == expected_count
        task.status = "failed"
        task.error = f"failed after manual requeue {expected_count}"
        task.attempt_count = task.max_attempts
        db_session.flush()

    envelope = _open_dead_letter(db_session, run, task)
    with pytest.raises(DeadLetterError, match="requeue limit"):
        requeue_dead_letter(
            db_session,
            user_id=user.id,
            task_id=task.id,
            acknowledgment=envelope["expected_requeue_acknowledgment"],
        )


def test_recovery_api_requeues_only_after_exact_acknowledgment(
    auth_client,
    db_session,
    monkeypatch,
):
    user = db_session.query(User).filter(User.email == "test@example.com").first()
    assert user is not None
    run, task, _ = _run(db_session, user, with_downstream=False)
    envelope = _open_dead_letter(db_session, run, task)
    db_session.commit()

    monkeypatch.setattr(
        recovery_api.dispatch_agent_run_task,
        "delay",
        lambda run_id: SimpleNamespace(id=f"dispatch-{run_id}"),
    )
    response = auth_client.post(
        f"/api/recovery/dead-letters/{task.id}/requeue",
        json={"acknowledgment": envelope["expected_requeue_acknowledgment"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["dispatch_task_id"] == f"dispatch-{run.id}"
    assert data["submission_authorized"] is False
    assert data["outreach_authorized"] is False
