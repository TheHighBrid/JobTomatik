from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


QUEUE_PATH = Path("evidence/lever-phase-b-candidate-review-2026-08-28.json")


def _load_queue() -> dict:
    value = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_phase_b_candidate_review_queue_is_read_only_and_distinct():
    queue = _load_queue()
    candidates = list(queue.get("candidates") or [])

    assert queue["schema_version"] == "lever-phase-b-candidate-review-v1"
    assert queue["purpose"] == "owner_review_before_supervised_phase_b_selection"
    assert queue["required_confirmed_phase_b_submissions"] == 10
    assert queue["prepared_candidate_count"] == len(candidates) >= 12
    assert queue["distinct_lever_site_count"] == len({str(item["site"]).casefold() for item in candidates})

    for forbidden in (
        "selected_by_user",
        "authorization_issued",
        "submission_queued",
        "runtime_flags_changed",
        "real_submission_enabled",
        "lever_supervised_pilot_enabled",
        "autopilot_enabled",
        "promotion_authorized",
    ):
        assert queue[forbidden] is False
    assert queue["owner_selection_required"] is True

    posting_ids = []
    sites = []
    for expected_rank, candidate in enumerate(candidates, start=1):
        assert candidate["rank"] == expected_rank
        assert candidate["source_kind"] == "direct_employer_lever"
        assert candidate["selected"] is False
        assert candidate["preflight_status"] == "not_materialized"
        assert str(candidate["posting_id"]).strip()
        assert str(candidate["site"]).strip()
        assert str(candidate["employer"]).strip()
        assert str(candidate["role"]).strip()

        parsed = urlparse(str(candidate["canonical_url"]))
        assert parsed.scheme == "https"
        assert parsed.netloc.casefold() == "jobs.lever.co"
        assert parsed.path.strip("/").split("/")[-1] == candidate["posting_id"]

        posting_ids.append(str(candidate["posting_id"]).casefold())
        sites.append(str(candidate["site"]).casefold())

    assert len(posting_ids) == len(set(posting_ids))
    assert len(sites) == len(set(sites))


def test_phase_b_candidate_review_queue_does_not_become_selection_receipt():
    queue = _load_queue()
    raw = json.dumps(queue, sort_keys=True).casefold()

    assert "one final-submit click maximum per approval" in raw
    assert "no legal, work-authorization" in raw
    assert "availability must be revalidated immediately before owner selection/import" in raw
    assert "authorize_final_submit" not in queue
    assert "approval_reference" not in queue
    assert "selection_quote" not in queue
