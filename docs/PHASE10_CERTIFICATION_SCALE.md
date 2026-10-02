# Phase 10: Certification, Recovery, and Scale

## Purpose

Phase 10 is the release-governance and final recovery layer for JobTomatik v2. It does not make the product autonomous by declaration. It makes every remaining autonomy and release claim depend on retained, reviewable evidence tied to the exact candidate commit, and it gives irrecoverable bounded work a durable dead-letter path instead of silently losing execution context.

The core rule is:

> Evidence, review, recovery, owner authorization, adapter maturity, and runtime enablement are separate gates.

A green certification screen never toggles `ALLOW_REAL_APPLICATION_SUBMIT`, `AUTOPILOT_ENABLED`, a platform kill switch, recruiter outreach, or an ATS maturity level.

This Phase 10 branch was rebased onto the merged Phase 9 observability head before validation so recovery and certification are evaluated against the actual current operations layer.

## Certification tracks

### Bounded autonomous pilot

The pilot track requires all of the following on the exact candidate head:

- supervised real-submission evidence;
- zero-false-submission audit;
- duplicate-prevention evidence;
- independently retained confirmation evidence;
- stale-attempt recovery and incident-response drill;
- **dead-letter checkpoint recovery evidence**;
- human-only handoff notifications;
- caps, quiet hours, exclusions, circuit breakers, and kill-switch controls;
- monitoring/alerting evidence;
- a measured unattended no-submit 4-hour run;
- a measured unattended no-submit 8-hour run;
- a measured unattended no-submit 24-hour run;
- separate owner authorization bound to the same commit.

The crash-recovery gate and dead-letter gate are intentionally separate. Recovering a stale application row does not prove that an exhausted bounded task can be safely requeued from an unchanged checkpoint.

### v2.1.0 release

The v2.1.0 release track requires every autonomous-pilot prerequisite plus:

- retained evidence that the bounded autonomous pilot completed successfully;
- exact-head Android device acceptance;
- retained release-artifact identity;
- an independently verified SHA-256 release checksum;
- separate owner authorization for the v2.1.0 release commit.

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

New evidence always starts as `unreviewed`. Recording a record does not make it qualifying.

