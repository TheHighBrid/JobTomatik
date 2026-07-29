from __future__ import annotations

from pathlib import Path


def require_text(path: str, marker: str) -> str:
    text = Path(path).read_text(encoding="utf-8")
    if marker not in text:
        raise SystemExit(f"Prerequisite marker missing in {path}: {marker!r}")
    return text


def append_once(path: str, marker: str, addition: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if marker not in text:
        target.write_text(text.rstrip() + "\n\n" + addition.strip() + "\n", encoding="utf-8")


# Confirm the first helper reached every code edit before its known final anchor.
for path, marker in (
    ("backend/app/services/operational_safety.py", "def rebind_resolved_handoff_target("),
    ("backend/app/services/form_filler.py", "require_browser_entry_allowed(_job_url_requested"),
    ("backend/app/services/browser_handoff.py", "require_bound_handoff_url(session, page.url)"),
    ("backend/app/services/handoff_safety_integration.py", "rebind_resolved_handoff_target("),
    ("backend/app/services/application_target_handoff.py", 'metadata.get("resolved_target_url")'),
    ("backend/app/services/lever_readiness_hardening.py", "phase_a_candidates = ["),
    ("backend/app/services/lever_readiness_hardening.py", "duplicate_record_ids ="),
    ("backend/app/services/lever_pilot_ingestion.py", "from app.services.lever_readiness_hardening import harden_lever_readiness"),
):
    require_text(path, marker)

# Remove the post-lock hardening/persistence pass from the boundary wrapper by markers.
boundary_path = Path("backend/app/services/lever_pilot_ledger_boundary.py")
boundary = boundary_path.read_text(encoding="utf-8")
start_marker = "    validate_phase_b_runtime_ledger(runtime_path)\n    hardened_result = harden_lever_readiness(\n"
end_marker = "    return hardened_result\n"
start = boundary.find(start_marker)
if start < 0:
    raise SystemExit("Lever boundary hardening start marker missing")
end = boundary.find(end_marker, start)
if end < 0:
    raise SystemExit("Lever boundary hardening end marker missing")
end += len(end_marker)
boundary = boundary[:start] + "    validate_phase_b_runtime_ledger(runtime_path)\n    return result\n" + boundary[end:]
boundary_path.write_text(boundary, encoding="utf-8")

# Regression tests for every reported P1 failure.
day06 = Path("backend/tests/test_day06_operational_safety.py")
text = day06.read_text(encoding="utf-8")
text = text.replace(
    "from app.services import operational_safety\n",
    "from app.services import browser_handoff, form_filler, operational_safety\n",
    1,
)
text = text.replace(
    "    operational_safety_manifest,\n",
    "    operational_safety_manifest,\n    OperationalSafetyViolation,\n    rebind_resolved_handoff_target,\n",
    1,
)
day06.write_text(text, encoding="utf-8")
append_once(
    str(day06),
    "test_global_kill_switch_blocks_all_shared_browser_entry_points",
    '''@pytest.mark.asyncio
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
    assert wrong.code == "handoff_posting_mismatch"''',
)

append_once(
    "backend/tests/test_lever_readiness_hardening.py",
    "test_historical_boundary_rows_do_not_poison_future_phase_a_certification",
    '''def test_historical_boundary_rows_do_not_poison_future_phase_a_certification(tmp_path):
    baseline = tmp_path / "phase-a.csv"
    ledger = tmp_path / "phase-b.jsonl"
    rows = [{
        "run_id": "historical-captcha",
        "site": "historical-site",
        "posting_id": "historical-posting",
        "region": "global",
        "pre_submit_state": "manual_challenge_handoff",
        "final_status": "needs_review",
        "official_posting_inspection_passed": "false",
    }]
    rows.extend({
        "run_id": f"qualified-{index}",
        "site": f"qualified-site-{index}",
        "posting_id": f"posting-{index}",
        "region": "global" if index % 2 else "eu",
        "pre_submit_state": "ready_to_submit",
        "final_status": "dry_run_passed",
        "official_posting_inspection_passed": "true",
    } for index in range(30))
    _write_phase_a(baseline, rows)
    summary = harden_lever_readiness(
        _base_readiness(), baseline_path=baseline, ledger_path=ledger
    )["summary"]
    assert summary["qualifying_dry_run_count"] == 30
    assert summary["manual_challenge_boundary_count"] == 1
    assert summary["phase_a_inspection_failure_count"] == 0
    assert summary["gates"]["thirty_qualifying_dry_runs"] is True
    assert summary["gates"]["all_phase_a_records_have_successful_matching_inspection"] is True


def test_duplicate_indicator_on_blocked_phase_b_record_fails_duplicate_gate(tmp_path):
    baseline = tmp_path / "phase-a.csv"
    ledger = tmp_path / "phase-b.jsonl"
    records = [_phase_b_record(index) for index in range(10)]
    blocked = _phase_b_record(99)
    blocked.update({
        "final_status": "blocked",
        "pre_submit_state": "blocked",
        "duplicate_submission_detected": True,
    })
    records.append(blocked)
    _write_phase_b(ledger, records)
    summary = harden_lever_readiness(
        _base_readiness(), baseline_path=baseline, ledger_path=ledger
    )["summary"]
    assert summary["raw_supervised_confirmed_count"] == 10
    assert summary["supervised_confirmed_count"] == 10
    assert summary["duplicate_submission_count"] == 1
    assert summary["gates"]["zero_duplicate_submissions"] is False
    assert summary["supervised_pilot_evidence_complete"] is False''',
)

pilot_test = Path("backend/tests/test_lever_pilot_ingestion.py")
text = pilot_test.read_text(encoding="utf-8")
text = text.replace("import json\n", "import json\nfrom contextlib import contextmanager\n", 1)
text = text.replace(
    "from app.services.application_state import record_submission_evidence\n",
    "from app.services.application_state import record_submission_evidence\nfrom app.services import lever_pilot_ingestion\n",
    1,
)
pilot_test.write_text(text, encoding="utf-8")
append_once(
    str(pilot_test),
    "test_hardening_and_summary_persistence_use_the_ingestion_lock_snapshot",
    '''def test_hardening_and_summary_persistence_use_the_ingestion_lock_snapshot(
    db_session, tmp_path, monkeypatch
):
    user, job, application = _confirmed_fixture(db_session)
    paths = _paths(tmp_path)
    original_lock = lever_pilot_ingestion._ledger_lock
    original_harden = lever_pilot_ingestion.harden_lever_readiness
    state = {"inside_lock": False, "hardened": False}

    @contextmanager
    def observed_lock(path, *, exclusive):
        with original_lock(path, exclusive=exclusive):
            state["inside_lock"] = True
            try:
                yield
            finally:
                state["inside_lock"] = False

    def observed_harden(readiness, *, baseline_path, ledger_path):
        assert state["inside_lock"] is True
        state["hardened"] = True
        return original_harden(
            readiness, baseline_path=baseline_path, ledger_path=ledger_path
        )

    monkeypatch.setattr(lever_pilot_ingestion, "_ledger_lock", observed_lock)
    monkeypatch.setattr(lever_pilot_ingestion, "harden_lever_readiness", observed_harden)
    result = ingest_confirmed_lever_application(
        db_session, application, user, job, **paths
    )
    assert state["hardened"] is True
    persisted = json.loads(paths["summary_json_path"].read_text(encoding="utf-8"))
    expected = {
        key: value for key, value in result.items() if key not in {"added", "record"}
    }
    assert persisted == expected
    assert persisted["runtime_record_count"] == result["runtime_record_count"]
    assert persisted["runtime_ledger_sha256"] == result["runtime_ledger_sha256"]
    assert persisted["ledger_sha256"] == result["ledger_sha256"]''',
)
