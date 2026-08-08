# Phase 11 — Full-Stack Shadow Campaigns

Phase 11 is the real evidence-collection layer behind JobTomatik's 4-hour, 8-hour, and 24-hour no-submit certification gates.

Phase 10 introduced the certification ledger and a policy-only elapsed-time harness. That harness is useful for proving timer and fail-safe mechanics, but it does not exercise the complete scheduler/discovery/application-preparation path. Phase 11 adds durable full-stack campaigns that do.

## Core boundary

A shadow campaign exercises production scheduling paths while application submission remains disabled.

Required runtime conditions at campaign start and on every cycle:

- `ALLOW_REAL_APPLICATION_SUBMIT=false`
- `AUTOPILOT_ENABLED=true`
- global kill switch clear
- user `auto_search_enabled=true`
- user `auto_apply_enabled=true`
- user `dry_run_mode=true`
- candidate Git revision known and unchanged

`AUTOPILOT_ENABLED=true` is a scheduler prerequisite, not submission permission. The shadow supervisor never changes it. Operators must configure the runtime intentionally before starting a campaign.

The supervisor never changes:

- `ALLOW_REAL_APPLICATION_SUBMIT`
- `ALLOW_REAL_FOLLOWUP_SEND`
- `AUTOPILOT_ENABLED`
- global/platform kill switches
- adapter maturity
- final-submit approval
- recruiter-outreach approval
- release authorization

## Exact start and stop controls

A campaign can only start after preflight passes and the account supplies the exact phrase:

```text
START FULL STACK SHADOW <shadow_run_4h|shadow_run_8h|shadow_run_24h> <candidate-revision-prefix>
```

A live campaign can only be intentionally stopped with:

```text
STOP FULL STACK SHADOW <session_id>
```

Starting and stopping are account-scoped.

Only one active campaign can exist per account. This is protected twice:

1. service-level active-session checking; and
2. a unique database `active_guard` retained while the session is `scheduled`, `running`, `settling`, or `stopping`.

The database guard matters on Android/SQLite because SQLite does not provide PostgreSQL-style row-lock semantics for `SELECT ... FOR UPDATE`.

## Durable campaign state

`ShadowRunSession` retains:

- account ID;
- exact candidate revision;
- target evidence type;
- requested duration;
- cycle cadence;
- scheduled/running/settling/stopping/terminal state;
- start, expected end, settle deadline, heartbeat, and completion timestamps;
- passed/failed cycle counts;
- application/review/reconciliation counters;
- configuration and baseline snapshots;
- final report and SHA-256 identity;
- failure reason;
- optional linked certification evidence ID.

`ShadowRunCycle` retains each production scheduler cycle with:

- session/cycle identity;
- start/completion timestamps;
- scheduler result;
- observability snapshot;
- reconciliation snapshot;
- failure detail.

## Real scheduler correlation

Phase 11 calls the existing production `_run_scheduler_cycle_for_user` implementation. It does not create a shadow-only substitute scheduler.

A `shadow_session_id` is passed as correlation metadata only. It grants no authority.

The scheduler now returns and retains:

- `real_submission_enabled`;
- `dry_run`;
- `shadow_session_id`;
- discovery Celery task ID when present;
- exact application IDs queued by the cycle.

Application creation events retain:

```text
source = full_stack_shadow_scheduler
shadow_session_id = <session_id>
dry_run = true
```

Scheduled discovery strips the private `_shadow_session_id` parameter before contacting external discovery providers, then retains the session ID on the durable discovery `AgentRun.result` after ingestion.

## Every cycle fails closed

Before each cycle, Phase 11 rechecks the full preflight and candidate revision.

The campaign fails if the runtime changes in a way that would invalidate the evidence, including:

- real submission becoming enabled;
- global autopilot becoming unavailable;
- kill switch activation;
- required user scheduler setting changing;
- dry-run mode being disabled;
- candidate revision changing.

The scheduler result must explicitly report:

```text
real_submission_enabled = false
dry_run = true
shadow_session_id = current session
```

A contradictory scheduler result is a failed cycle.

Three consecutive failed cycles terminate the campaign. Any failed campaign cycle also prevents later qualification for that campaign.

## Duration is not qualification

Reaching four, eight, or twenty-four hours does not automatically create qualifying evidence.