Evidence identity is namespaced by the owning account. Two users may legitimately retain the same external workflow/source reference without one account reserving the other account's evidence key. System evidence uses a separate system namespace.

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
AUTHORIZE AUTONOMOUS_PILOT v2.1.0 <first-12-characters-of-commit>
```

or:

```text
AUTHORIZE V2_RELEASE v2.1.0 <first-12-characters-of-commit>
```

Pilot authorizations expire by default after four hours. v2 release authorizations expire by default after twenty-four hours. Both can be revoked explicitly.

An authorization row is re-hashed before reuse. If its scope, release version, commit, owner, approval reference, or expiry drifts after approval, it is no longer active.

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

## Dead-letter and checkpoint recovery

Irrecoverable bounded local agent tasks are retained inside the existing durable `AgentTask.task_output` record under a `dead_letter` envelope. This keeps recovery available for discovery/research/evaluation tasks that do not have an `Application` row.

A dead-letter envelope retains:

- run and task identity;
- plan task identity and agent type;
- exact task input;
- dependency identities, states, and output hashes;
- run-plan hash;
- stable run-context references;
- bounded approval state and scope;
- failure class/source and bounded error text;
- checkpoint SHA-256;
- attempt history and manual-requeue count;
- explicit `submission_authorized=false`;
- explicit `outreach_authorized=false`.

Automatic retry is disabled after the task enters dead-letter state.

### Exact manual requeue

A requeue requires the exact phrase exposed by the retained envelope:

```text
REQUEUE DEAD LETTER <task_id> <first-12-characters-of-checkpoint-hash>
```

Immediately before requeue, JobTomatik recomputes the checkpoint. Any change in task input, dependency evidence, plan identity, stable run context, or bounded approval state blocks replay with checkpoint drift.

A valid manual requeue:

- preserves historical `attempt_count`;
- grants only one additional bounded claim;
- has a maximum of two manual dead-letter requeues;
- resets only downstream tasks that were skipped because of the failed dependency;
- requires the original bounded-run approval to remain satisfied;
- refuses cancelled or paused runs;
- cannot inherit submission or recruiter-outreach authority.

### Resolve without replay

An operator may close an open dead letter without running it again using:

```text
RESOLVE DEAD LETTER <task_id> <first-12-characters-of-checkpoint-hash>
```

Resolution records the note while leaving the underlying task failed. It does not dispatch work.

### Recovery Center

`/recovery` provides:

- open/requeued/resolved dead-letter views;
- failure class and attempt counts;
- retained checkpoint hash;
- exact requeue and resolve phrases;
- explicit resolution note;
- bounded requeue dispatch result;
- clear separation from submission/outreach/maturity permissions.

API:

```text
GET  /api/recovery/dead-letters
POST /api/recovery/dead-letters/{task_id}/requeue
POST /api/recovery/dead-letters/{task_id}/resolve
```

All operations are account-scoped.

## Recovery certification drill

`backend/scripts/run_dead_letter_recovery_drill.py` runs in an isolated in-memory database and proves:

- exhausted work enters a durable dead-letter state;
- automatic retry is disabled;
- an unchanged checkpoint can be explicitly requeued;
- attempt history is preserved;
- only one additional claim is granted;
- mutated checkpoint input blocks replay;
- blocked drift remains failed;
- submission and outreach authorization remain false;
- no browser or external network is used.

The existing stale-application recovery drill remains separate and continues to prove safe handling of abandoned `applying` rows and uncertain live outcomes.

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
- `ALLOW_REAL_FOLLOWUP_SEND`;
- scheduler/autopilot enablement;
- global kill switch;
- disabled ATS/platform list;
- canonical ATS maturity.

The Recovery Center also does not alter those controls. A dead-letter requeue is permission for one bounded local task attempt, not permission for a consequential external action.

## Account isolation

User-recorded certification evidence is account-scoped. A user's readiness evaluator can use:

- evidence recorded by that user;
- explicitly system-recorded evidence where `recorded_by_user_id` is null.

It cannot qualify from another user's certification records or release authorization. Evidence keys are also account-namespaced so an identical external source identity cannot create a cross-account collision.

Dead-letter listing, requeue, and resolve operations join through the user-owned `AgentRun`, so another account cannot inspect or replay the task.

## Release artifacts

Release artifact evidence requires an artifact name and a supported kind:

- `android_apk`;
- `android_aab`;
- `source_bundle`.

Release checksum evidence requires a valid SHA-256 digest. Artifact and checksum records are still unreviewed until the separate evidence-verification action occurs.

## Existing operational evidence

Phase 10 composes, rather than replaces, the controls already implemented earlier in v2:

- Phase 9 operational observability and source/adapter incidents;
- ATS certification and maturity manifests;
- exact-payload supervised submission approval;
- submission evidence review;
- duplicate/idempotency protections;
- manual handoff notifications;
- operations caps, quiet hours, exclusions, circuit breakers, and kill switches;
- isolated stale-application recovery incident drill;
- Android authoritative runtime checks.

## API surface

```text
GET  /api/certification/manifest
GET  /api/certification/evidence
POST /api/certification/evidence
POST /api/certification/evidence/{evidence_id}/verify
POST /api/certification/authorizations
POST /api/certification/authorizations/{authorization_id}/revoke

GET  /api/recovery/dead-letters
POST /api/recovery/dead-letters/{task_id}/requeue
POST /api/recovery/dead-letters/{task_id}/resolve
```

## Product surfaces

`/certification` provides:

- exact candidate revision;
- autonomous-pilot and v2-release readiness matrices;
- current independent runtime-control state;
- retained evidence ledger;
- evidence recording and explicit verification;
- commit-bound owner authorization and revocation.

`/recovery` provides the bounded dead-letter queue and checkpoint actions.

The interfaces intentionally keep readiness/recovery separate from live-submit controls.

## What Phase 10 does not fabricate

Phase 10 cannot manufacture evidence for events that have not happened. In particular it does not pretend that any of these have occurred merely because the code exists:

- a supervised real application submission;
- a zero-false-submission production audit;
- real dead-letter recovery evidence outside the isolated certification drill;
- 4/8/24 hours of elapsed unattended shadow runtime;
- a bounded live autonomous pilot;
- final Android device acceptance on the exact release head;
- release artifact publication/checksum review;
- owner authorization.

Those gates stay visibly blocked until the corresponding real evidence exists.

## Automated certification

`.github/workflows/certification-scale.yml` runs with real submission, recruiter outreach, and autopilot disabled. It proves:

- evidence lifecycle and exact-head behavior;
- evidence-key account namespacing;
- release-authorization hash integrity;
- tamper, expiry, account-isolation, and duration fail-closed behavior;
- authorization prerequisites and revocation;
- no runtime side effects from evidence/review/authorization;
- release artifact/checksum validation;
- short measured shadow harness behavior;
- isolated stale-application recovery incident drill;
- isolated dead-letter checkpoint/requeue/drift drill;
- Recovery Center and Certification Center source contracts;
- production frontend build.

The short shadow smoke is never counted as the required 4/8/24-hour evidence.

## Completion boundary

Phase 10 implementation is complete when its code and full repository CI are green. The **project release** is complete only when the real evidence gates shown by the Certification Center are satisfied on one exact candidate head and the owner performs the final explicit authorization.
