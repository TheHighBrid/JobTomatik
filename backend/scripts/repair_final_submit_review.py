#!/usr/bin/env python3
"""Explicit SQLite bookkeeping repair. Preview is read-only; no ATS/ORM imports.

This restores classification only. It cannot recreate a browser handoff, establish
current readiness, grant submission authority, or change certification progress.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

FINAL_REASON = "operator_final_submit_required"
FINAL_SUMMARY = (
    "Retained evidence records the owner final-submit boundary. "
    "A current verified browser handoff is still required before any final action."
)
REPAIR_EVENT = "final_submit_review_classification_repaired"
UNDO_EVENT = "final_submit_review_classification_undone"
PROTECTED_TABLES = (
    "submission_approvals", "submission_attempts", "submission_evidence",
    "submission_evidence_reviews", "submission_evidence_receipts",
    "manual_handoff_sessions",
)


class RepairRefused(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RepairRefused(message)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


def object_json(raw: str | None) -> dict:
    value = json.loads(raw or "{}")
    require(isinstance(value, dict), "Expected a JSON object")
    return value


def read_state(db, app_id: int, review_id: int, user_id: int, target_hash: str) -> dict:
    require(bool(re.fullmatch(r"[0-9a-f]{64}", target_hash)), "Invalid expected target hash")
    app_row = db.execute("SELECT * FROM applications WHERE id=? AND user_id=?", (app_id, user_id)).fetchone()
    require(app_row is not None, "Application/owner mismatch")
    app = dict(app_row)
    require(app["status"] == "pending" and app["automation_state"] == "needs_review", "Application is not pending review")
    require(app["applied_at"] is None, "Application has an applied timestamp")
    require(app["application_target_status"] == "resolved", "Application target is unresolved")
    row = db.execute("SELECT * FROM manual_review_tasks WHERE id=? AND application_id=?", (review_id, app_id)).fetchone()
    require(row is not None, "Review/application mismatch")
    review = dict(row)
    require(review["status"] == "open" and review["resolved_at"] is None, "Review is not open")
    job = db.execute("SELECT raw_data FROM jobs WHERE id=?", (app["job_id"],)).fetchone()
    require(job is not None, "Application job is missing")
    metadata = object_json(job["raw_data"]).get("supervised_target_metadata")
    require(isinstance(metadata, dict), "Retained supervised target metadata is missing")
    require(metadata.get("identity_hash") == target_hash and metadata.get("verified") is True, "Verified target identity mismatch")
    require(metadata.get("platform") == "lever", "Repair is limited to retained Lever reviews")
    require(metadata.get("canonical_application_url") == app["application_target_url"] == review["blocking_url"], "Exact target URL mismatch")
    for table in PROTECTED_TABLES:
        # Table names are constants, never user input. Missing schema fails closed.
        require(db.execute(f"SELECT COUNT(*) FROM {table} WHERE application_id=?", (app_id,)).fetchone()[0] == 0,
                f"Application has protected records in {table}")
    events = [dict(row) for row in db.execute(
        "SELECT * FROM application_events WHERE application_id=? ORDER BY id", (app_id,),
    )]
    validate_preparation_attempts(app, events)
    return {"application": app, "review": review, "target": metadata, "events": events}


def validate_preparation_attempts(app: dict, events: list[dict]) -> None:
    # applications.apply increments this counter before filling, including dry runs.
    # A positive counter alone is neither submission evidence nor proof of safety.
    count = app["submission_attempt_count"]
    require(type(count) is int and count >= 0, "Invalid application attempt counter")
    starts = [object_json(event["payload"]) for event in events
              if event["event_type"] == "application_attempt_started"]
    require(len(starts) == count, "Attempt counter does not match retained preparation history")
    for number, payload in enumerate(starts, 1):
        require(type(payload.get("attempt")) is int and payload["attempt"] == number,
                "Retained preparation attempt sequence is incomplete or contradictory")
        require(payload.get("dry_run") is True,
                "Retained attempt is not explicitly dry-run preparation")


def validate_retained_final_action(state: dict, target_hash: str) -> None:
    details = object_json(state["review"]["details"])
    items = details.get("questions")
    require(isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict), "Expected exactly one retained final-action item")
    item = items[0]
    data = item.get("details")
    require(item.get("reason_code") == FINAL_REASON and isinstance(data, dict), "Nested final-action reason is missing")
    require(data.get("handoff_stage") == "operator_final_submit", "Final-action stage mismatch")
    for key, value in {
        "submit_clicked": False, "operator_final_click_required": True,
        "automated_submission_authorized": False, "queue_submission_authorized": False,
    }.items():
        require(data.get(key) is value, f"Missing or contradictory {key}")
    require(not any(key in data for key in ("descriptor", "control_type", "canonical_key")), "Contradictory employer-question metadata")
    require(data.get("target_identity_hash") == target_hash, "Retained item target mismatch")
    require(type(data.get("fields_filled")) is int and data["fields_filled"] > 0, "Verified field count is missing")
    log = details.get("log")
    require(isinstance(log, list) and all(isinstance(x, dict) for x in log), "Retained event log is malformed")
    require(not any(x.get("submit_clicked") is True for x in log), "Retained log contains a submit click")
    ready = [(i, x) for i, x in enumerate(log) if x.get("action") == "ats_final_submit_ready"]
    retained = [(i, x) for i, x in enumerate(log) if x.get("action") == "browser_handoff_retained"]
    require(len(ready) == len(retained) == 1, "Final-ready/browser-retained evidence is missing or ambiguous")
    i, final = ready[0]
    j, browser = retained[0]
    require(i < j and final.get("submit_clicked") is False and final.get("adapter") == "lever", "Final-ready evidence contradicts the boundary")
    require(browser.get("supervised_target_locked") is True and browser.get("controlled_page_target_id_recorded") is True, "Controlled browser target was not retained")
    require(browser.get("fields_filled") == data["fields_filled"], "Retained field counts disagree")
    require(bool(final.get("fingerprint")) and final["fingerprint"] == browser.get("current_fingerprint"), "Final-ready/browser fingerprints disagree")


def plan_repair(state: dict, target_hash: str, undo_event: int | None = None) -> dict:
    review = state["review"]
    validate_retained_final_action(state, target_hash)
    events = [(event, object_json(event["payload"])) for event in state["events"]]
    base = {
        "application_id": state["application"]["id"], "review_id": review["id"],
        "user_id": state["application"]["user_id"], "target_identity_hash": target_hash,
        "snapshot_digest": digest(state), "submission_authorized": False,
        "before": {"reason_code": review["reason_code"], "summary": review["summary"]},
    }
    if undo_event is not None:
        matches = [payload for event, payload in events if event["id"] == undo_event and event["event_type"] == REPAIR_EVENT and payload.get("review_id") == review["id"]]
        require(len(matches) == 1, "Repair event not found for this review")
        original = matches[0]
        require(digest(review) == original.get("after_review_digest"), "Review changed after repair; refusing rollback")
        require(not any(event["id"] > undo_event for event, _ in events), "Application has later events; refusing rollback")
        require(original.get("before", {}).get("reason_code") == "ambiguous_question", "Invalid repair event")
        return {**base, "event_type": UNDO_EVENT, "undo_event": undo_event, "after": original["before"]}
    if review["reason_code"] == FINAL_REASON:
        matches = [payload for event, payload in events if event["event_type"] == REPAIR_EVENT and payload.get("review_id") == review["id"] and payload.get("after_review_digest") == digest(review)]
        require(bool(matches), "Final-submit review has no matching repair receipt")
        return {**base, "already_repaired": True, "original_snapshot_digest": matches[-1]["snapshot_digest"]}
    require(review["reason_code"] == "ambiguous_question", "Review was not demoted to ambiguous_question")
    require(any(
        event["event_type"] == "misclassified_answer_policy_review_repaired"
        and payload.get("review_id") == review["id"]
        and payload.get("previous_reason_code") == FINAL_REASON
        and payload.get("effective_reason_code") == "ambiguous_question"
        for event, payload in events
    ), "Original misclassification event is missing")
    return {**base, "event_type": REPAIR_EVENT, "after": {"reason_code": FINAL_REASON, "summary": FINAL_SUMMARY}}


def run(database: Path, *, app_id: int, review_id: int, user_id: int,
        target_hash: str, apply: bool = False, expected_digest: str | None = None,
        undo_event: int | None = None) -> dict:
    require(not apply or bool(expected_digest), "Apply requires the preview snapshot digest")
    uri = database.resolve().as_uri() + ("?mode=rw" if apply else "?mode=ro")
    db = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        if not apply:
            db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        state = read_state(db, app_id, review_id, user_id, target_hash)
        plan = plan_repair(state, target_hash, undo_event)
        if plan.get("already_repaired"):
            require(not apply or expected_digest in (plan["snapshot_digest"], plan["original_snapshot_digest"]), "Preview digest mismatch")
            db.rollback()
            return {"status": "already_repaired", "review_id": review_id, "submission_authorized": False}
        if not apply:
            db.rollback()
            # No retained answers, browser session identifiers, or raw history are emitted.
            return {"status": "preview", "application_id": app_id, "review_id": review_id,
                    "snapshot_digest": plan["snapshot_digest"], "event_type": plan["event_type"],
                    "before_reason": plan["before"]["reason_code"], "after_reason": plan["after"]["reason_code"],
                    "submission_authorized": False}
        require(expected_digest == plan["snapshot_digest"], "State changed since preview; refusing mutation")
        db.execute("UPDATE manual_review_tasks SET reason_code=?, summary=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND application_id=?",
                   (plan["after"]["reason_code"], plan["after"]["summary"], review_id, app_id))
        after = dict(db.execute("SELECT * FROM manual_review_tasks WHERE id=?", (review_id,)).fetchone())
        plan["before_review_digest"] = digest(state["review"])
        plan["after_review_digest"] = digest(after)
        plan["preserved_details_digest"] = digest(state["review"]["details"])
        plan["receipt_digest"] = digest(plan)
        cursor = db.execute(
            "INSERT INTO application_events(application_id,event_type,from_state,to_state,payload) VALUES(?,?,?,?,?)",
            (app_id, plan["event_type"], "needs_review", "needs_review", json.dumps(plan, sort_keys=True)),
        )
        db.commit()
        return {"status": "applied", "event_id": cursor.lastrowid, "receipt_digest": plan["receipt_digest"], "submission_authorized": False}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--application-id", required=True, type=int)
    parser.add_argument("--review-id", required=True, type=int)
    parser.add_argument("--user-id", required=True, type=int)
    parser.add_argument("--expected-target-hash", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-digest")
    parser.add_argument("--undo-event", type=int)
    args = parser.parse_args()
    try:
        result = run(args.database, app_id=args.application_id, review_id=args.review_id,
                     user_id=args.user_id, target_hash=args.expected_target_hash,
                     apply=args.apply, expected_digest=args.expected_digest, undo_event=args.undo_event)
    except (RepairRefused, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        raise SystemExit(f"Repair refused: {type(exc).__name__}: {exc}") from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
