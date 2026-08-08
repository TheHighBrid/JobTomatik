def _payload(metadata):
    return {
        "evidence_type": "dead_letter_checkpoint_recovery",
        "commit_sha": "e" * 40,
        "environment": "recovery-certification",
        "status": "passed",
        "source_reference": "drill:dead-letter:proof",
        "evidence_metadata": metadata,
    }


def test_dead_letter_certification_rejects_generic_pass_label(auth_client):
    response = auth_client.post(
        "/api/certification/evidence",
        json=_payload({"passed": True}),
    )
    assert response.status_code == 422, response.text


def test_dead_letter_certification_requires_consequential_authority_false(auth_client):
    metadata = {
        "dead_letter_verified": True,
        "checkpoint_resume_verified": True,
        "checkpoint_drift_blocked": True,
        "submission_authorized": True,
        "outreach_authorized": False,
    }
    response = auth_client.post(
        "/api/certification/evidence",
        json=_payload(metadata),
    )
    assert response.status_code == 422, response.text


def test_dead_letter_certification_accepts_complete_checkpoint_proof(auth_client):
    metadata = {
        "dead_letter_verified": True,
        "checkpoint_resume_verified": True,
        "checkpoint_drift_blocked": True,
        "submission_authorized": False,
        "outreach_authorized": False,
        "report_sha256": "9" * 64,
    }
    response = auth_client.post(
        "/api/certification/evidence",
        json=_payload(metadata),
    )
    assert response.status_code == 201, response.text
    assert response.json()["review_status"] == "unreviewed"
