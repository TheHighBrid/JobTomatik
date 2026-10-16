# JT5 release notes (draft)

**Release state:** Candidate documentation only. Version and release date remain unset until JT5 verification, OneHost validation, main landing, and owner review are complete.

JT5 advances JobTomatik toward its product goal: live submission of real applications through a reliable, target-bound Apply flow.

## What changes

- Adds an owner-authenticated Apply action that reserves one attempt and dispatches the JT5 worker.
- Adds read-only status reporting for the latest attempt and application result.
- Uses durable attempt identity and atomic duplicate prevention.
- Keeps execution bound to the resolved employer target and application identity; invalid or drifting targets fail closed.
- Reports uncertain outcomes for reconciliation and does not retry them automatically.
- Removes the reserve-only API path so reservation and dispatch are not exposed as separate user actions.
- Keeps live-submit configuration under owner control while verification and production cutover are completed.

## Verification required before release

This draft does not certify that the release gates have passed. Complete and record:

- Exact-head focused and full backend verification.
- Four-gate regression coverage for authentication, ownership, atomic duplicate prevention, and uncertain outcomes.
- Greenhouse and Lever fixture execution on the JT5 path.
- Invalid-target and target-drift fail-closed checks.
- Frontend and Android checks.
- OneHost deployment, startup recovery, and retained-browser validation.

Use [the JT5 production cutover checklist](operations/JT5_PRODUCTION_CUTOVER_CHECKLIST.md) to record the candidate SHA, verification evidence, OneHost results, and owner decision.

## Production operation

Production live-submit enablement remains an explicit owner decision. After evidence review, use the approved production configuration process and verify the employer, role, target URL, and application identity before the first live Apply. Reconcile any uncertain result before attempting another submission.
