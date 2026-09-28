"""Automatic Lever final-submit boundary: click once, confirm, reconcile, fail closed.

The browser is fully mocked. These tests drive the real operator-assisted approval,
once-only claim, live-checkpoint, click boundary, and reconciliation code paths.
"""

import asyncio
from types import SimpleNamespace

import pytest

import app.database as app_database
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.services import browser_handoff
from app.services import operator_assisted_auto_submit as auto_submit
from app.services import operator_assisted_final_action as final_action
from app.services import operator_assisted_handoff_integration as integration
from app.services import operator_assisted_live_pilot_hardening as hardening
from app.services.ats_base import ConfirmationEvidence
from app.tasks import operator_assisted as operator_task
from tests.conftest import TestingSessionLocal
from tests.test_operator_assisted_submission import (
    LEVER_URL,
    _create_final_submit_boundary,
    _keep_automation_off,
    _prepare_application,
    _valid_metadata,
)


THANKS_URL = LEVER_URL.rsplit("/apply", 1)[0] + "/thanks"
SAFE_OPERATIONS = SimpleNamespace(
    global_kill_switch=False,
    autopilot_enabled=False,
    disabled_platforms="",
)
SAFE_CORE = SimpleNamespace(
    allow_real_application_submit=False,
    lever_supervised_pilot_enabled=False,
)


class FakeControl:
    def __init__(self, page, *, visible=True, enabled=True):
        self.page = page
        self.visible = visible
        self.enabled = enabled

    async def is_visible(self):
        return self.visible

    async def is_enabled(self):
        return self.enabled

    async def click(self):
        self.page.clicks += 1
        if self.page.navigates_on_submit:
            self.page.url = THANKS_URL


class FakePage:
    def __init__(self, *, navigates_on_submit=True):
        self.url = LEVER_URL
        self.clicks = 0
        self.navigates_on_submit = navigates_on_submit

    async def wait_for_timeout(self, _milliseconds):
        return None


class FakeLeverAdapter:
    name = "lever"
    version = "1.1.0"

    def __init__(self, page, *, control="ok", strict_confirmation=True):
        self.page = page
        self.control_mode = control
        self.strict_confirmation = strict_confirmation

    async def resolve_surface(self, page):
        return page

    async def step_fingerprint(self, _surface):
        return f"step:{self.page.url}"

    async def find_submit_button(self, _surface):
        if self.control_mode == "missing":
            return None
        return FakeControl(
            self.page,
            visible=self.control_mode != "hidden",
            enabled=self.control_mode != "disabled",
        )

    async def extract_validation_errors(self, _surface):
        return []

    async def detect_confirmation(self, _surface, **_kwargs):
        if not self.strict_confirmation or self.page.clicks == 0:
            return []
        return [
            ConfirmationEvidence(
                evidence_type="confirmation_page",
                is_sufficient=True,
                final_url=self.page.url,
                confirmation_text="application submitted",
                selector="body",
                metadata={"confirmation_url": True},
            )
        ]


