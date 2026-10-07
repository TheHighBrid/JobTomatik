# GH-OH1 read-only preflight

GH-OH1 is the first supervised real Greenhouse acceptance on the OneHost
architecture. This preflight is intentionally one step before any consequential
execution.

Endpoint:

`GET /api/supervised-pilot/applications/{application_id}/gh-oh1-preflight`

The endpoint is authenticated and application-owner scoped.

## What it proves

The report composes the existing canonical Phase B dossier with the execution-host
contract and duplicate/replay state. A report may return
`READY FOR SUPERVISED EXECUTION` only when all non-final-action prerequisites are
satisfied:

- the application came through canonical Greenhouse Phase B intake;
- the exact owner-selected target remains structurally ready;
- required payload/document hashes and idempotency state exist;
- there are no unresolved manual-review blockers;
- production liveness/form-schema checks pass when production probing applies;
- the OneHost runtime owns local Playwright Chromium and retained handoff state;
- runtime and expected source revisions are exact and identical;
- resumable handoff is enabled;
- autopilot remains disabled;
- the emergency kill switch is not currently tripped;
- real-submit and Greenhouse supervised-execution flags remain closed before the
  exact execution boundary;
- no prior submission attempt, confirmation evidence, duplicate target ownership,
  consumed approval, or stale active approval exists.

## What it never does

Preflight never:

- opens Chromium;
- navigates to an employer;
- queues Celery work;
- changes a feature flag;
- issues, consumes, or revokes an approval;
- clicks a final action;
- submits an application;
- interacts with CAPTCHA, MFA, login, identity, or assessment controls.

The response always records these negative guarantees under `safety_boundary`.

## Final-action boundary

`READY FOR SUPERVISED EXECUTION` is not final-submit authorization.

After browser preparation, JobTomatik must revalidate the exact payload and obtain
the existing one-time application-bound approval before any human final action.
Any changed employer, role, URL, application id, resume hash, cover-letter hash,
answer-payload hash, form-schema hash, or other approval binding invalidates that
approval.

GH-OH1 remains subject to issue #655 and its evidence-before-state-promotion,
reconciliation, duplicate/retry suppression, and independent evidence-review rules.
