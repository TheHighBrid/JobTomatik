from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.application import Application, ManualReviewReason, ManualReviewTask
from app.models.handoff import HandoffSessionStatus
from app.models.job import Job
from app.models.user import User
from app.services import browser_handoff, form_filler, operational_safety
from app.services.handoff_session import (
    HandoffSessionExpired,
    claim_handoff_session,
    issue_handoff_session,
)
from app.services.operational_safety import (
    build_handoff_target_binding,
    classify_handoff_reason,
    evaluate_execution_safety,
    operational_safety_manifest,
    OperationalSafetyViolation,
    rebind_resolved_handoff_target,
    validate_handoff_target_binding,
)
from app.services.operations_policy import evaluate_circuit_breaker_policy
from app.services.operations_settings import get_operations_settings


GREENHOUSE_URL = "https://job-boards.greenhouse.io/safeco/jobs/123456"
LEVER_URL = "https://jobs.lever.co/safeco/abc-def"
ASHBY_URL = "https://jobs.ashbyhq.com/safeco/ashby-123"
WORKDAY_URL = "https://safeco.wd5.myworkdayjobs.com/en-US/jobs/job/Ottawa/R-123"


def _reset_operations_settings():
    get_operations_settings.cache_clear()


def _core(monkeypatch, *, real_submit=False, resumable_handoffs=False):
    monkeypatch.setattr(
        operational_safety,
        "get_settings",
        lambda: SimpleNamespace(
            allow_real_application_submit=real_submit,
            enable_resumable_handoffs=resumable_handoffs,
        ),
    )


def _records(db_session, *, suffix="base", url=GREENHOUSE_URL, reason=None):
    user = User(
        email=f"day06-{suffix}@example.test",
        hashed_password="test-hash",
        automation_settings={},
    )
    job = Job(
        external_id=f"day06-{suffix}",
        title=f"Fraud Analyst {suffix}",
        company="SafeCo",
        url=url,
        raw_data={"selected_apply_url": url},
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        application_target_url=url,
        submission_idempotency_key=f"day06:{suffix}",
    )
    db_session.add(application)
    db_session.flush()
    review = ManualReviewTask(
        application_id=application.id,
        reason_code=(reason or ManualReviewReason.captcha_detected).value,
        summary="Day 6 synthetic boundary",
    )
    db_session.add(review)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(job)
    db_session.refresh(application)
    db_session.refresh(review)
    return user, job, application, review


def _failure(db_session, user, *, suffix, url, reason, created_at):
    job = Job(
        external_id=f"failure-{suffix}",
        title=f"Failure role {suffix}",
        company="FailureCo",
        url=url,
        raw_data={"selected_apply_url": url},
    )
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        application_target_url=url,
        submission_idempotency_key=f"failure:{suffix}",
    )
    db_session.add(application)
    db_session.flush()
    db_session.add(ManualReviewTask(
        application_id=application.id,
        reason_code=reason.value,
        summary="Synthetic clustered operational failure",
        created_at=created_at,
    ))
    db_session.commit()


def test_global_kill_switch_blocks_platform_and_execution(db_session, monkeypatch):
    monkeypatch.setenv("AUTOMATION_GLOBAL_KILL_SWITCH", "true")
    monkeypatch.setenv("AUTOPILOT_DISABLED_PLATFORMS", "")
    _reset_operations_settings()
    _core(monkeypatch, real_submit=True, resumable_handoffs=True)
    user, _job, _application, _review = _records(db_session, suffix="global-stop")

    decision = evaluate_execution_safety(
        db_session,
        user,
        url=GREENHOUSE_URL,
        dry_run=True,
        requires_handoff=False,
    )

    assert decision.allowed is False
    assert decision.code == "global_kill_switch_active"
    assert decision.metadata["operator_reason_code"] == "emergency_stop"


