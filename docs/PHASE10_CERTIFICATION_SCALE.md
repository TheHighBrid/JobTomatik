# Phase 10: Certification and Scale

## Purpose

Phase 10 is the release-governance layer for JobTomatik v2. It does not make the product autonomous by declaration. It makes every remaining autonomy and release claim depend on retained, reviewable evidence tied to the exact candidate commit.

The core rule is:

> Evidence, review, owner authorization, adapter maturity, and runtime enablement are separate gates.

A green certification screen never toggles `ALLOW_REAL_APPLICATION_SUBMIT`, `AUTOPILOT_ENABLED`, a platform kill switch, or an ATS maturity level.

## Certification tracks

### Bounded autonomous pilot

The pilot track requires all of the following on the exact candidate head:

- supervised real-submission evidence;
- zero-false-submission audit;
- duplicate-prevention evidence;
- independently retained confirmation evidence;
- recovery/incident drill;
- human-only handoff notifications;
- caps, quiet hours, exclusions, circuit breakers, and kill-switch controls;
- monitoring/alerting evidence;
- a measured unattended no-submit 4-hour run;
- a measured unattended no-submit 8-hour run;
- a measured unattended no-submit 24-hour run;
- separate owner authorization bound to the same commit.

### v2.00 release

The v2.00 release track requires every autonomous-pilot prerequisite plus:

- retained evidence that the bounded autonomous pilot completed successfully;
- exact-head Android device acceptance;
- retained release-artifact identity;
- an independently verified SHA-256 release checksum;
- separate owner authorization for the v2.00 release commit.

## Evidence lifecycle

### 1. Record

`POST /api/certification/evidence`

A record contains:

- evidence type;
- optional ATS adapter;
- exact commit SHA;
- environment;
- pass/fail status;
- measured duration where applicable;
- durable source reference;
- evidence-specific metadata;
- SHA-256 hash of the canonical evidence payload;
- recorder identity;
- optional expiry.

New evidence always starts as `unreviewed`.

Recording a record does not make it qualifying.

### 2. Verify

`POST /api/certification/evidence/{id}/verify`

Verification requires the exact acknowledgment:

```text
VERIFY EVIDENCE <id> <first-12-characters-of-commit>
```

Before a record can become `verified`, the API rechecks payload integrity, pass/fail state, expiry, and any measured minimum duration. After verification, the manifest still rejects the record when it does not match the current candidate head.

### 3. Authorize

`POST /api/certification/authorizations`

Owner authorization is impossible until the selected track reports every prerequisite as qualifying on the exact current runtime revision.

The acknowledgment is commit-bound:

```text
AUTHORIZE AUTONOMOUS_PILOT v2.00 <first-12-characters-of-commit>
```

or:

```text
AUTHORIZE V2_RELEASE v2.00 <first-12-characters-of-commit>
```

Pilot authorizations expire by default after four hours. v2 release authorizations expire by default after twenty-four hours. Both can be revoked explicitly.

Authorization records a decision. It does not enable runtime submission.

## Fail-closed evidence semantics

A record is non-qualifying when any of these are true:

- missing;
- status is not `passed`;
- not independently verified through the separate review action;
- commit does not exactly match the candidate head;
- expired;
- canonical payload hash no longer matches;
- a shadow run is shorter than its required measured duration.

The release evaluator never substitutes a similar commit, historical success, a newer copy of an old report, or a requested duration for actual measured elapsed time.

## Shadow rehearsal

`backend/scripts/run_shadow_rehearsal.py` is an unattended **no-submit** harness.

It never opens an employer browser, never contacts an employer, never clicks final submit, and never changes runtime settings. It repeatedly checks the canonical operations and ATS manifests and measures elapsed time with a monotonic clock.

Example smoke run:

```bash
cd backend
python scripts/run_shadow_rehearsal.py \
  --duration-seconds 2 \
  --interval-seconds 0.25 \
  --output certification-artifacts/shadow-smoke.json
```

