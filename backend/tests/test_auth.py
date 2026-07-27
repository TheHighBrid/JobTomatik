def test_register_success(client):
    resp = client.post("/api/auth/register", json={
        "email": "user@example.com",
        "password": "password123",
        "full_name": "Jane Smith",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "user@example.com"
    assert data["user"]["full_name"] == "Jane Smith"


def test_register_duplicate_email(client):
    payload = {"email": "dup@example.com", "password": "pass12345"}
    client.post("/api/auth/register", json=payload)
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"]


def test_email_identity_is_case_insensitive(client):
    password = "pass12345"
    created = client.post("/api/auth/register", json={
        "email": "Person@Example.COM",
        "password": password,
    })
    duplicate = client.post("/api/auth/register", json={
        "email": "person@example.com",
        "password": password,
    })
    login = client.post("/api/auth/login", data={
        "username": "PERSON@example.com",
        "password": password,
    })

    assert created.status_code == 201
    assert created.json()["user"]["email"] == "person@example.com"
    assert duplicate.status_code == 400
    assert login.status_code == 200


def test_register_rejects_short_password(client):
    resp = client.post("/api/auth/register", json={
        "email": "short@example.com",
        "password": "p123",
    })

    assert resp.status_code == 422
    assert "at least 8 characters" in str(resp.json())


def test_login_success(client):
    password = "p12345678"
    client.post("/api/auth/register", json={"email": "a@b.com", "password": password})
    resp = client.post("/api/auth/login", data={"username": "a@b.com", "password": password})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "p12345678"})
    resp = client.post("/api/auth/login", data={"username": "a@b.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_nonexistent_user(client):
    resp = client.post("/api/auth/login", data={"username": "no@one.com", "password": "x"})
    assert resp.status_code == 401


def test_profile_requires_auth(client):
    resp = client.get("/api/profile")
    assert resp.status_code == 401


def test_profile_authenticated(auth_client):
    resp = auth_client.get("/api/profile")
    assert resp.status_code == 200
    assert resp.json()["email"] == "test@example.com"