def test_autopilot_platform_real_submit_and_handoff_switches(db_session, monkeypatch):
    monkeypatch.setenv("AUTOMATION_GLOBAL_KILL_SWITCH", "false")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("AUTOPILOT_DISABLED_PLATFORMS", "")
    _reset_operations_settings()
    user, _job, _application, _review = _records(db_session, suffix="switches")

    _core(monkeypatch, real_submit=True, resumable_handoffs=True)
    autopilot = evaluate_execution_safety(
        db_session,
        user,
        url=GREENHOUSE_URL,
        dry_run=True,
        autopilot=True,
    )
    assert autopilot.code == "global_autopilot_disabled"

    monkeypatch.setenv("AUTOPILOT_DISABLED_PLATFORMS", "greenhouse")
    _reset_operations_settings()
    platform = evaluate_execution_safety(
        db_session,
        user,
        url=GREENHOUSE_URL,
        dry_run=True,
    )
    assert platform.code == "platform_disabled"

    monkeypatch.setenv("AUTOPILOT_DISABLED_PLATFORMS", "")
    _reset_operations_settings()
    _core(monkeypatch, real_submit=False, resumable_handoffs=True)
    live = evaluate_execution_safety(
        db_session,
        user,
        url=GREENHOUSE_URL,
        dry_run=False,
    )
    assert live.code == "real_submission_disabled"

    _core(monkeypatch, real_submit=True, resumable_handoffs=False)
    handoff = evaluate_execution_safety(
        db_session,
        user,
        url=GREENHOUSE_URL,
        dry_run=False,
        requires_handoff=True,
    )
    assert handoff.code == "resumable_handoffs_disabled"

    dry_run = evaluate_execution_safety(
        db_session,
        user,
        url=GREENHOUSE_URL,
        dry_run=True,
        requires_handoff=True,
    )
    assert dry_run.allowed is True


def test_manual_review_reason_matrix_is_typed_and_fail_closed():
    for reason in (
        ManualReviewReason.captcha_detected,
        ManualReviewReason.mfa_required,
        ManualReviewReason.login_required,
        ManualReviewReason.anti_bot_challenge,
        ManualReviewReason.application_target_required,
    ):
        policy = classify_handoff_reason(reason)
        assert policy.resumable is True
        assert policy.disposition == "resumable_browser"

    for reason in (
        ManualReviewReason.assessment_required,
        ManualReviewReason.legal_answer_missing,
        ManualReviewReason.sensitive_answer_missing,
        ManualReviewReason.ambiguous_question,
        ManualReviewReason.unsupported_control,
    ):
        policy = classify_handoff_reason(reason)
        assert policy.resumable is False
        assert policy.disposition == "manual_only"

    uncertain = classify_handoff_reason(
        ManualReviewReason.submission_confirmation_uncertain
    )
    assert uncertain.resumable is False
    assert uncertain.disposition == "evidence_review"

    manifest = operational_safety_manifest()
    assert manifest["invariants"]["ambiguous_controls_are_never_guessed"] is True
    assert manifest["invariants"]["uncertain_confirmation_requires_evidence_review"] is True


def test_handoff_binding_rejects_wrong_posting_and_wrong_records(db_session):
    _user, job, application, review = _records(db_session, suffix="binding")
    binding = build_handoff_target_binding(
        application,
        job,
        review,
        current_url=GREENHOUSE_URL,
        current_fingerprint="initial-dom",
    )
    session = SimpleNamespace(
        handoff_metadata={"target_binding": binding},
        current_url=GREENHOUSE_URL,
    )

    same = validate_handoff_target_binding(
        session,
        application,
        job,
        review,
        current_url=GREENHOUSE_URL + "?utm_source=test",
    )
    assert same.allowed is True

    wrong_posting = validate_handoff_target_binding(
        session,
        application,
        job,
        review,
        current_url="https://job-boards.greenhouse.io/safeco/jobs/999999",
    )
    assert wrong_posting.allowed is False
    assert wrong_posting.code == "handoff_posting_mismatch"
    assert wrong_posting.metadata["operator_reason_code"] == "wrong_posting_resume"

    _other_user, other_job, other_app, other_review = _records(
        db_session,
        suffix="other-binding",
        url=LEVER_URL,
    )
    wrong_records = validate_handoff_target_binding(
        session,
        other_app,
        other_job,
        other_review,
        current_url=LEVER_URL,
    )
    assert wrong_records.allowed is False
    assert wrong_records.code == "handoff_record_identity_mismatch"