@pytest.fixture
def lever_env(auth_client, tmp_path, monkeypatch):
    """A prepared application parked at the retained Lever final-submit boundary."""

    app_id = _prepare_application(auth_client, tmp_path)
    _keep_automation_off(monkeypatch)
    handoff_public_id = _create_final_submit_boundary(app_id)

    for module in (auto_submit, operator_task, app_database):
        monkeypatch.setattr(module, "SessionLocal", TestingSessionLocal)

    async def resolved(_job):
        return _valid_metadata()

    monkeypatch.setattr(auto_submit, "resolve_supervised_target_metadata", resolved)
    monkeypatch.setattr(operator_task, "resolve_supervised_target_metadata", resolved)
    for module in (integration, final_action):
        monkeypatch.setattr(module, "get_operations_settings", lambda: SAFE_OPERATIONS)
        monkeypatch.setattr(module, "get_settings", lambda: SAFE_CORE)

    async def passive_state(_page):
        return {"hcaptcha_present": False}

    monkeypatch.setattr(hardening, "passive_verification_state", passive_state)
    monkeypatch.setattr(hardening, "passive_verification_requires_manual_browser", lambda _state: False)
    monkeypatch.setattr(auto_submit, "CONFIRMATION_RECHECK_INTERVAL_SECONDS", 0)

    env = SimpleNamespace(
        app_id=app_id,
        handoff_public_id=handoff_public_id,
        page=FakePage(),
        adapter=None,
        connects=0,
        passive_checks=0,
        passive_confirms=False,
    )
    env.adapter = FakeLeverAdapter(env.page)

    async def connect(_session):
        env.connects += 1
        return object(), None, None, env.page

    async def verify_target(_page, _session, **_kwargs):
        return {"verified": True, "blockers": []}

    async def detect(_page, _url):
        return env.adapter

    async def fingerprint(page):
        return f"page:{page.url}"

    async def disconnect(_playwright):
        return None

    async def generic_verifier(_session):
        env.passive_checks += 1
        confirmed = bool(env.passive_confirms and env.page.clicks)
        return browser_handoff.BrowserVerification(
            challenge_cleared=confirmed,
            provider="local_cdp",
            current_url=env.page.url,
            current_fingerprint=f"page:{env.page.url}",
            evidence={
                "submission_confirmed": confirmed,
                "confirmation_url_signal": confirmed and env.page.url.endswith("/thanks"),
                "confirmation_evidence": (
                    [{
                        "evidence_type": "confirmation_page",
                        "is_sufficient": True,
                        "final_url": env.page.url,
                        "confirmation_text": "application submitted",
                        "selector": "body",
                        "metadata": {"verification_method": "explicit_confirmation_text"},
                    }]
                    if confirmed
                    else []
                ),
                "target_verification": {"verified": True, "blockers": []},
                "verification_method": "explicit_submission_confirmation" if confirmed else "browser_state",
            },
        )

    monkeypatch.setattr(browser_handoff, "_connect_local_cdp", connect)
    monkeypatch.setattr(browser_handoff, "_verify_session_target", verify_target)
    monkeypatch.setattr(browser_handoff, "_require_verified_session_target", lambda _value: None)
    monkeypatch.setattr(browser_handoff, "detect_ats_adapter", detect)
    monkeypatch.setattr(browser_handoff, "page_fingerprint", fingerprint)
    monkeypatch.setattr(
        browser_handoff,
        "_session_supervised_target",
        lambda _session: {"adapter": "lever", "adapter_version": "1.1.0"},
    )
    monkeypatch.setattr(browser_handoff, "_disconnect", disconnect)
    monkeypatch.setattr(integration, "_ORIGINAL_VERIFY_COMPLETION", generic_verifier)
    return env


def _run(env):
    return asyncio.run(
        auto_submit.submit_retained_lever_final_action(env.app_id, env.handoff_public_id)
    )


def _run_prepare_task(env, monkeypatch):
    """Drive the Celery task with the already-filled retained page result mocked."""

    fill_result = {
        "success": False,
        "dry_run": True,
        "requires_manual_review": True,
        "handoff_public_id": env.handoff_public_id,
        "application_url": LEVER_URL,
        "review_items": [
            {"reason_code": ManualReviewReason.operator_final_submit_required.value}
        ],
    }
    fills = []

    def fake_fill(application_id, dry_run=True):
        fills.append((application_id, dry_run))
        return dict(fill_result)

    monkeypatch.setattr(operator_task, "submit_application_task", SimpleNamespace(run=fake_fill))
    result = operator_task.prepare_operator_assisted_application_task.run(env.app_id)
    assert fills == [(env.app_id, True)]
    return result


def _application(db, env):
    return db.query(Application).filter(Application.id == env.app_id).one()


def _approvals(db, env):
    return db.query(SubmissionApproval).filter(SubmissionApproval.application_id == env.app_id).all()


def _state(value):
    return getattr(value, "value", value)


def test_confirmed_submit_clicks_once_and_marks_applied_confirmed(lever_env, monkeypatch):
    result = _run_prepare_task(lever_env, monkeypatch)

    assert lever_env.page.clicks == 1, result.get("error")
    assert result["success"] is True
    assert result["submission_confirmed"] is True
    assert result["final_submit_clicked_by_jobtomatik"] is True
    assert result["automatic_retry_allowed"] is False
    assert result["application_status"] == ApplicationStatus.applied.value
    assert result["automation_state"] == ApplicationAutomationState.confirmed.value
    assert result["confirmation_detector"] == "lever_adapter_strict"

    db = TestingSessionLocal()
    try:
        application = _application(db, lever_env)
        assert _state(application.status) == ApplicationStatus.applied.value
        assert _state(application.automation_state) == ApplicationAutomationState.confirmed.value
        assert application.applied_at is not None
        evidence = db.query(SubmissionEvidence).filter(
            SubmissionEvidence.application_id == lever_env.app_id
        ).all()
        assert any(item.is_sufficient and item.final_url == THANKS_URL for item in evidence)
        assert any(item.confirmation_text == "application submitted" for item in evidence)
        session = db.query(ManualHandoffSession).filter(
            ManualHandoffSession.public_id == lever_env.handoff_public_id
        ).one()
        assert session.status == HandoffSessionStatus.completed.value
        [approval] = _approvals(db, lever_env)
        metadata = dict(approval.approval_metadata or {})
        assert approval.status == SubmissionApprovalStatus.consumed.value
        assert metadata["operator_submit_action_result"] == "confirmed"
        assert metadata["operator_submit_live_snapshot_checkpointed"] is True
        assert metadata["operator_submit_current_url"] == THANKS_URL
    finally:
        db.close()

    # A second run for the same (now closed) application never clicks again.
    again = _run(lever_env)
    assert again["final_submit_clicked_by_jobtomatik"] is False
    assert again["idempotency_guard"] == "application_already_submitted"
    assert lever_env.page.clicks == 1


