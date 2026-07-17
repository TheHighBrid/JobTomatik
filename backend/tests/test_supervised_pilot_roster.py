from datetime import datetime, timedelta

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewTask,
)
from app.models.job import Job
from app.models.user import User
from app.services.supervised_pilot_roster import build_supervised_pilot_roster


def _user(db_session, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nphase-b-roster\n")
    user = User(
        email="phase-b-roster@example.test",
        hashed_password="not-used",
        full_name="Phase B Operator",
        resume_path=str(resume),
        profile_data={},
    )
    db_session.add(user)
    db_session.flush()
    return user


def _job(db_session, *, external_id, company, title, url):
    job = Job(
        external_id=external_id,
        company=company,
        title=title,
        url=url,
        raw_data={"application_method": "external_url"},
    )
    db_session.add(job)
    db_session.flush()
    return job


def _application(
    db_session,
    *,
    user,
    job,
    state,
    created_at,
    cover_letter="Prepared cover letter",
):
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=state,
        submission_idempotency_key=f"application:{user.id}:job:{job.id}",
        cover_letter=cover_letter,
        created_at=created_at,
    )
    db_session.add(application)
    db_session.flush()
    return application


def _readiness(confirmed=0):
    return {
        "summary": {
            "qualifying_dry_run_count": 30,
            "distinct_dry_run_employer_count": 30,
            "supervised_confirmed_count": confirmed,
        }
    }


def test_roster_lists_only_greenhouse_in_creation_order_without_ranking(db_session, tmp_path):
    user = _user(db_session, tmp_path)
    first_job = _job(
        db_session,
        external_id="gh-first",
        company="First Employer",
        title="First Role",
        url="https://job-boards.greenhouse.io/first/jobs/1",
    )
    ignored_job = _job(
        db_session,
        external_id="lever-ignored",
        company="Ignored Employer",
        title="Ignored Role",
        url="https://jobs.lever.co/ignored/1",
    )
    second_job = _job(
        db_session,
        external_id="gh-second",
        company="Second Employer",
        title="Second Role",
        url="https://job-boards.greenhouse.io/second/jobs/2",
    )
    first = _application(
        db_session,
        user=user,
        job=first_job,
        state=ApplicationAutomationState.ready_to_apply.value,
        created_at=datetime(2026, 7, 17, 10, 0, 0),
    )
    _application(
        db_session,
        user=user,
        job=ignored_job,
        state=ApplicationAutomationState.ready_to_apply.value,
        created_at=datetime(2026, 7, 17, 10, 30, 0),
    )
    second = _application(
        db_session,
        user=user,
        job=second_job,
        state=ApplicationAutomationState.preparing.value,
        created_at=datetime(2026, 7, 17, 11, 0, 0),
    )
    db_session.commit()

    roster = build_supervised_pilot_roster(db_session, user, readiness=_readiness())

    assert roster["selection_policy"] == "user_selected_exact_application"
    assert roster["ordering"] == "application_created_at_ascending_no_ranking"
    assert [item["application_id"] for item in roster["candidates"]] == [first.id, second.id]
    assert roster["candidate_count"] == 2
    assert roster["technically_ready_count"] == 1
    assert roster["candidates"][0]["technical_ready"] is True
    assert roster["candidates"][0]["execution_ready"] is False
    assert roster["candidates"][0]["execution_blockers"] == [
        "global_live_submit_disabled",
        "greenhouse_supervised_pilot_disabled",
    ]
    assert "application_not_ready_to_apply" in roster["candidates"][1]["technical_blockers"]


def test_roster_surfaces_manual_review_and_phase_progress(db_session, tmp_path):
    user = _user(db_session, tmp_path)
    job = _job(
        db_session,
        external_id="gh-review",
        company="Review Employer",
        title="Review Role",
        url="https://job-boards.greenhouse.io/review/jobs/3",
    )
    application = _application(
        db_session,
        user=user,
        job=job,
        state=ApplicationAutomationState.ready_to_apply.value,
        created_at=datetime(2026, 7, 17, 12, 0, 0),
    )
    db_session.add(
        ManualReviewTask(
            application_id=application.id,
            reason_code="ambiguous_question",
            status="open",
            summary="A question requires an explicit answer policy.",
            details={},
        )
    )
    db_session.commit()

    roster = build_supervised_pilot_roster(db_session, user, readiness=_readiness(confirmed=4))

    assert roster["phase_a"] == {
        "qualifying_dry_run_count": 30,
        "distinct_employer_count": 30,
        "complete": True,
    }
    assert roster["phase_b"] == {
        "confirmed_count": 4,
        "target": 10,
        "remaining": 6,
        "complete": False,
    }
    candidate = roster["candidates"][0]
    assert candidate["roster_status"] == "blocked"
    assert candidate["unresolved_manual_review_count"] == 1
    assert "unresolved_manual_reviews" in candidate["technical_blockers"]


def test_confirmed_and_ingested_applications_are_labeled_not_reselected(db_session, tmp_path):
    user = _user(db_session, tmp_path)
    job = _job(
        db_session,
        external_id="gh-complete",
        company="Completed Employer",
        title="Completed Role",
        url="https://job-boards.greenhouse.io/complete/jobs/4",
    )
    application = _application(
        db_session,
        user=user,
        job=job,
        state=ApplicationAutomationState.confirmed.value,
        created_at=datetime(2026, 7, 17, 13, 0, 0),
    )
    db_session.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="supervised_pilot_record_ingested",
            from_state=ApplicationAutomationState.confirmed.value,
            to_state=ApplicationAutomationState.confirmed.value,
            payload={"run_id": "gh-supervised-test"},
        )
    )
    db_session.commit()

    roster = build_supervised_pilot_roster(db_session, user, readiness=_readiness(confirmed=1))
    candidate = roster["candidates"][0]

    assert candidate["already_confirmed"] is True
    assert candidate["already_ingested"] is True
    assert candidate["roster_status"] == "recorded_in_pilot_ledger"


def test_roster_endpoint_is_authenticated_and_returns_phase_a_baseline(auth_client):
    response = auth_client.get("/api/supervised-pilot/roster")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selection_policy"] == "user_selected_exact_application"
    assert payload["phase_a"]["qualifying_dry_run_count"] == 30
    assert payload["phase_a"]["distinct_employer_count"] == 30
    assert payload["phase_b"]["target"] == 10
    assert payload["execution_flags"] == {
        "global_live_submit_enabled": False,
        "greenhouse_supervised_pilot_enabled": False,
    }