def test_expired_handoff_cannot_be_claimed_or_resumed(db_session, monkeypatch):
    monkeypatch.setenv("AUTOMATION_GLOBAL_KILL_SWITCH", "false")
    monkeypatch.setenv("AUTOPILOT_DISABLED_PLATFORMS", "")
    _reset_operations_settings()
    _user, _job, application, review = _records(db_session, suffix="expired")

    issued = issue_handoff_session(
        db_session,
        application,
        review,
        browser_provider="retained-local",
        current_url=GREENHOUSE_URL,
        current_fingerprint="challenge-dom",
        metadata={"dry_run": True},
        ttl_minutes=1,
    )
    issued.session.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()

    with pytest.raises(HandoffSessionExpired):
        claim_handoff_session(
            db_session,
            issued.session,
            user_id=application.user_id,
            resume_token=issued.resume_token,
        )
    assert issued.session.status == HandoffSessionStatus.expired.value


def test_platform_breaker_isolates_unrelated_adapter(db_session, monkeypatch):
    monkeypatch.setenv("AUTOMATION_GLOBAL_KILL_SWITCH", "false")
    monkeypatch.setenv("AUTOPILOT_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("AUTOPILOT_FAILURE_WINDOW_MINUTES", "60")
    monkeypatch.setenv("AUTOPILOT_CIRCUIT_BREAKER_MINUTES", "120")
    _reset_operations_settings()
    user, _job, _application, _review = _records(db_session, suffix="platform-breaker")
    now = datetime.utcnow().replace(microsecond=0)
    for index, minutes in enumerate((30, 20, 10), start=1):
        _failure(
            db_session,
            user,
            suffix=f"greenhouse-{index}",
            url=GREENHOUSE_URL.replace("123456", str(123456 + index)),
            reason=ManualReviewReason.automation_error,
            created_at=now - timedelta(minutes=minutes),
        )

    greenhouse = evaluate_circuit_breaker_policy(
        db_session,
        user.id,
        url=GREENHOUSE_URL,
        now=now,
    )
    assert greenhouse.allowed is False
    assert greenhouse.code == "platform_circuit_breaker_open"
    assert greenhouse.metadata["platform"] == "greenhouse"

    lever = evaluate_circuit_breaker_policy(
        db_session,
        user.id,
        url=LEVER_URL,
        now=now,
    )
    assert lever.allowed is True
    assert lever.metadata["isolated_cluster"]["platform_counts"] == {"greenhouse": 3}


def test_cross_platform_failure_cluster_opens_user_breaker(db_session, monkeypatch):
    monkeypatch.setenv("AUTOMATION_GLOBAL_KILL_SWITCH", "false")
    monkeypatch.setenv("AUTOPILOT_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("AUTOPILOT_FAILURE_WINDOW_MINUTES", "60")
    monkeypatch.setenv("AUTOPILOT_CIRCUIT_BREAKER_MINUTES", "120")
    _reset_operations_settings()
    user, _job, _application, _review = _records(db_session, suffix="global-breaker")
    now = datetime.utcnow().replace(microsecond=0)
    for suffix, url, reason, minutes in (
        ("greenhouse", GREENHOUSE_URL, ManualReviewReason.automation_error, 30),
        ("lever", LEVER_URL, ManualReviewReason.validation_error, 20),
        ("ashby", ASHBY_URL, ManualReviewReason.step_navigation_failed, 10),
    ):
        _failure(
            db_session,
            user,
            suffix=suffix,
            url=url,
            reason=reason,
            created_at=now - timedelta(minutes=minutes),
        )

    decision = evaluate_circuit_breaker_policy(
        db_session,
        user.id,
        url=WORKDAY_URL,
        now=now,
    )
    assert decision.allowed is False
    assert decision.code == "circuit_breaker_open"
    assert set(decision.metadata["platform_counts"]) == {"greenhouse", "lever", "ashby"}
    assert decision.metadata["operator_reason_code"] == "user_failure_cluster"

@pytest.mark.asyncio
async def test_global_kill_switch_blocks_all_shared_browser_entry_points(monkeypatch):
    monkeypatch.setenv("AUTOMATION_GLOBAL_KILL_SWITCH", "true")
    monkeypatch.setenv("AUTOPILOT_DISABLED_PLATFORMS", "")
    _reset_operations_settings()
    called = {"value": False}

    async def unexpected_browser(*args, **kwargs):
        called["value"] = True
        return {"success": True}

    monkeypatch.setattr(form_filler, "fill_and_submit_application_with_handoff", unexpected_browser)
    with pytest.raises(OperationalSafetyViolation) as direct:
        await form_filler.fill_and_submit_application(job_url=GREENHOUSE_URL, dry_run=True)
    assert direct.value.code == "global_kill_switch_active"
    assert called["value"] is False

    retained = SimpleNamespace(current_url=GREENHOUSE_URL, handoff_metadata={})
    with pytest.raises(browser_handoff.BrowserHandoffUnavailable, match="global_kill_switch_active"):
        await browser_handoff._connect_local_cdp(retained)


@pytest.mark.parametrize(
    ("first_url", "second_url"),
    [
        ("https://boards.greenhouse.io/safeco?gh_jid=123456", "https://boards.greenhouse.io/safeco?gh_jid=999999"),
        ("https://boards.greenhouse.io/embed/job_app?token=alpha-token", "https://boards.greenhouse.io/embed/job_app?token=beta-token"),
    ],
)
def test_greenhouse_query_posting_ids_are_part_of_handoff_identity(db_session, first_url, second_url):
    _user, job, application, review = _records(db_session, suffix="greenhouse-query-binding", url=first_url)
    binding = build_handoff_target_binding(application, job, review, current_url=first_url)
    session = SimpleNamespace(handoff_metadata={"target_binding": binding}, current_url=first_url)
    assert validate_handoff_target_binding(
        session, application, job, review, current_url=first_url + "&utm_source=certification"
    ).allowed is True
    mismatch = validate_handoff_target_binding(
        session, application, job, review, current_url=second_url
    )
    assert mismatch.allowed is False
    assert mismatch.code == "handoff_posting_mismatch"


def test_resolved_listing_target_is_rebound_and_rechecked_before_resume(db_session, monkeypatch):
    listing_url = "https://www.jobbank.gc.ca/jobsearch/jobposting/12345678"
    user, job, application, review = _records(
        db_session,
        suffix="resolved-target-rebind",
        url=listing_url,
        reason=ManualReviewReason.application_target_required,
    )
    binding = build_handoff_target_binding(
        application, job, review, current_url=listing_url, target_resolution_only=True
    )
    session = SimpleNamespace(
        current_url=listing_url,
        current_fingerprint="listing-dom",
        handoff_metadata={
            "dry_run": True,
            "source_listing_url": listing_url,
            "target_resolution_only": True,
            "stage": "application_target_resolution",
            "target_binding": binding,
        },
    )
    monkeypatch.setenv("AUTOMATION_GLOBAL_KILL_SWITCH", "false")
    monkeypatch.setenv("AUTOPILOT_DISABLED_PLATFORMS", "lever")
    _reset_operations_settings()
    with pytest.raises(OperationalSafetyViolation) as disabled:
        rebind_resolved_handoff_target(
            db_session, session, application, job, review, user,
            resolved_url=LEVER_URL, current_fingerprint="lever-dom",
        )
    assert disabled.value.code == "platform_disabled"
    assert session.handoff_metadata["target_binding"]["target_resolution_only"] is True

    monkeypatch.setenv("AUTOPILOT_DISABLED_PLATFORMS", "")
    _reset_operations_settings()
    rebound = rebind_resolved_handoff_target(
        db_session, session, application, job, review, user,
        resolved_url=LEVER_URL, current_fingerprint="lever-dom",
    )
    assert rebound.allowed is True
    assert session.handoff_metadata["target_resolution_only"] is False
    assert session.handoff_metadata["target_binding"]["platform"] == "lever"
    wrong = validate_handoff_target_binding(
        session, application, job, review,
        current_url="https://jobs.lever.co/safeco/different-posting",
    )
    assert wrong.allowed is False
    assert wrong.code == "handoff_posting_mismatch"
