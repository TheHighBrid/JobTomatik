from app.models.answer_policy import ApplicantAnswerPolicy
from app.services.answer_policy import load_runtime_policies, resolve_runtime_policy
from tests.conftest import TestingSessionLocal


def test_answer_policy_catalog_requires_auth(client):
    response = client.get("/api/profile/answer-policies/catalog")
    assert response.status_code == 401


def test_catalog_covers_common_question_families_and_option_labels(auth_client):
    response = auth_client.get("/api/profile/answer-policies/catalog")
    assert response.status_code == 200
    catalog = {item["canonical_key"]: item for item in response.json()}

    assert len(catalog) >= 45
    assert {
        "work_authorization",
        "salary_expectation",
        "shift_availability",
        "race_ethnicity",
        "data_retention_consent",
        "why_this_company",
    }.issubset(catalog)
    assert "Man" in catalog["gender_identity"]["fallback_suggestions"]
    assert "North African" in catalog["race_ethnicity"]["fallback_suggestions"]
    assert "Middle Eastern" in catalog["race_ethnicity"]["fallback_suggestions"]


def test_autofill_policy_requires_explicit_confirmation(auth_client):
    response = auth_client.post(
        "/api/profile/answer-policies",
        json={
            "canonical_key": "work_authorization",
            "mode": "answer",
            "answer_value": "Yes",
            "allow_autofill": True,
            "confirmed": False,
        },
    )
    assert response.status_code == 400
    assert "explicit user confirmation" in response.json()["detail"]


def test_confirmed_policy_is_encrypted_at_rest_and_decrypted_for_owner(auth_client):
    response = auth_client.post(
        "/api/profile/answer-policies",
        json={
            "canonical_key": "work_authorization",
            "mode": "answer",
            "answer_value": "Yes",
            "answer_label": "Yes",
            "allow_autofill": True,
            "confirmed": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["answer_value"] == "Yes"
    assert data["confirmed_at"] is not None

    db = TestingSessionLocal()
    stored = db.query(ApplicantAnswerPolicy).filter(ApplicantAnswerPolicy.id == data["id"]).first()
    assert stored.encrypted_value
    assert stored.encrypted_value != "Yes"
    assert "Yes" not in stored.encrypted_value
    db.close()


def test_fallback_answers_are_encrypted_and_resolved_in_order(auth_client):
    response = auth_client.post(
        "/api/profile/answer-policies",
        json={
            "canonical_key": "gender_identity",
            "mode": "answer",
            "answer_value": "Male",
            "fallback_answers": ["Man", "M", "Prefer not to answer"],
            "allow_autofill": True,
            "confirmed": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["fallback_answers"] == ["Man", "M", "Prefer not to answer"]

    db = TestingSessionLocal()
    stored = db.query(ApplicantAnswerPolicy).filter(ApplicantAnswerPolicy.id == data["id"]).first()
    assert stored.encrypted_fallbacks
    assert "Prefer not to answer" not in stored.encrypted_fallbacks
    runtime = load_runtime_policies(db, stored.user_id)
    db.close()

    resolved = resolve_runtime_policy("What is your gender?", runtime)
    assert resolved["answer"] == "Male"
    assert resolved["answer_candidates"] == ["Male", "Man", "M", "Prefer not to answer"]


def test_changing_fallbacks_revokes_confirmation_and_autofill(auth_client):
    created = auth_client.post(
        "/api/profile/answer-policies",
        json={
            "canonical_key": "gender_identity",
            "mode": "answer",
            "answer_value": "Male",
            "fallback_answers": ["Man"],
            "allow_autofill": True,
            "confirmed": True,
        },
    ).json()

    updated = auth_client.patch(
        f"/api/profile/answer-policies/{created['id']}",
        json={"fallback_answers": ["Man", "M"]},
    )
    assert updated.status_code == 200
    assert updated.json()["confirmed_at"] is None
    assert updated.json()["allow_autofill"] is False


def test_bulk_setup_creates_and_updates_multiple_policies(auth_client):
    payload = {
        "items": [
            {
                "canonical_key": "gender_identity",
                "mode": "answer",
                "answer_value": "Male",
                "fallback_answers": ["Man"],
                "allow_autofill": True,
                "confirmed": True,
            },
            {
                "canonical_key": "race_ethnicity",
                "mode": "answer",
                "answer_value": "North African",
                "fallback_answers": ["Middle Eastern", "Prefer not to answer"],
                "allow_autofill": True,
                "confirmed": True,
            },
        ]
    }
    created = auth_client.post("/api/profile/answer-policies/bulk", json=payload)
    assert created.status_code == 200
    assert created.json()["created"] == 2
    assert created.json()["updated"] == 0

    payload["items"][0]["fallback_answers"] = ["Man", "M"]
    updated = auth_client.post("/api/profile/answer-policies/bulk", json=payload)
    assert updated.status_code == 200
    assert updated.json()["created"] == 0
    assert updated.json()["updated"] == 2


def test_changing_answer_revokes_confirmation_and_autofill(auth_client):
    created = auth_client.post(
        "/api/profile/answer-policies",
        json={
            "canonical_key": "salary_expectation",
            "mode": "answer",
            "answer_value": "85000 CAD",
            "allow_autofill": True,
            "confirmed": True,
        },
    ).json()

    updated = auth_client.patch(
        f"/api/profile/answer-policies/{created['id']}",
        json={"answer_value": "90000 CAD"},
    )
    assert updated.status_code == 200
    data = updated.json()
    assert data["answer_value"] == "90000 CAD"
    assert data["confirmed_at"] is None
    assert data["allow_autofill"] is False


def test_runtime_policy_respects_platform_scope(auth_client):
    profile = auth_client.get("/api/profile").json()
    response = auth_client.post(
        "/api/profile/answer-policies",
        json={
            "canonical_key": "sponsorship_required",
            "mode": "answer",
            "answer_value": "No",
            "scope": "platform",
            "scope_value": "greenhouse.io",
            "allow_autofill": True,
            "confirmed": True,
        },
    )
    assert response.status_code == 201

    db = TestingSessionLocal()
    matching = load_runtime_policies(
        db,
        profile["id"],
        target_url="https://boards.greenhouse.io/acme/jobs/123",
        company="Acme",
    )
    non_matching = load_runtime_policies(
        db,
        profile["id"],
        target_url="https://jobs.lever.co/acme/123",
        company="Acme",
    )
    db.close()

    assert len(matching) == 1
    assert matching[0]["answer_value"] == "No"
    assert non_matching == []


def test_unapproved_question_is_never_resolved_from_defaults():
    result = resolve_runtime_policy("Are you legally authorized to work in Canada?", [])
    assert result["canonical_key"] == "work_authorization"
    assert result["can_autofill"] is False
    assert result["matched"] is False
