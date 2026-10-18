# JT5 retained-confirmation recovery

This candidate adds an authenticated review path for a saved uncertain JT5 attempt.
It depends on the late browser receipt preservation in PR #711.

## Supported behavior

The application detail page displays the saved confirmation text or employer
receipt ID. The owner selects a record, describes the finding, and explicitly
confirms the review. The server rechecks the current snapshot hash, application,
attempt binding, capture time, evidence strength and prior rejection.

A successful review records an immutable audit receipt, retains the original
attempt result, confirms the application, and closes only reviews bound to that
attempt. Later owner statuses such as interviewing, offer or rejected survive.
Repeating the identical request is idempotent. A changed decision is rejected.

The service locks the attempt before the application, matching worker and stale
recovery order. Busy PostgreSQL rows return HTTP 423 with no resolution recorded.

## Boundaries

- An active retained handoff blocks confirmation. This route does not cancel a
  handoff or terminate a browser. Finish or cancel through existing handoff controls.
- Screenshot-only evidence is retained but cannot be approved in this text/receipt
  review panel. Artifact inspection remains separate work.
- Missing, conflicting, stale, rejected or unbound evidence cannot confirm an attempt.
- Typed notes, case numbers and a checkbox cannot establish non-submission.
  Requests for that outcome return HTTP 409 and preserve the retry block.
- The non-submission intake and verification contract remains unfinished.
  This candidate does not claim to implement it.
- No browser opens, employer request, queue dispatch, new attempt, approval
  consumption or release-control change occurs through the recovery endpoint.
- Synthetic checks verify implementation behavior, not an employer outcome.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | /api/applications/{id}/jt5/reconciliation | Read owner-scoped retained review context |
| POST | /api/applications/{id}/jt5/reconcile | Record exact retained-confirmation review |

The response always declares automatic_retry_allowed=false.
The read context declares non_submission_resolution_available=false.
It also exposes resolution_available and blockers. Rejected snapshots and
incompatible application states never produce actionable confirmation choices.
Both the original attempt binding and the explicit trusted worker binding must
match; legacy evidence without the trusted field remains unavailable.
Whitespace-only text falls back to the retained employer receipt ID in the UI.

## Verification

The focused recovery tests cover ownership, strict review acknowledgement,
snapshot drift, exact evidence references, attempt and worker bindings, rejection,
active handoffs, preserved owner history, immutable audit and no dispatch.
The PostgreSQL job also exercises locked attempts and applications.
The browser smoke script uses the real React application page with synthetic
API responses and blocks every request outside its local fixture origin.

Run backend/tests/test_jt5_outcome_resolution.py with the late receipt and stale
recovery suites. Run frontend npm test and npm run build. For the mobile browser
fixture, start the frontend on a loopback port and execute
backend/scripts/smoke_jt5_outcome_recovery_ui.py with that local origin and a
private evidence output directory. It temporarily creates and removes its HTML
harness; traces and screenshots contain synthetic data only.

Integration order: review and integrate #711, retarget this stacked candidate to
main, complete final revision checks and independent review, then prepare an
owner-reviewed deployment candidate. Production state is not changed by this PR.
