"""Portable engineering checks, not physical Android certification evidence.

Fixtures reconstruct the sanitized shape in the owner's tablet audit. They are
not an export of review 250 or the full 39-entry production log.
Run without the application/pytest environment using unittest discovery.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shape = load_module("review_shape_package", ROOT / "app/services/manual_review_shape.py")
repair = load_module("review_repair_package", ROOT / "scripts/repair_final_submit_review.py")
TARGET = "a" * 64
URL = "https://jobs.lever.co/example/retained-posting/apply"
OLD_SUMMARY = "1 application question(s) require an approved answer policy."


def retained_details():
    return {"method": "external_url", "questions": [{
        "reason_code": repair.FINAL_REASON,
        "summary": "Review the fully filled application and make the final Submit action yourself after exact approval.",
        "details": {"handoff_stage": "operator_final_submit", "fields_filled": 19,
                    "steps_completed": 1, "submit_clicked": False,
                    "operator_final_click_required": True,
                    "automated_submission_authorized": False,
                    "queue_submission_authorized": False, "target_identity_hash": TARGET},
    }], "log": [
        {"action": "ats_final_submit_ready", "adapter": "lever", "submit_clicked": False, "fingerprint": "fixture-fingerprint"},
        {"action": "browser_handoff_retained", "fields_filled": 19,
         "supervised_target_locked": True, "controlled_page_target_id_recorded": True,
         "current_fingerprint": "fixture-fingerprint"},
    ], "last_policy_revalidation": {"blocker_codes": ["retained_question_descriptor_missing"]}}


class ClassificationTests(unittest.TestCase):
    def classify(self, details, summary=OLD_SUMMARY):
        return shape.effective_answer_policy_reason(reason_code=repair.FINAL_REASON, summary=summary, details=details)

    def test_old_and_new_final_summaries_preserve_final_reason(self):
        details = retained_details()
        for summary in (OLD_SUMMARY, shape.result_review_summary(details["questions"])):
            self.assertEqual(self.classify(details, summary), repair.FINAL_REASON)
        self.assertNotIn("approved answer policy", shape.result_review_summary(details["questions"]))

    def test_caseware_question_repair_is_preserved(self):
        for reason in ("ambiguous_question", repair.FINAL_REASON):
            item = {"reason_code": reason, "details": {"descriptor": "Employer question?", "control_type": "radio", "required": True}}
            self.assertEqual(self.classify({"questions": [item]}), "ambiguous_question")

    def test_mixed_malformed_and_contradictory_groups_are_not_reinterpreted(self):
        final = retained_details()["questions"][0]
        question = {"reason_code": "ambiguous_question", "details": {"descriptor": "Question?"}}
        conflicting = deepcopy(final)
        conflicting["details"].update(descriptor="Question?", control_type="radio", required=True)
        for items in ([final, question], [question, None], [{}], [conflicting], "invalid"):
            self.assertEqual(self.classify({"questions": items}), repair.FINAL_REASON)


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fixture.db"
        self.kw = dict(app_id=261, review_id=250, user_id=7, target_hash=TARGET)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE applications(id INTEGER PRIMARY KEY,user_id INTEGER,job_id INTEGER,status TEXT,automation_state TEXT,applied_at TEXT,submission_attempt_count INTEGER,application_target_status TEXT,application_target_url TEXT);
                CREATE TABLE jobs(id INTEGER PRIMARY KEY,raw_data TEXT);
                CREATE TABLE manual_review_tasks(id INTEGER PRIMARY KEY,application_id INTEGER,reason_code TEXT,status TEXT,summary TEXT,details TEXT,blocking_url TEXT,resolved_at TEXT,updated_at TEXT);
                CREATE TABLE application_events(id INTEGER PRIMARY KEY,application_id INTEGER,event_type TEXT,from_state TEXT,to_state TEXT,payload TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            """)
            for table in repair.PROTECTED_TABLES:
                db.execute(f"CREATE TABLE {table}(application_id INTEGER)")
            db.execute("INSERT INTO applications VALUES(261,7,1,'pending','needs_review',NULL,0,'resolved',?)", (URL,))
            db.execute("INSERT INTO jobs VALUES(1,?)", (json.dumps({"supervised_target_metadata": {"identity_hash": TARGET, "verified": True, "platform": "lever", "canonical_application_url": URL}}),))
            db.execute("INSERT INTO manual_review_tasks VALUES(250,261,'ambiguous_question','open',?,?,?,NULL,NULL)", ("The retained review does not contain the employer question text.", json.dumps(retained_details()), URL))
            db.execute("INSERT INTO application_events(application_id,event_type,payload) VALUES(261,'misclassified_answer_policy_review_repaired',?)", (json.dumps({"review_id": 250, "previous_reason_code": repair.FINAL_REASON, "effective_reason_code": "ambiguous_question"}),))

    def snapshot(self):
        with sqlite3.connect(self.path) as db:
            return list(db.iterdump())

    def test_preview_apply_idempotency_preservation_and_undo(self):
        before = self.snapshot()
        preview = repair.run(self.path, **self.kw)
        self.assertEqual(before, self.snapshot())
        result = repair.run(self.path, **self.kw, apply=True, expected_digest=preview["snapshot_digest"])
        after = self.snapshot()
        again = repair.run(self.path, **self.kw, apply=True, expected_digest=preview["snapshot_digest"])
        self.assertEqual(again["status"], "already_repaired")
        self.assertEqual(after, self.snapshot())
        with sqlite3.connect(self.path) as db:
            self.assertEqual(json.loads(db.execute("SELECT details FROM manual_review_tasks").fetchone()[0]), retained_details())
            self.assertEqual(db.execute("SELECT status,automation_state,submission_attempt_count FROM applications").fetchone(), ("pending", "needs_review", 0))
            for table in repair.PROTECTED_TABLES:
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        undo = repair.run(self.path, **self.kw, undo_event=result["event_id"])
        repair.run(self.path, **self.kw, undo_event=result["event_id"], apply=True, expected_digest=undo["snapshot_digest"])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT reason_code FROM manual_review_tasks").fetchone()[0], "ambiguous_question")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM application_events").fetchone()[0], 3)

    def test_changed_state_wrong_owner_and_missing_digest_are_rejected(self):
        preview = repair.run(self.path, **self.kw)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE manual_review_tasks SET summary='changed'")
        before = self.snapshot()
        for kw in ({**self.kw, "apply": True}, {**self.kw, "apply": True, "expected_digest": preview["snapshot_digest"]}, {**self.kw, "user_id": 8}, {**self.kw, "target_hash": "b" * 64}):
            with self.assertRaises(repair.RepairRefused):
                repair.run(self.path, **kw)
        self.assertEqual(before, self.snapshot())

    def test_incomplete_contradictory_and_unbound_evidence_is_rejected(self):
        cases = []
        for key, value in (("submit_clicked", True), ("operator_final_click_required", 1), ("queue_submission_authorized", None), ("target_identity_hash", "b" * 64)):
            details = retained_details()
            details["questions"][0]["details"][key] = value
            cases.append(details)
        details = retained_details()
        details["log"][1]["current_fingerprint"] = "different"
        cases.append(details)
        details = retained_details()
        details["log"].reverse()
        cases.append(details)
        details = retained_details()
        details["questions"].append({"reason_code": "ambiguous_question"})
        cases.append(details)
        for details in cases:
            with sqlite3.connect(self.path) as db:
                db.execute("UPDATE manual_review_tasks SET details=?", (json.dumps(details),))
            with self.assertRaises(repair.RepairRefused):
                repair.run(self.path, **self.kw)

    def test_protected_records_and_missing_original_event_block_repair(self):
        for table in repair.PROTECTED_TABLES:
            with sqlite3.connect(self.path) as db:
                db.execute(f"INSERT INTO {table} VALUES(261)")
            with self.assertRaises(repair.RepairRefused):
                repair.run(self.path, **self.kw)
            with sqlite3.connect(self.path) as db:
                db.execute(f"DELETE FROM {table}")
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM application_events")
        with self.assertRaises(repair.RepairRefused):
            repair.run(self.path, **self.kw)

    def test_audit_insert_failure_rolls_back_review_change(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON application_events BEGIN SELECT RAISE(ABORT,'fixture audit failure'); END")
        preview = repair.run(self.path, **self.kw)
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            repair.run(self.path, **self.kw, apply=True, expected_digest=preview["snapshot_digest"])
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
