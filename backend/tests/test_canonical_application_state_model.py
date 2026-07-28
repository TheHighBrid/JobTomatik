from __future__ import annotations

import ast
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    SubmissionEvidence,
    SubmissionEvidenceType,
)
from app.models.job import Job
from app.models.user import User
from app.services.application_integrity import (
    reconcile_user_reported_status,
    submission_is_closed,
)
from app.services.application_recovery import recover_stale_application_attempt
from app.services.application_state import (
    InvalidApplicationTransition,
    application_state_transition_manifest,
    claim_application_attempt_result,
    record_submission_evidence,
    transition_application_state,
)


STATES = list(ApplicationAutomationState)
STATE_PAIRS = list(product(STATES, STATES))


def _make_application(db, *, suffix: str, state: ApplicationAutomationState) -> Application:
    user = User(
        email=f"state-{suffix}@example.test",
        hashed_password="test-hash",
        full_name="State Model Test",
    )
    job = Job(
        external_id=f"state-job-{suffix}",
        title="State Model Analyst",
        company="State Model Employer",
        url=f"https://example.test/jobs/{suffix}",
    )
    db.add_all([user, job])
    db.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=state.value,
        submission_attempt_count=0,
        submission_idempotency_key=f"state:{suffix}",
    )
    db.add(application)
    db.flush()
    return application


@pytest.mark.parametrize(
    ("source", "target"),
    STATE_PAIRS,
    ids=[f"{source.value}-to-{target.value}" for source, target in STATE_PAIRS],
)
def test_runtime_transition_matrix_matches_canonical_graph(db_session, source, target):
    application = _make_application(
        db_session,
        suffix=f"{source.value}-{target.value}",
        state=source,
    )
    manifest = application_state_transition_manifest()
    expected = source == target or target.value in manifest["allowed_transitions"][source.value]

    if target.value in manifest["evidence_required_states"]:
        record_submission_evidence(
            db_session,
            application,
            SubmissionEvidenceType.confirmation_page,
            is_sufficient=True,
            confirmation_text="Application received",
        )
        db_session.flush()

    if expected:
        event = transition_application_state(
            db_session,
            application,
            target,
            "transition_matrix_test",
        )
        assert event.from_state == source.value
        assert event.to_state == target.value
    else:
        with pytest.raises(InvalidApplicationTransition):
            transition_application_state(
                db_session,
                application,
                target,
                "transition_matrix_test",
            )


def test_submission_uncertain_cannot_become_submitted_without_evidence(db_session):
    application = _make_application(
        db_session,
        suffix="uncertain-no-evidence",
        state=ApplicationAutomationState.submission_uncertain,
    )

    with pytest.raises(InvalidApplicationTransition, match="evidence is required"):
        transition_application_state(
            db_session,
            application,
            ApplicationAutomationState.submitted,
            "unsafe_confirmation",
        )

    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value


def test_submission_uncertain_can_advance_after_sufficient_evidence(db_session):
    application = _make_application(
        db_session,
        suffix="uncertain-with-evidence",
        state=ApplicationAutomationState.submission_uncertain,
    )
    record_submission_evidence(
        db_session,
        application,
        SubmissionEvidenceType.confirmation_page,
        is_sufficient=True,
        final_url="https://example.test/application/complete",
        confirmation_text="Thank you for applying",
    )
    db_session.flush()

    transition_application_state(
        db_session,
        application,
        ApplicationAutomationState.submitted,
        "accepted_confirmation_evidence",
    )

    assert application.automation_state == ApplicationAutomationState.submitted.value


