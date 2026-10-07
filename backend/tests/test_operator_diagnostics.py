from __future__ import annotations

from app.models.user import User
from app.services.operator_diagnostics import build_operator_diagnostics, render_operator_status
from tests.conftest import TestingSessionLocal


def test_operator_board_matches_owner_layout_and_grants_nothing(auth_client, monkeypatch):
    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "test@example.com").one()
    report = build_operator_diagnostics(
        db,
        user,
        onehost_probe=lambda: {"ok": True},
        worker_probe=lambda: {"ok": True},
        browser_probe=lambda: {"ok": True},
    )
    db.close()
    text = render_operator_status(report)
    assert text.startswith("JOBTOMATIK\n")
    assert "OneHost        Connected" in text
    assert "Worker         Ready" in text
    assert "Browser        Ready" in text
    assert "Database       Healthy" in text
    assert "Real Submit    OFF" in text
    assert report["grants_submit"] is False
    assert "android_native_chrome" in report["retired_controls"]
    assert "termux" not in text.lower()


def test_operator_diagnostics_endpoint_is_read_only(auth_client):
    response = auth_client.get("/api/system/operator-diagnostics")
    assert response.status_code == 200
    body = response.json()
    assert body["product"] == "JOBTOMATIK"
    assert body["safety"]["real_submit"] == "OFF"
    assert body["grants_submit"] is False
    assert "export_diagnostics_bundle" in body["recovery_controls"]
