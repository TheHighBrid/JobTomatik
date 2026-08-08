def _token(client, email: str) -> str:
    register = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "testpass123",
            "full_name": email.split("@")[0],
        },
    )
    assert register.status_code == 201, register.text
    login = client.post(
        "/api/auth/login",
        data={"username": email, "password": "testpass123"},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def test_same_external_evidence_identity_does_not_collide_across_accounts(client):
    first_token = _token(client, "cert-owner-one@example.test")
    second_token = _token(client, "cert-owner-two@example.test")
    payload = {
        "evidence_type": "duplicate_prevention",
        "commit_sha": "a" * 40,
        "environment": "production-like",
        "status": "passed",
        "source_reference": "workflow:shared-external-identity",
        "evidence_metadata": {"report_sha256": "1" * 64},
    }

    first = client.post(
        "/api/certification/evidence",
        json=payload,
        headers={"Authorization": f"Bearer {first_token}"},
    )
    second = client.post(
        "/api/certification/evidence",
        json=payload,
        headers={"Authorization": f"Bearer {second_token}"},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["evidence_key"] != second.json()["evidence_key"]
    assert first.json()["payload_hash"] == second.json()["payload_hash"]
