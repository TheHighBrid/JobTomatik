import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.database import Base, get_db

# In-memory SQLite for tests
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def mock_celery(monkeypatch):
    """Stub API-triggered Celery calls so tests do not need Redis."""
    fake_result = MagicMock(id="test-task-id")
    mock_task = MagicMock()
    mock_task.delay.return_value = fake_result
    mock_task.apply_async.return_value = fake_result

    monkeypatch.setattr("app.api.applications.generate_cover_letter_task", mock_task)
    monkeypatch.setattr("app.api.applications.submit_application_task", mock_task)
    monkeypatch.setattr("app.api.jobs.run_job_search", mock_task)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_client(client):
    """Returns a TestClient with a registered and logged-in user."""
    client.post("/api/auth/register", json={
        "email": "test@example.com",
        "password": "testpass123",
        "full_name": "Test User",
    })
    resp = client.post(
        "/api/auth/login",
        data={"username": "test@example.com", "password": "testpass123"},
    )
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