def test_stale_worker_result_checkpoint_is_rejected_without_state_change(db_session):
    application = _make_application(
        db_session,
        suffix="stale-worker",
        state=ApplicationAutomationState.applying,
    )
    application.submission_attempt_count = 2
    db_session.commit()

    stale_claim = claim_application_attempt_result(db_session, application.id, 1)
    db_session.commit()
    db_session.refresh(application)

    assert stale_claim is None
    assert application.automation_state == ApplicationAutomationState.applying.value
    assert application.submission_attempt_count == 2
    event = db_session.query(ApplicationEvent).filter(
        ApplicationEvent.application_id == application.id,
        ApplicationEvent.event_type == "stale_application_worker_result_discarded",
    ).one()
    assert event.payload["worker_attempt"] == 1
    assert event.payload["active_attempt"] == 2

    active_claim = claim_application_attempt_result(db_session, application.id, 2)
    assert active_claim is not None


def test_partial_transition_transaction_rolls_back_state_and_event(db_session):
    application = _make_application(
        db_session,
        suffix="partial-transaction",
        state=ApplicationAutomationState.ready_to_apply,
    )
    application_id = application.id
    db_session.commit()

    transition_application_state(
        db_session,
        application,
        ApplicationAutomationState.applying,
        "application_attempt_started",
        {"attempt": 1, "dry_run": True},
    )
    db_session.flush()
    db_session.rollback()

    reloaded = db_session.query(Application).filter(Application.id == application_id).one()
    assert reloaded.automation_state == ApplicationAutomationState.ready_to_apply.value
    assert db_session.query(ApplicationEvent).filter(
        ApplicationEvent.application_id == application_id,
        ApplicationEvent.event_type == "application_attempt_started",
    ).count() == 0


def test_crash_between_submit_action_and_evidence_capture_fails_closed(db_session):
    application = _make_application(
        db_session,
        suffix="click-before-evidence-crash",
        state=ApplicationAutomationState.applying,
    )
    now = datetime.utcnow().replace(microsecond=0)
    application.status = ApplicationStatus.applying
    application.submission_attempt_count = 1
    application.last_submission_attempt_at = now - timedelta(minutes=60)
    db_session.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="application_attempt_started",
            from_state=ApplicationAutomationState.ready_to_apply.value,
            to_state=ApplicationAutomationState.applying.value,
            payload={"attempt": 1, "dry_run": False},
        )
    )
    db_session.commit()

    result = recover_stale_application_attempt(
        db_session,
        application,
        now=now,
        timeout_minutes=30,
    )
    db_session.commit()
    db_session.refresh(application)

    assert result["recovered"] is True
    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value
    assert db_session.query(SubmissionEvidence).filter(
        SubmissionEvidence.application_id == application.id,
    ).count() == 0


def test_user_reported_applied_status_closes_queue_without_fabricating_state(db_session):
    application = _make_application(
        db_session,
        suffix="user-reported-applied",
        state=ApplicationAutomationState.ready_to_apply,
    )
    application.status = ApplicationStatus.applied

    reconcile_user_reported_status(
        db_session,
        application,
        ApplicationStatus.applied,
        user_id=application.user_id,
    )
    db_session.commit()
    db_session.refresh(application)

    assert submission_is_closed(application) is True
    assert application.automation_state == ApplicationAutomationState.ready_to_apply.value
    assert db_session.query(SubmissionEvidence).filter(
        SubmissionEvidence.application_id == application.id,
    ).count() == 0
    event = db_session.query(ApplicationEvent).filter(
        ApplicationEvent.application_id == application.id,
        ApplicationEvent.event_type == "application_status_reconciled",
    ).one()
    assert event.from_state == event.to_state == ApplicationAutomationState.ready_to_apply.value
    assert event.payload["automation_state_inferred"] is False


def test_runtime_code_has_zero_direct_automation_state_assignments():
    root = Path(__file__).resolve().parents[1] / "app"
    allowed_file = root / "services" / "application_state.py"
    violations = []

    for path in root.rglob("*.py"):
        if path == allowed_file:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            elif isinstance(node, ast.AugAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "automation_state":
                    violations.append(f"{path.relative_to(root.parent)}:{node.lineno}")

    assert violations == [], "Direct automation_state writes bypass the state service: " + ", ".join(violations)