def test_slow_lever_redirect_is_confirmed_by_read_only_recheck(lever_env, monkeypatch):
    lever_env.adapter.strict_confirmation = False
    lever_env.passive_confirms = True

    result = _run_prepare_task(lever_env, monkeypatch)

    assert lever_env.page.clicks == 1
    assert lever_env.passive_checks >= 1
    assert result["success"] is True
    assert result["confirmation_detector"] == auto_submit.PASSIVE_CONFIRMATION_DETECTOR
    db = TestingSessionLocal()
    try:
        application = _application(db, lever_env)
        assert _state(application.status) == ApplicationStatus.applied.value
        assert _state(application.automation_state) == ApplicationAutomationState.confirmed.value
    finally:
        db.close()


def test_unconfirmed_submit_is_not_marked_applied_and_records_evidence(lever_env, monkeypatch):
    lever_env.page.navigates_on_submit = False
    lever_env.adapter.strict_confirmation = False

    result = _run_prepare_task(lever_env, monkeypatch)

    assert lever_env.page.clicks == 1
    assert lever_env.passive_checks == auto_submit.CONFIRMATION_RECHECK_ATTEMPTS
    assert result["success"] is False
    assert result["submission_confirmed"] is False
    assert result["requires_manual_review"] is True
    assert result["automation_state"] == ApplicationAutomationState.submission_uncertain.value

    db = TestingSessionLocal()
    try:
        application = _application(db, lever_env)
        assert _state(application.status) != ApplicationStatus.applied.value
        assert application.applied_at is None
        assert _state(application.automation_state) == ApplicationAutomationState.submission_uncertain.value
        assert not db.query(SubmissionEvidence).filter(
            SubmissionEvidence.application_id == lever_env.app_id,
            SubmissionEvidence.is_sufficient.is_(True),
        ).first()
        review = db.query(ManualReviewTask).filter(
            ManualReviewTask.application_id == lever_env.app_id,
            ManualReviewTask.reason_code == ManualReviewReason.submission_confirmation_uncertain.value,
            ManualReviewTask.status == ManualReviewStatus.open.value,
        ).one()
        assert review.details["final_submit_click_possible"] is True
        assert review.details["final_url"] == LEVER_URL
        assert review.details["observed_at"]
        assert review.details["automatic_retry_allowed"] is False
        [approval] = _approvals(db, lever_env)
        metadata = dict(approval.approval_metadata or {})
        assert metadata["operator_submit_action_result"] == "awaiting_confirmation"
        assert metadata["operator_submit_confirmation_observed"] is False
    finally:
        db.close()

    # Re-running must never click the employer Submit control a second time.
    again = _run(lever_env)
    assert again["final_submit_clicked_by_jobtomatik"] is False
    assert again["idempotency_guard"] == "previous_submission_outcome_uncertain"
    assert lever_env.page.clicks == 1


@pytest.mark.parametrize("control_mode", ["missing", "disabled", "hidden"])
def test_missing_or_unusable_submit_control_fails_closed_without_click(
    lever_env,
    monkeypatch,
    control_mode,
):
    lever_env.adapter.control_mode = control_mode

    result = _run_prepare_task(lever_env, monkeypatch)

    assert lever_env.page.clicks == 0
    assert lever_env.passive_checks == 0
    assert result["success"] is False
    assert result["final_submit_clicked_by_jobtomatik"] is False
    assert result["final_submit_click_possible"] is False
    assert result["automation_state"] == ApplicationAutomationState.needs_review.value

    db = TestingSessionLocal()
    try:
        application = _application(db, lever_env)
        assert _state(application.status) != ApplicationStatus.applied.value
        assert _state(application.automation_state) == ApplicationAutomationState.needs_review.value
        review = db.query(ManualReviewTask).filter(
            ManualReviewTask.application_id == lever_env.app_id,
            ManualReviewTask.status.in_([
                ManualReviewStatus.open.value,
                ManualReviewStatus.in_progress.value,
            ]),
        ).one()
        assert review.reason_code == ManualReviewReason.operator_final_submit_required.value
        assert review.details["automatic_final_submit"]["final_submit_click_possible"] is False
        assert review.details["handoff_stage"] == "operator_final_submit"
        [approval] = _approvals(db, lever_env)
        metadata = dict(approval.approval_metadata or {})
        assert metadata["operator_submit_live_snapshot_checkpointed"] is False
        assert metadata["operator_submit_action_result"] == "uncertain"
    finally:
        db.close()


