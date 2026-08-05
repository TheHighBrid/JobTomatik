from app.models.application import ApplicationAutomationState
from app.models.material import EvidenceUnit
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services import lever_phase_b_reviewed_materials as reviewed_materials
from app.services.evidence_ledger import evidence_hash


REVIEW_ID = "D8-026"
POSTING_ID = "7d4a0f39-7771-4d19-b328-e8705cac1623"
APPLICATION_URL = f"https://jobs.lever.co/cin7/{POSTING_ID}/apply"


def _posting():
    return {
        "id": POSTING_ID,
        "text": "Customer Success Manager",
        "categories": {
            "commitment": "Full-Time",
            "location": "Toronto, CAN",
            "team": "Customer Success",
            "allLocations": ["Toronto, CAN"],
        },
        "description": "<p>Lead onboarding and customer retention.</p>",
        "descriptionPlain": "Lead onboarding and customer retention programs.",
        "hostedUrl": f"https://jobs.lever.co/cin7/{POSTING_ID}",
        "applyUrl": APPLICATION_URL,
        "lists": [
            {
                "text": "Qualifications",
                "content": "<p>Customer success and communication experience.</p>",
            }
        ],
    }


def _configure_user(db_session, tmp_path):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    resume = tmp_path / "owner-resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nowner resume\n")
    user.resume_path = str(resume)
    user.resume_filename = resume.name
    user.full_name = "Test Applicant"
    user.profile_data = {
        "current_role": "Customer Success Specialist",
        "years_experience": "5",
        "employment_history": (
            "Example SaaS | Customer Success Specialist | Led onboarding"
        ),
        "key_achievements": "Improved onboarding completion",
    }
    user.job_preferences = {
        "skills": ["Customer Success", "Onboarding", "Communication"]
    }
    db_session.commit()
    return user


def _patch_resume_evidence(monkeypatch):
    original = reviewed_materials.rebuild_user_evidence

    def rebuild(db, user):
        result = original(db, user)
        statement = "Led onboarding and retention programs for software customers."
        digest = evidence_hash(statement, kind="employment")
        unit = EvidenceUnit(
            user_id=user.id,
            kind="employment",
            label="Résumé experience",
            statement=statement,
            organization="Example SaaS",
            role="Customer Success Specialist",
            source_type="resume_pdf",
            source_ref="resume:post-review-drift:1",
            source_hash=digest,
            verification_status="source_backed",
            confidence=0.9,
            provenance={"document": "owner-resume.pdf", "verbatim": True},
            is_active=True,
        )
        db.add(unit)
        db.flush()
        result = dict(result)
        result["sources"] = {
            **(result.get("sources") or {}),
            "resume_pdf": 1,
        }
        return result

    monkeypatch.setattr(reviewed_materials, "rebuild_user_evidence", rebuild)


def test_evidence_change_after_material_approval_revokes_local_preflight_readiness(
    auth_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    user = _configure_user(db_session, tmp_path)
    _patch_resume_evidence(monkeypatch)
    monkeypatch.setattr(
        reviewed_materials,
        "_fetch_official_posting",
        lambda _candidate: _posting(),
    )

    prepared = auth_client.post(
        f"/api/supervised-pilot/lever-launch/{REVIEW_ID}/prepare-materials"
    )
    assert prepared.status_code == 200, prepared.text
    approved = auth_client.post(
        f"/api/supervised-pilot/lever-launch/{REVIEW_ID}/review-materials",
        json={"approved": True},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["automation_state"] == (
        ApplicationAutomationState.ready_to_apply.value
    )

    statement = "New user-confirmed achievement added after bundle approval."
    db_session.add(
        EvidenceUnit(
            user_id=user.id,
            kind="achievement",
            label="Post-review evidence",
            statement=statement,
            source_type="manual",
            source_ref="manual:post-review-drift",
            source_hash=evidence_hash(statement, kind="achievement"),
            verification_status="user_confirmed",
            confidence=1.0,
            provenance={"created_by_user": True},
            is_active=True,
        )
    )
    db_session.commit()

    launch = auth_client.get("/api/supervised-pilot/lever-launch")
    assert launch.status_code == 200, launch.text
    candidate = next(
        item
        for item in launch.json()["candidates"]
        if item["review_id"] == REVIEW_ID
    )
    assert candidate["preparation_stage"] == "review_required"
    assert candidate["material_review_eligible"] is False
    assert "material_source_snapshot_out_of_date" in candidate[
        "preparation_blockers"
    ]
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0
