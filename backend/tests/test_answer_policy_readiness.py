from datetime import datetime, timedelta

from app.models.answer_policy import ApplicantAnswerPolicy
from app.models.user import User
from app.services.answer_policy import load_runtime_policies, resolve_runtime_policy
from tests.conftest import TestingSessionLocal


def _complete_profile(db):
    user = db.query(User).filter(User.email == "test@example.com").one()
    user.phone = "+1 613 555 0100"
    user.address = "Ottawa, Ontario, Canada"
    user.resume_path = "/tmp/resume.pdf"
    db.commit()
    return user


def _policy_payload(key, answer="Yes", **overrides):
    payload = {
        "canonical_key": key,
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "allow_autofill": True,
        "confirmed": True,
        "provenance": "user_provided",
        "confidence": 1.0,
    }
    payload.update(overrides)
    return payload


def test_readiness_report_lists_exact_profile_and_policy_blockers(auth_client):
    response = auth_client.get(
        "/api/profile/answer-policies/readiness",
        params={
            "country_code": "CA",
            "target_url": "https://boards.greenhouse.io/acme/jobs/123",
            "company": "Acme",
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert report["platform"] == "greenhouse"
    assert report["ready_for_unattended"] is False
    assert report["summary"]["policies_required"] == 4
    assert {item["canonical_key"] for item in report["required_policies"]} == {
        "work_authorization",
        "sponsorship_required",
        "terms_consent",
        "data_processing_consent",
    }
    blocker_codes = {item["code"] for item in report["blockers"]}
    assert "profile_field_missing" in blocker_codes
    assert "policy_missing" in blocker_codes
    assert report["guarantees"][0].startswith("No missing legal")


def test_complete_canada_greenhouse_policy_pack_is_ready(auth_client):
    db = TestingSessionLocal()
    _complete_profile(db)
    db.close()

    payload = {
        "items": [
            _policy_payload("work_authorization", "Yes"),
            _policy_payload("sponsorship_required", "No"),
            _policy_payload("terms_consent", "I agree"),
            _policy_payload("data_processing_consent", "I agree"),
        ]
    }
    saved = auth_client.post("/api/profile/answer-policies/bulk", json=payload)
    assert saved.status_code == 200, saved.text

    response = auth_client.get(
        "/api/profile/answer-policies/readiness",
        params={
            "country_code": "CA",
            "target_url": "https://boards.greenhouse.io/acme/jobs/123",
            "company": "Acme",
        },
    )
    report = response.json()
    assert report["ready_for_unattended"] is True
    assert report["completeness_score"] == 100.0
    assert report["blockers"] == []
    assert report["conflicts"] == []
    assert report["summary"] == {
        "profile_fields_required": 5,
        "profile_fields_complete": 5,
        "policies_required": 4,
        "policies_ready": 4,
        "blocker_count": 0,
        "conflict_count": 0,
    }


def test_policy_records_provenance_confidence_and_explicit_consent(auth_client):
    response = auth_client.post(
        "/api/profile/answer-policies",
        json=_policy_payload(
            "work_authorization",
            "Yes",
            provenance="verified_import",
            confidence=0.97,
            source_metadata={"source": "reviewed_profile_import", "record": "profile-v2"},
        ),
    )
    assert response.status_code == 201, response.text
    policy = response.json()
    assert policy["provenance"] == "verified_import"
    assert policy["confidence"] == 0.97
    assert policy["consent_metadata"]["autofill_authorized"] is True
    assert policy["consent_metadata"]["confirmation_method"] == "authenticated_answer_policy_api"
    assert policy["source_metadata"]["record"] == "profile-v2"
    assert policy["encryption_valid"] is True

    db = TestingSessionLocal()
    stored = db.query(ApplicantAnswerPolicy).filter(ApplicantAnswerPolicy.id == policy["id"]).one()
    assert stored.encrypted_value != "Yes"
    assert "Yes" not in stored.encrypted_value
    db.close()


def test_low_confidence_policy_cannot_be_authorized(auth_client):
    response = auth_client.post(
        "/api/profile/answer-policies",
        json=_policy_payload("work_authorization", "Yes", confidence=0.50),
    )
    assert response.status_code == 400
    assert "confidence" in response.json()["detail"].lower()


def test_unknown_provenance_policy_cannot_be_authorized(auth_client):
    response = auth_client.post(
        "/api/profile/answer-policies",
        json=_policy_payload("work_authorization", "Yes", provenance="unknown"),
    )
    assert response.status_code == 400
    assert "provenance" in response.json()["detail"].lower()


def test_ai_suggestion_is_never_used_before_user_confirmation(auth_client):
    created = auth_client.post(
        "/api/profile/answer-policies",
        json={
            "canonical_key": "salary_expectation",
            "mode": "answer",
            "answer_value": "90000 CAD",
            "allow_autofill": False,
            "confirmed": False,
            "provenance": "ai_suggested",
            "confidence": 0.60,
        },
    )
    assert created.status_code == 201

    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").one()
    policies = load_runtime_policies(db, user.id)
    db.close()
    resolved = resolve_runtime_policy("What is your desired salary?", policies)
    assert resolved["matched"] is True
    assert resolved["can_autofill"] is False
    assert "policy_confidence_low" in resolved["blocker_codes"]
    assert "policy_not_confirmed" in resolved["blocker_codes"]


def test_expired_policy_fails_closed_at_runtime_and_in_readiness(auth_client):
    created = auth_client.post(
        "/api/profile/answer-policies",
        json=_policy_payload(
            "work_authorization",
            "Yes",
            expires_at=(datetime.utcnow() + timedelta(days=30)).isoformat(),
        ),
    ).json()

    db = TestingSessionLocal()
    user = _complete_profile(db)
    policy = db.query(ApplicantAnswerPolicy).filter(ApplicantAnswerPolicy.id == created["id"]).one()
    policy.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    policies = load_runtime_policies(db, user.id)
    db.close()

    resolved = resolve_runtime_policy("Are you legally authorized to work in Canada?", policies)
    assert resolved["can_autofill"] is False
    assert resolved["blocker_codes"][0] == "policy_expired"

    report = auth_client.get(
        "/api/profile/answer-policies/readiness",
        params={"country_code": "CA", "platform": "generic"},
    ).json()
    required = {
        item["canonical_key"]: item for item in report["required_policies"]
    }
    assert "policy_expired" in required["work_authorization"]["blocker_codes"]


def test_same_priority_scope_conflict_stops_runtime_and_readiness(auth_client):
    first = auth_client.post(
        "/api/profile/answer-policies",
        json=_policy_payload(
            "work_authorization",
            "Yes",
            scope="platform",
            scope_value="greenhouse.io",
        ),
    )
    second = auth_client.post(
        "/api/profile/answer-policies",
        json=_policy_payload(
            "work_authorization",
            "No",
            scope="platform",
            scope_value="boards.greenhouse.io",
        ),
    )
    assert first.status_code == 201
    assert second.status_code == 201

    db = TestingSessionLocal()
    user = _complete_profile(db)
    policies = load_runtime_policies(
        db,
        user.id,
        target_url="https://boards.greenhouse.io/acme/jobs/123",
        company="Acme",
    )
    db.close()
    resolved = resolve_runtime_policy("Are you legally authorized to work?", policies)
    assert resolved["can_autofill"] is False
    assert "Conflicting" in resolved["reason"]
    assert len(resolved["conflict_policy_ids"]) == 2

    report = auth_client.get(
        "/api/profile/answer-policies/readiness",
        params={
            "country_code": "CA",
            "target_url": "https://boards.greenhouse.io/acme/jobs/123",
            "company": "Acme",
        },
    ).json()
    assert report["ready_for_unattended"] is False
    assert report["summary"]["conflict_count"] == 1
    assert report["conflicts"][0]["canonical_key"] == "work_authorization"


def test_material_policy_edit_revokes_consent_and_authorization(auth_client):
    created = auth_client.post(
        "/api/profile/answer-policies",
        json=_policy_payload("sponsorship_required", "No"),
    ).json()

    updated = auth_client.patch(
        f"/api/profile/answer-policies/{created['id']}",
        json={"confidence": 0.92, "source_metadata": {"reason": "profile_refresh"}},
    )
    assert updated.status_code == 200
    policy = updated.json()
    assert policy["confirmed_at"] is None
    assert policy["allow_autofill"] is False
    assert policy["consent_metadata"] == {}


def test_corrupt_ciphertext_is_reported_without_leaking_or_guessing(auth_client):
    created = auth_client.post(
        "/api/profile/answer-policies",
        json=_policy_payload("work_authorization", "Yes"),
    ).json()

    db = TestingSessionLocal()
    _complete_profile(db)
    stored = db.query(ApplicantAnswerPolicy).filter(ApplicantAnswerPolicy.id == created["id"]).one()
    stored.encrypted_value = "not-valid-fernet-ciphertext"
    stored.encrypted_label = None
    db.commit()
    db.close()

    report = auth_client.get(
        "/api/profile/answer-policies/readiness",
        params={"country_code": "CA", "platform": "generic"},
    ).json()
    work_auth = next(
        item for item in report["required_policies"]
        if item["canonical_key"] == "work_authorization"
    )
    assert "policy_encryption_invalid" in work_auth["blocker_codes"]
    assert "policy_answer_missing" in work_auth["blocker_codes"]
