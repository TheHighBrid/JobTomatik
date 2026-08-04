from app.models.material import EvidenceUnit
from app.models.user import User
from app.services.evidence_ledger import (
    profile_evidence_candidates,
    rebuild_user_evidence,
    resume_text_candidates,
)


def _user(db_session):
    return db_session.query(User).filter(User.email == "test@example.com").one()


def test_profile_evidence_uses_factual_fields_not_target_preferences(auth_client, db_session):
    user = _user(db_session)
    user.full_name = "Test Applicant"
    user.profile_data = {
        "current_role": "Fraud Analyst",
        "years_experience": "4",
        "employment_history": "RBC | Fraud Operations | Reviewed suspicious transactions",
        "key_achievements": "Documented investigation outcomes for audit review",
    }
    user.job_preferences = {
        "skills": ["AML", "KYC"],
        "preferred_titles": ["Director of Financial Crime"],
    }

    candidates = profile_evidence_candidates(user)
    statements = {item["statement"] for item in candidates}

    assert "Test Applicant" in statements
    assert "Fraud Analyst" in statements
    assert "AML" in statements
    assert "KYC" in statements
    assert "Director of Financial Crime" not in statements
    employment = next(item for item in candidates if item["kind"] == "employment")
    assert employment["organization"] == "RBC"
    assert employment["role"] == "Fraud Operations"


def test_resume_text_candidates_preserve_verbatim_lines_and_section(auth_client):
    candidates = resume_text_candidates(
        """
        EXPERIENCE
        Fraud Analyst | Example Bank
        Reviewed transaction alerts and documented findings
        SKILLS
        AML investigations
        """,
        source_ref="resume:test.pdf",
    )

    assert [item["statement"] for item in candidates] == [
        "Fraud Analyst | Example Bank",
        "Reviewed transaction alerts and documented findings",
        "AML investigations",
    ]
    assert candidates[0]["kind"] == "employment"
    assert candidates[-1]["kind"] == "skill"
    assert all(item["provenance"]["verbatim"] is True for item in candidates)


def test_rebuild_versions_changed_profile_evidence_and_deactivates_stale(auth_client, db_session):
    user = _user(db_session)
    user.profile_data = {"current_role": "Fraud Analyst"}
    db_session.commit()

    first = rebuild_user_evidence(db_session, user)
    db_session.commit()
    first_unit = (
        db_session.query(EvidenceUnit)
        .filter(
            EvidenceUnit.user_id == user.id,
            EvidenceUnit.source_ref == "profile:current_role",
            EvidenceUnit.is_active.is_(True),
        )
        .one()
    )

    user.profile_data = {"current_role": "AML Investigator"}
    second = rebuild_user_evidence(db_session, user)
    db_session.commit()

    db_session.refresh(first_unit)
    active = (
        db_session.query(EvidenceUnit)
        .filter(
            EvidenceUnit.user_id == user.id,
            EvidenceUnit.source_ref == "profile:current_role",
            EvidenceUnit.is_active.is_(True),
        )
        .one()
    )
    assert first["created"] > 0
    assert second["deactivated"] >= 1
    assert first_unit.is_active is False
    assert active.statement == "AML Investigator"
    assert active.id != first_unit.id


def test_evidence_api_is_user_scoped(auth_client, db_session):
    user = _user(db_session)
    user.profile_data = {"current_role": "Fraud Analyst"}
    db_session.commit()

    rebuild = auth_client.post("/api/materials/evidence/rebuild")
    assert rebuild.status_code == 200
    assert rebuild.json()["total_active"] >= 2

    created = auth_client.post(
        "/api/materials/evidence",
        json={
            "kind": "achievement",
            "label": "Case quality",
            "statement": "Maintained clear audit-ready case notes",
        },
    )
    assert created.status_code == 201
    evidence_id = created.json()["id"]

    listed = auth_client.get("/api/materials/evidence")
    assert listed.status_code == 200
    assert evidence_id in {item["id"] for item in listed.json()}

    removed = auth_client.delete(f"/api/materials/evidence/{evidence_id}")
    assert removed.status_code == 204
    active_ids = {
        item["id"]
        for item in auth_client.get("/api/materials/evidence").json()
    }
    assert evidence_id not in active_ids
