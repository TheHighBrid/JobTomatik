# Current-Head Final Acceptance Gate

## Why this gate exists

JobTomatik previously reached a state where isolated fixes and green unit tests were handed to the device too early. The most visible failure was the LinkedIn application path stopping at an ordinary **Apply** doorway or application form and creating a human handoff instead of continuing automatically.

This gate makes that class of regression a required current-head CI check rather than a device-debugging exercise.

## Acceptance path

The workflow `.github/workflows/current-head-final-acceptance.yml` exercises the exact reported application shape with Playwright Chromium:

```text
LinkedIn job 4442675569
  -> Apply / click-only Apply
  -> Affirm Greenhouse application target
  -> application form detected
  -> first name, last name, email, phone, cover letter, and résumé filled
  -> dry-run ready-to-submit boundary
```

The workflow proves that ordinary application navigation and fillable ATS forms do **not** create a retained-browser handoff.

It also verifies stale pre-form handoff retirement/revalidation so an old navigation session cannot strand a new attempt on an obsolete LinkedIn page.

## Android-style runtime path

The same workflow then starts the exact checked-out revision as a serialized Celery worker using the Android production queue shape:

```text
applications, celery, followup, scraping
```

It uses Redis DB1 and proves a producer can enqueue an application canary and receive the result from the exact revisioned worker.

The gate re-runs the Android runtime, stale-worker retirement, recovery, task-liveness, browser-tab refresh, and runtime-preparation regression contracts.

## Exact revision identity

Before either acceptance block runs, the workflow binds:

- `JOBTOMATIK_RUNTIME_REVISION`
- `JOBTOMATIK_EXPECTED_REVISION`

both to the checked-out Git revision and requires the runtime-identity attestation check to pass.

The resulting receipt therefore describes the exact tested tree rather than a nearby branch or historical build.

## Safety boundary

The gate runs with all consequential execution controls disabled:

- `ALLOW_REAL_APPLICATION_SUBMIT=false`
- `ALLOW_REAL_FOLLOWUP_SEND=false`
- `AUTOPILOT_ENABLED=false`
- `ENABLE_RESUMABLE_HANDOFFS=false`
- `GREENHOUSE_SUPERVISED_PILOT_ENABLED=false`
- `LEVER_SUPERVISED_PILOT_ENABLED=false`

The browser fixtures are local routed pages. The gate does not contact LinkedIn, Affirm, Greenhouse, or another employer, and it never clicks a final application submit control.

## Evidence artifact

A successful run uploads:

- `current-head-final-acceptance.json`
- `current-head-revision.txt`
- the exact-head Celery worker log

The JSON receipt includes the tested revision, every required acceptance assertion, runtime-safety state, and a SHA-256 over the canonical receipt body.

It explicitly records:

```json
"live_device_acceptance_performed": false
```

CI is the non-device acceptance layer. It is not allowed to claim that the Android device itself was tested when it was not.

## When the device is finally involved

A live Android acceptance check is justified only after this gate and the repository's normal backend/browser, Android, security, reproducibility, and stabilization gates are green on the same candidate revision.

That device check is then a single final acceptance of the already-certified flow, not another exploratory debugging loop.

## Regression policy

This workflow runs on every pull request and every push to `main`, even when the changed files are outside the application-entry implementation.

That is intentional. Cross-cutting runtime, task, browser, model, dependency, or integration changes can regress application progression without modifying the original navigation file, so path-filtered testing is not sufficient for this final acceptance invariant.