When the requested duration expires, Phase 11 stops launching new scheduler cycles and enters `settling` when correlated dry-run application work is still active.

The bounded settling window is 45 minutes. This prevents a legitimate application-preparation task that began near the duration boundary from being mislabeled as a leak merely because it has not finished yet.

After active work settles, or the settle deadline expires, the campaign reconciles the retained state.

## Qualification gates

A completed campaign is qualification-eligible only when every gate passes:

- measured elapsed duration meets the requested target;
- at least one production scheduler cycle completed;
- zero campaign-cycle failures;
- correlated discovery was observed;
- correlated dry-run application preparation was observed;
- no scheduler application reference points to a missing record;
- no duplicate application reference exists across campaign cycles;
- no application acquired an actual/consequential submitted state;
- no runaway submission retry count exists;
- no failed or submission-uncertain application lacks a retained manual-review explanation;
- no correlated application is still `preparing` or `applying` after settling;
- no policy escape occurred;
- real submission remained disabled.

A campaign that reaches its clock target but fails reconciliation becomes `failed`, not `completed`.

## False-submission protection

The following are treated as forbidden submission outcomes during a no-submit campaign:

Application status:

- `applied`
- `interviewing`
- `offer`
- `rejected`

Automation state:

- `submitted`
- `confirmed`

Any of these creates a `shadow_submission_occurred` policy escape and makes the campaign non-qualifying.

The supervisor also refuses to trust a scheduler cycle that reports `real_submission_enabled=true`.

## Crash and broker recovery

Campaign supervision is durable through Celery.

`run_shadow_session_cycle` executes one bounded cycle and schedules the next checkpoint.

A beat task runs every fifteen minutes at minutes 11, 26, 41, and 56:

```text
app.tasks.shadow_runs.recover_stalled_shadow_sessions
```

It detects active sessions whose heartbeat has exceeded the bounded timeout and redispatches their supervisor.

The actual cycle service performs a second row-locked running-cycle check. A recent running cycle is not duplicated. A stale running cycle is marked failed before recovery proceeds, which preserves liveness without pretending the interrupted cycle was trustworthy evidence.

If the initial campaign dispatch fails, the retained campaign is marked failed and the API returns 503.

If a later self-scheduling broker dispatch fails, the active durable campaign remains recoverable by the periodic stalled-session task.

## Evidence bridge

A campaign does not certify itself.

After a campaign reaches terminal `completed` state with `qualification_eligible=true`, the account may explicitly record it into the Phase 10 certification ledger through:

```text
POST /api/shadow-runs/<session_id>/record-evidence
```

The bridge rechecks:

- account ownership;
- terminal completed state;
- exact current candidate revision;
- retained final-report SHA-256;
- session/report identity consistency;
- qualification result;
- target evidence type.

The resulting `CertificationEvidence` record is always:

```text
status = passed
review_status = unreviewed
environment = full-stack-shadow
```

It includes the campaign report hash, measured duration, cycle counts, reconciliation signal, and explicit `submission_authorized=false` / `outreach_authorized=false` metadata.

Independent evidence review in Certification Center remains a separate step.

## API

Phase 11 adds:

- `GET /api/shadow-runs/preflight`
- `GET /api/shadow-runs`
- `GET /api/shadow-runs/{session_id}`
- `POST /api/shadow-runs`
- `POST /api/shadow-runs/{session_id}/stop`
- `POST /api/shadow-runs/{session_id}/record-evidence`

All retained campaign and evidence operations are account-scoped.

## Operator UI

`/shadow-campaigns` provides:

- 4h / 8h / 24h target selection;
- preflight checklist;
- exact start phrase;
- cycle interval control;
- active progress;
- settling state and deadline;
- cycle pass/fail counts;
- application, human-boundary, unexplained, duplicate, and runaway counters;
- final quality-gate matrix;
- report hash;
- exact stop phrase;
- explicit unreviewed-evidence recording.

The existing mobile bottom navigation remains intentionally unchanged; the new workspace is available from primary/sidebar navigation.

## CI is not real evidence

The Phase 11 GitHub Actions workflow tests the mechanism with synthetic time and isolated data. It does not run for four, eight, or twenty-four hours and must never be represented as real certification evidence.

Real certification still requires an actual campaign on the exact candidate revision, its retained reconciled report, and separate evidence verification.
