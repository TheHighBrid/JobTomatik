from datetime import datetime

from app.models.answer_policy import ApplicantAnswerPolicy
from app.models.user import User
from app.services.answer_policy import load_runtime_policies
from app.services.control_policy import resolve_control_policy
from tests.conftest import TestingSessionLocal


def test_owner_can_reenter_legacy_encrypted_answer_and_reauthorize_in_one_patch(auth_client):
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "test@example.com").one()
        policy = ApplicantAnswerPolicy(
            user_id=user.id,
            canonical_key="degree_completion",
            category="education",
            sensitivity="standard",
            mode="answer",
            encrypted_value="legacy-unreadable-value",
            encrypted_label="legacy-unreadable-label",
            encrypted_fallbacks="legacy-unreadable-fallbacks",
            match_phrases=[],
            scope="global",
            scope_value="",
            allow_autofill=True,
            is_active=True,
            confirmed_at=datetime.utcnow(),
            provenance="user_provided",
            confidence=1.0,
            consent_metadata={"autofill_authorized": True},
        )
        db.add(policy)
        db.commit()
        db.refresh(policy)
        policy_id = policy.id
        user_id = user.id
    finally:
        db.close()

    before = auth_client.get("/api/profile/answer-policies").json()
    legacy = next(item for item in before if item["id"] == policy_id)
    assert legacy["encryption_valid"] is False
    assert legacy["answer_value"] is None

    response = auth_client.patch(
        f"/api/profile/answer-policies/{policy_id}",
        json={
            "answer_value": "Yes",
            "answer_label": "Yes",
            "fallback_answers": [],
            "allow_autofill": True,
            "confirmed": True,
            "is_active": True,
        },
    )

    assert response.status_code == 200
    repaired = response.json()
    assert repaired["answer_value"] == "Yes"
    assert repaired["answer_label"] == "Yes"
    assert repaired["fallback_answers"] == []
    assert repaired["encryption_valid"] is True
    assert repaired["allow_autofill"] is True
    assert repaired["confirmed_at"] is not None

    db = TestingSessionLocal()
    try:
        policies = load_runtime_policies(
            db,
            user_id,
            target_url="https://jobs.lever.co/caseware/example/apply",
            company="Caseware",
        )
    finally:
        db.close()

    resolution = resolve_control_policy("Do you have post-secondary education?", policies)
    assert resolution["canonical_key"] == "degree_completion"
    assert resolution["can_autofill"] is True
    assert resolution["answer_candidates"] == ["Yes"]
    assert resolution["blocker_codes"] == []
