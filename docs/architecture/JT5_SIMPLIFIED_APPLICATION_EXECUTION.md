# JT5 simplified application execution: implementation contract

Status: migration in progress; no production behavior changes in this commit.

## Owner-approved product contract
One authenticated Apply action for a selected application. No extra approval reference, approval expiration ceremony, platform pilot flag, or second confirmation step. Preserve four protections: authentication, ownership, atomic duplicate prevention, and uncertain-outcome reconciliation.

## Findings from current main
- `backend/app/api/supervised_submissions.py` exposes a separate supervised approval/queue API.
- `backend/app/services/supervised_submission.py` creates exact-payload one-time approvals and validates expiration.
- `backend/app/services/supervised_submission_integration.py` revalidates approval in the worker.
- `backend/app/services/submission_integrity_integration.py` patches validation and reservation functions.
- `backend/app/tasks/applications.py` contains `LIVE_SUBMIT_BLOCKED_REASON` and the real-submit setting.
- `backend/app/config.py` defines release/pilot controls.
- `backend/app/services/supervised_platforms.py` defines platform pilot policies.
- `OPERATIONS_GUIDE.md` documents global kill switch, autopilot and handoff switches.
- `scripts/verify.sh` and `scripts/verify-onehost-handoff.sh` explicitly disable live submission in test environments.

## Migration phases (avoid partial deletion)
1. Trace every caller of the supervised approval and platform pilot interfaces, including Android UI, tests, workers and scheduled flows.
2. Add one authenticated application execution endpoint using the existing user ownership check and durable submission-attempt records.
3. Atomically reserve the attempt using database locking/uniqueness. A confirmed application returns the existing receipt; an uncertain attempt returns the existing uncertain status, never a second submission.
4. Adapt the existing Greenhouse and Lever browser executors to accept the reserved attempt without an approval reference. Retain form validation, real site limitations, evidence capture and browser resource isolation as ordinary implementation behavior.
5. Remove the approval issue/revoke/expiry dependency, pilot enablement gates, redundant runtime flag gates and UI double-confirmation after all callers migrate.
6. Remove owner-facing autopilot/scheduling/concurrency/browser-ownership switches as requested; do not delete essential queue scheduling infrastructure or OS/browser resource isolation blindly. If scheduling is removed as a feature, retire scheduled dispatch jobs and related endpoints with tests.
7. Rewrite verification to use mocked ATS submissions in tests without depending on live-submit environment flags.
8. Update API schemas, migrations, Android client, docs and CI together; prove exact-head tests before merge.

## Acceptance tests
- Unauthenticated request: rejected.
- Authenticated non-owner: rejected.
- First valid request: one attempt reserved and one browser execution dispatched.
- Simultaneous duplicate requests: at most one attempt executes.
- Confirmed previous attempt: returns receipt, no new execution.
- Uncertain previous attempt: returns uncertain state, no retry until reconciliation.
- Failed-before-submit attempt: retry can be authorized without extra approval ceremony.
- Browser fails after possible submit: classify uncertain, never claim confirmed.
- Greenhouse/Lever fill and upload behavior unchanged.
- No references to deprecated approval/pilot toggles in the active execution path.
- Backend and worker use identical code revision.

## Explicit non-goals
- Do not infer that a queued task or DOM click is an employer receipt.
- Do not hardcode applicant answers or remove authentication.
- Do not merge a documentation-only change as if the implementation were complete.
