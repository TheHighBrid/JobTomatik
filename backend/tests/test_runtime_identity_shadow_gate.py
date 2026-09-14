from __future__ import annotations


from app.api import shadow_runs as shadow_api
from app.models.certification import ShadowRunSession
from app.services.operations_settings import get_operations_settings
from app.tasks import shadow_runs as shadow_tasks


REVISION = "c" * 40


def _clear_identity(monkeypatch):
    for name in (
        "JOBTOMATIK_RUNTIME_REVISION",
        "JOBTOMATIK_EXPECTED_REVISION",
        "JOBTOMATIK_RUNTIME_ROLE",
        "JOBTOMATIK_OPERATIONS_ENV_FILE",
        "GITHUB_SHA",
        "AUTOPILOT_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    get_operations_settings.cache_clear()


def _base_preflight(target="shadow_run_4h"):
    return {
        "ok": True,
        "checks": {},
        "blockers": [],
        "candidate_revision": REVISION,
        "target_evidence_type": target,
        "requested_duration_seconds": 4 * 60 * 60,
        "expected_start_acknowledgment": (
            f"START FULL STACK SHADOW {target} {REVISION[:12]}"
        ),
        "scheduler": {
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "dry_run_mode": True,
        },
        "operations": {
            "autopilot_enabled": True,
            "global_kill_switch": False,
            "disabled_platforms": [],
        },
        "runtime": {
            "allow_real_application_submit": False,
            "allow_real_followup_send": False,
        },
        "invariants": {
            "final_submit_allowed": False,
            "runtime_settings_mutated": False,
            "outreach_authorized": False,
            "adapter_maturity_mutated": False,
        },
    }


def test_shadow_preflight_surfaces_runtime_identity_blocker(auth_client, monkeypatch):
    _clear_identity(monkeypatch)
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setattr(
        shadow_api,
        "full_stack_shadow_preflight",
        lambda db, user, target_evidence_type="shadow_run_4h": _base_preflight(
            target_evidence_type
        ),
    )

    response = auth_client.get("/api/shadow-runs/preflight")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "runtime_identity_unattested" in payload["blockers"]
    assert payload["checks"]["runtime_identity_attested"] is False
    assert payload["expected_start_acknowledgment"] is None
    assert payload["runtime_identity"]["deployment_attested"] is False
    assert payload["runtime_identity"]["submission_authorized"] is False


def test_shadow_start_is_blocked_before_session_creation_when_unattested(
    auth_client,
    db_session,
    monkeypatch,
):
    _clear_identity(monkeypatch)
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")

    response = auth_client.post(
        "/api/shadow-runs",
        json={
            "target_evidence_type": "shadow_run_4h",
            "cycle_interval_seconds": 60,
            "acknowledgment": f"START FULL STACK SHADOW shadow_run_4h {REVISION[:12]}",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "runtime_identity_unattested"
    assert db_session.query(ShadowRunSession).count() == 0


def test_shadow_identity_gate_accepts_matching_exact_revision(monkeypatch):
    _clear_identity(monkeypatch)
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "api")

    gate = shadow_api._runtime_identity_gate()

    assert gate["required"] is True
    assert gate["ok"] is True
    assert gate["identity"]["revision"] == REVISION
    assert gate["identity"]["role"] == "api"


def test_shadow_api_and_worker_share_operations_env_file_autopilot_gate(tmp_path, monkeypatch):
    _clear_identity(monkeypatch)
    env_file = tmp_path / "jobtomatik.env"
    env_file.write_text("AUTOPILOT_ENABLED=true\n", encoding="utf-8")
    monkeypatch.setenv("JOBTOMATIK_OPERATIONS_ENV_FILE", str(env_file))
    get_operations_settings.cache_clear()

    api_gate = shadow_api._runtime_identity_gate()
    worker_ok, worker_identity = shadow_tasks._identity_allows_shadow_execution()

    assert api_gate["required"] is True
    assert api_gate["ok"] is False
    assert api_gate["identity"]["deployment_attested"] is False
    assert worker_ok is False
    assert worker_identity["deployment_attested"] is False


def test_shadow_worker_refuses_direct_unattested_execution(monkeypatch):
    _clear_identity(monkeypatch)
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setattr(
        shadow_tasks,
        "execute_shadow_cycle",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("execute_shadow_cycle must not run")
        ),
    )
    monkeypatch.setattr(
        shadow_tasks,
        "_fail_session_for_identity",
        lambda session_id, identity: {
            "session_id": session_id,
            "status": "failed",
            "error": "runtime_identity_unattested",
            "runtime_revision": identity.get("revision"),
            "schedule_next": False,
            "submission_authorized": False,
            "outreach_authorized": False,
        },
    )

    result = shadow_tasks.run_shadow_session_cycle(77)

    assert result["status"] == "failed"
    assert result["error"] == "runtime_identity_unattested"
    assert result["schedule_next"] is False
    assert result["submission_authorized"] is False
    assert result["outreach_authorized"] is False


def test_shadow_worker_accepts_matching_attestation(monkeypatch):
    _clear_identity(monkeypatch)
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")

    ok, identity = shadow_tasks._identity_allows_shadow_execution()

    assert ok is True
    assert identity["deployment_attested"] is True
    assert identity["role"] == "worker"
