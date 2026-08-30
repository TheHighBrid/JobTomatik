from __future__ import annotations

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
)
from app.models.user import User
from app.services import lever_phase_b_current_intake as intake_service
from app.services.lever_phase_b_current_roster import (
    list_current_lever_phase_b_candidates,
)


POSTING_ID = "0d95c00e-3019-4390-8a57-c05d9bf58a10"
HOSTED_URL = f"https://jobs.lever.co/eqbank/{POSTING_ID}"
APPLY_URL = f"{HOSTED_URL}/apply"


def _verified_target():
    return {
        "platform": "lever",
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "verified": True,
        "blockers": [],
        "target_url": APPLY_URL,
        "canonical_application_url": APPLY_URL,
        "site": "eqbank",
        "posting_id": POSTING_ID,
        "region": "global",
        "official_title": "Bilingual Customer Care Representative (ENG & FR)",
        "title_matches_local_job": True,
        "posting_metadata_hash": "a" * 64,
        "identity_hash": "b" * 64,
        "verification_error": None,
        "verified_at": "2026-08-30T16:00:00",
    }


def _payload():
    return {
        "employer": "EQ Bank / Equitable Bank",
        "role": "Bilingual Customer Care Representative (ENG & FR)",
        "application_url": HOSTED_URL,
        "location": "Remote, Canada",
        "notes": "Preparation only",
        "source_reference": "current-lever-roster-test",
    }


def test_current_lever_roster_is_read_only_and_excludes_execution_states(
    auth_client,
    db_session,
    monkeypatch,
):
    async def verified(_job):
        return _verified_target()

    monkeypatch.setattr(
        intake_service,
        "resolve_supervised_target_metadata",
        verified,
    )

    response = auth_client.post("/api/supervised-pilot/lever-candidates", json=_payload())
    assert response.status_code == 201, response.text
    imported = response.json()
    application = (
        db_session.query(Application)
        .filter(Application.id == imported["application_id"])
        .one()
    )
    user = db_session.query(User).filter(User.id == application.user_id).one()
    event_count = db_session.query(ApplicationEvent).count()

    roster = list_current_lever_phase_b_candidates(db_session, user)
    assert roster["selection_policy"] == "user_selected_exact_application_no_ranking"
    assert roster["ordering"] == "application_created_at_ascending_no_ranking"
    assert roster["read_only"] is True
    assert roster["candidate_count"] == 1
    assert roster["eligible_count"] == 1
    assert roster["approval_issued"] is False
    assert roster["submission_queued"] is False
    assert roster["runtime_flags_changed"] is False

    candidate = roster["candidates"][0]
    assert candidate["application_id"] == application.id
    assert candidate["job_id"] == application.job_id
    assert candidate["application_url"] == APPLY_URL
    assert candidate["automation_state"] == ApplicationAutomationState.preparing.value
    assert candidate["target_identity_verified"] is True
    assert candidate["target_identity_blockers"] == []
    assert candidate["material_preparation_eligible"] is True
    assert candidate["eligibility_blockers"] == []
    assert db_session.query(ApplicationEvent).count() == event_count

    application.automation_state = ApplicationAutomationState.confirmed.value
    db_session.add(application)
    db_session.commit()
    event_count = db_session.query(ApplicationEvent).count()

    terminal_roster = list_current_lever_phase_b_candidates(db_session, user)
    assert terminal_roster["candidate_count"] == 1
    assert terminal_roster["eligible_count"] == 0
    terminal = terminal_roster["candidates"][0]
    assert terminal["application_id"] == application.id
    assert terminal["automation_state"] == ApplicationAutomationState.confirmed.value
    assert terminal["material_preparation_eligible"] is False
    assert terminal["eligibility_blockers"] == [
        "automation_state_not_material_preparation_eligible"
    ]
    assert db_session.query(ApplicationEvent).count() == event_count
