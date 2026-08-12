from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MANAGER = BACKEND_ROOT / "scripts" / "manage_android_stack.sh"
ACCEPTANCE = BACKEND_ROOT / "scripts" / "android_runtime_acceptance.py"


def test_post_start_status_does_not_dispatch_health_work_to_busy_solo_worker():
    manager = MANAGER.read_text(encoding="utf-8")
    status_body = manager.split("status_stack()", 1)[1].split("prepare_stack()", 1)[0]

    assert "managed_worker_ready" in status_body
    assert "application_queue_canary.apply_async" not in status_body
    assert "worker_application_canary_probe" not in status_body
    assert "STARTUP_RECEIPT_ATTESTED" in status_body


def test_runtime_acceptance_does_not_dispatch_health_work_to_busy_solo_worker():
    acceptance = ACCEPTANCE.read_text(encoding="utf-8")

    assert "application_queue_canary" not in acceptance
    assert "apply_async(" not in acceptance
    assert "WORKER_CANARY_MAX_WAIT_SECONDS" not in acceptance
    assert "validate_worker_canary_receipt" in acceptance
