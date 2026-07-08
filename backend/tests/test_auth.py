import pytest


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
    payload = {"email": "dup@example.com", "password": "pass123"}
    client.post("/api/auth/register", json=payload)
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"]


def test_login_success(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "p123"})
    resp = client.post("/api/auth/login", data={"username": "a@b.com", "password": "p123"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "p123"})
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