@pytest.mark.parametrize(
    ("operations", "core"),
    [
        (SimpleNamespace(global_kill_switch=True, autopilot_enabled=False, disabled_platforms=""), SAFE_CORE),
        (SimpleNamespace(global_kill_switch=False, autopilot_enabled=False, disabled_platforms="lever"), SAFE_CORE),
        (SimpleNamespace(global_kill_switch=False, autopilot_enabled=True, disabled_platforms=""), SAFE_CORE),
        (SAFE_OPERATIONS, SimpleNamespace(allow_real_application_submit=True, lever_supervised_pilot_enabled=False)),
        (SAFE_OPERATIONS, SimpleNamespace(allow_real_application_submit=False, lever_supervised_pilot_enabled=True)),
    ],
    ids=["kill_switch", "platform_disabled", "autopilot", "global_live_submit", "lever_pilot"],
)
def test_runtime_gates_block_before_any_click_or_browser_connection(
    lever_env,
    monkeypatch,
    operations,
    core,
):
    for module in (integration, final_action):
        monkeypatch.setattr(module, "get_operations_settings", lambda: operations)
        monkeypatch.setattr(module, "get_settings", lambda: core)

    result = _run(lever_env)

    assert lever_env.page.clicks == 0
    assert lever_env.connects == 0
    assert result["success"] is False
    assert result["final_submit_clicked_by_jobtomatik"] is False
    db = TestingSessionLocal()
    try:
        application = _application(db, lever_env)
        assert _state(application.automation_state) == ApplicationAutomationState.needs_review.value
        assert _state(application.status) != ApplicationStatus.applied.value
        assert not [
            approval
            for approval in _approvals(db, lever_env)
            if approval.status == SubmissionApprovalStatus.consumed.value
        ]
    finally:
        db.close()


def test_preflight_gate_blocks_before_click(lever_env, monkeypatch):
    from app.services import supervised_submission as approval_service

    monkeypatch.setattr(approval_service.settings, "allow_real_application_submit", True)

    result = _run(lever_env)

    assert lever_env.page.clicks == 0
    assert lever_env.connects == 0
    assert "preflight blocked" in result["error"].lower()
    assert "operator_assisted_requires_global_submit_disabled" in result["error"]


def test_already_applied_application_is_never_clicked(lever_env):
    db = TestingSessionLocal()
    application = _application(db, lever_env)
    application.status = ApplicationStatus.applied
    db.commit()
    db.close()

    result = _run(lever_env)

    assert lever_env.page.clicks == 0
    assert lever_env.connects == 0
    assert result["idempotency_guard"] == "application_already_submitted"
    assert result["final_submit_clicked_by_jobtomatik"] is False


def test_prior_checkpointed_final_action_blocks_a_second_automatic_click(lever_env):
    db = TestingSessionLocal()
    application = _application(db, lever_env)
    approval = SubmissionApproval(
        application_id=application.id,
        user_id=application.user_id,
        platform="lever",
        status=SubmissionApprovalStatus.consumed.value,
        employer="SafeCo",
        role="Payments Risk Analyst",
        application_url=LEVER_URL,
        submission_idempotency_key="prior-attempt",
        profile_snapshot_hash="p" * 64,
        resume_hash="r" * 64,
        cover_letter_hash="l" * 64,
        answer_payload_hash="a" * 64,
        combined_payload_hash="c" * 64,
        approved_at=application.created_at,
        expires_at=application.created_at,
        approval_metadata={
            "approval_source": "authenticated_user_operator_assisted",
            "handoff_public_id": "an-earlier-retained-handoff",
            "operator_submit_action_started_at": "2026-09-28T00:00:00",
            "operator_submit_live_snapshot_checkpointed": True,
            "operator_submit_action_result": "uncertain",
        },
    )
    db.add(approval)
    db.commit()
    db.close()

    result = _run(lever_env)

    assert lever_env.page.clicks == 0
    assert lever_env.connects == 0
    assert result["idempotency_guard"] == "final_submit_already_attempted"
