# Judge review repair package

Certification remains **2/10**. This package is engineering work, not a new
certification result. It does not authorize deployment, database repair, an
application retry, final submission, or work on 3/10.

## What changed

The legacy review writer gave final-submit items an answer-policy summary. The
existing summary correction prevents new instances, but the repair classifier
still trusted the old summary and the nonempty `questions` container. The new
predicate requires homogeneous, positively identified question records, rejecting
mixed, malformed and final-action records. GET serialization never repairs the DB.

The explicit SQLite repair command restores only a review's reason and summary
(and its update timestamp), recording an event in the same transaction. It keeps
all original details, logs and previous revalidation/repair events. Its default
mode is a WAL-aware read-only transaction, not `immutable=1`.

It refuses unless the owner/application/review, verified stored Lever target,
exact target URL, single final-action item, explicit false submission flags,
matching ordered browser/final-ready fingerprints, field counts, and original
misclassification event agree. It also requires an open review, pending
application, and no approval, submission, evidence, receipt or handoff records.
Missing schema/evidence causes refusal, not weakened checks.

The command does not restore a usable browser session. A repaired review is
historical classification only, never evidence of current submit readiness.

## Validation status

- Eight portable unittest engineering checks passed in the preparation workspace.
- Fixtures reconstruct the sanitized structure from the tablet audit; they are
  not the raw 39-entry production log or a physical-device run.
- API/persistence regressions were added to the existing focused suite. They
  must run in the tablet's production dependency environment before acceptance.
- No live database preview or repair was executed by the package author.
- No physical Android acceptance, new application preparation or submission ran.

## One bounded on-device handoff

Fetch this package's exact commit into a **separate worktree** using Git. Do not
switch, reset or update the running production checkout, and do not edit the
tablet's interrupted worktree. Fetching a prepared commit does not require the
broken patch helper.

Use the already identified production Python executable and installed dependencies
from the Ubuntu proot environment. From the separate worktree, first run:

```sh
python -m unittest discover -s backend/tests -p test_final_submit_review_package.py -v
```

Here and below `python` means that production executable, not native Termux
Python. Before pytest, inspect conftest/config for the working revision and direct
every test database to an isolated disposable path; never allow the production
database URL into tests. Run only:

```sh
python -m pytest backend/tests/test_misclassified_answer_policy_review_repair.py backend/tests/test_application_step_review.py backend/tests/test_final_submit_review_package.py -q
```

Do not install dependencies or run a full release matrix to solve an unrelated
tooling problem. Report an unavailable prerequisite precisely.

Then run a **preview only** using the actual locally verified database path,
owner ID and target hash. Do not guess IDs from user counts, expose credentials,
or obtain a new target by contacting the ATS:

```sh
python backend/scripts/repair_final_submit_review.py --database VERIFIED_DB_PATH --application-id 261 --review-id 250 --user-id VERIFIED_OWNER_ID --expected-target-hash VERIFIED_TARGET_HASH
```

The output contains a snapshot digest, reason transition and identifiers, not raw
answers, browser session IDs or logs. Stop after returning test results and this
preview. If it refuses, inspect the stated mismatch without loosening guards.

## Production application and rollback, only after review

Prepare a consistent SQLite backup with the backup API; include WAL through the
API instead of copying an open database file. Verify the backup opens correctly.
Quiesce the affected workflow before database repair. Use the existing managed
deployment procedure for the reviewed immutable runtime artifact, retaining the
previous artifact as code rollback. Require matching API/worker/Beat/frontend
revision receipts and physical Android acceptance including Playwright over CDP.

Re-run the preview immediately before applying. The explicit apply invocation is
the preview command plus `--apply --expected-digest PREVIEW_DIGEST`. The command
takes a write lock and recomputes the state digest, refusing stale previews. A
repeat apply of the same repair returns `already_repaired` without another event.

Verify the corrected reason and preserved raw details, prior events and
revalidation evidence; confirm no handoff, approval, submission or application
state was invented. The event retains the prior summary/reason and checksum
receipts. Checksums detect accidental differences; they are not an externally
anchored tamper-proof audit system.

For a bookkeeping rollback, run the same preview command with
`--undo-event REPAIR_EVENT_ID`, then add `--apply --expected-digest UNDO_PREVIEW_DIGEST`.
Undo only restores the previous reason/summary and adds a new audit event. It
refuses if the review changed, protected records appeared or later application
events exist. Never overwrite intervening production activity with a whole-DB
restore. A rollback restores the known old classification defect and does not
certify the judge.

A future, separately authorized fill-only run on the actual tablet must verify
the complete frontend/API/worker/browser/handoff path without clicking Submit.
That production verification is still outstanding; do not claim it from these
engineering tests or request 3/10 yet.