A short CI smoke proves only that the harness works. It explicitly returns `qualification_eligible=false`.

The 4-hour, 8-hour, and 24-hour gates become true only when `measured_duration_seconds` reaches 14,400, 28,800, and 86,400 seconds respectively while all no-submit assertions remain true.

Shadow evidence submitted to the certification ledger must also declare:

```json
{
  "final_submit_enabled": false,
  "final_submit_clicked": false,
  "measured_elapsed_time": true
}
```

The API rejects shadow evidence that does not preserve those invariants.

## Runtime controls remain independent

The Certification Center reports, but does not alter:

- `ALLOW_REAL_APPLICATION_SUBMIT`;
- scheduler/autopilot enablement;
- global kill switch;
- disabled ATS/platform list;
- canonical ATS maturity.

This separation prevents a certification record, an owner click, or a stale database row from accidentally becoming permission to submit applications.

## Account isolation

User-recorded certification evidence is account-scoped. A user's readiness evaluator can use:

- evidence recorded by that user;
- explicitly system-recorded evidence where `recorded_by_user_id` is null.

It cannot qualify from another user's certification records or release authorization.

## Release artifacts

Release artifact evidence requires an artifact name and a supported kind:

- `android_apk`;
- `android_aab`;
- `source_bundle`.

Release checksum evidence requires a valid SHA-256 digest. Artifact and checksum records are still unreviewed until the separate evidence-verification action occurs.

## Existing operational evidence

Phase 10 composes, rather than replaces, the controls already implemented earlier in v2:

- ATS certification and maturity manifests;
- exact-payload supervised submission approval;
- submission evidence review;
- duplicate/idempotency protections;
- manual handoff notifications;
- operations caps, quiet hours, exclusions, circuit breakers, and kill switches;
- isolated recovery incident drill;
- Android authoritative runtime checks.

The new certification ledger provides the retained exact-head evidence and owner-gate structure needed to decide when those controls have collectively earned a pilot or release claim.

## API surface

```text
GET  /api/certification/manifest
GET  /api/certification/evidence
POST /api/certification/evidence
POST /api/certification/evidence/{evidence_id}/verify
POST /api/certification/authorizations
POST /api/certification/authorizations/{authorization_id}/revoke
```

## Product surface

`/certification` provides:

- exact candidate revision;
- autonomous-pilot and v2-release readiness matrices;
- current independent runtime-control state;
- retained evidence ledger;
- evidence recording and explicit verification;
- commit-bound owner authorization and revocation.

The interface intentionally disables authorization while prerequisites are incomplete.

## What Phase 10 does not fabricate

Phase 10 cannot manufacture evidence for events that have not happened. In particular it does not pretend that any of these have occurred merely because the code exists:

- a supervised real application submission;
- a zero-false-submission production audit;
- 4/8/24 hours of elapsed unattended shadow runtime;
- a bounded live autonomous pilot;
- final Android device acceptance on the exact release head;
- release artifact publication/checksum review;
- owner authorization.

Those gates stay visibly blocked until the corresponding real evidence exists.

## Automated certification

`.github/workflows/certification-scale.yml` runs with real submission and autopilot disabled. It proves:

- evidence lifecycle and exact-head behavior;
- tamper, expiry, account-isolation, and duration fail-closed behavior;
- authorization prerequisites and revocation;
- no runtime side effects from evidence/review/authorization;
- release artifact/checksum validation;
- short measured shadow harness behavior;
- isolated recovery incident drill;
- Certification Center source contracts and production frontend build.

The short shadow smoke is never counted as the required 4/8/24-hour evidence.

## Completion boundary

Phase 10 implementation is complete when its code and full repository CI are green. The **project release** is complete only when the real evidence gates shown by the Certification Center are satisfied on one exact candidate head and the owner performs the final explicit authorization.
