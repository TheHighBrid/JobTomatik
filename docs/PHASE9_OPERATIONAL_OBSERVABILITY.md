# Phase 9: Operational Observability and Incident Alerts

## Purpose

Phase 9 implements the Day 32 observability block in the bounded-autonomy roadmap.

It gives JobTomatik a durable, account-scoped reliability view across:

- discovery sources;
- ATS adapter outcomes;
- submission uncertainty;
- validation and navigation failures;
- login and MFA lockout risk;
- circuit-breaker state;
- application-material integrity review;
- routine operational activity.

Phase 9 is an evidence and notification layer only. It cannot enable live submission, promote adapter maturity, retry an application, answer an application question, or send recruiter outreach.

## Existing foundation reused

Phase 9 deliberately extends existing infrastructure rather than creating a parallel monitoring system.

It reuses:

- `AgentRun` as the durable discovery-run record;
- `Application` and `ManualReviewTask` as application/adapter incident evidence;
- `ApplicationMaterial.status` as the existing material-integrity verdict;
- `Notification` for user-scoped in-app alerts;
- `build_adapter_health_report` for existing adapter success/failure calculations;
- `evaluate_circuit_breaker_policy` for the authoritative clustered-failure breaker state;
- the existing hourly Celery task identity `app.tasks.operations.refresh_adapter_health_alerts`.

No database migration is required.

## Durable source diagnostics

`search_jobs_with_diagnostics` augments discovery with a bounded observation record for every independently executed source.

Each observation contains only:

- source name;
- source kind (`broad_board` or `public_ats`);
- success/failure status;
- result count;
- optional public ATS target identifier;
- bounded exception class name as `error_code`.

Raw exception messages are not persisted. Provider exceptions can contain request URLs or runtime detail, so Phase 9 stores the exception class only.

The compatibility `search_jobs` function remains available and still returns only jobs.

## Broad-board failure semantics

Some existing broad-board scraper functions intentionally catch provider/network errors and return an empty result, or development mock results when that explicit mode is enabled.

Phase 9 does not rewrite that scraper contract in the observability phase. Therefore:

- an exception that escapes the source boundary is recorded as a failed observation;
- a source that completes with zero rows is recorded as a successful zero-result observation;
- repeated successful zero-result observations generate `source_zero_results` degradation rather than being falsely classified as a transport outage.

This distinction keeps the reliability view truthful while leaving source-retry behavior for the dedicated recovery phase.

## Persistence

`run_job_search` writes source diagnostics into the existing discovery `AgentRun.result` JSON.

The persisted result also retains:

- `total_found`;
- `duplicates`;
- `new_candidates`;
- search origin (`interactive` or `scheduler`).

Source-health reports are reconstructed from those durable runs. A process restart or UI refresh therefore does not erase the observations used to calculate source reliability.

## Source health

For the selected reporting window, each observed source exposes:

- observation count;
- successful observations;
- failed observations;
- zero-result observations;
- total result count;
- success rate;
- consecutive failures;
- bounded error-code counts;
- latest observation time.

Alerts include:

### `source_breakage`

Critical when consecutive failures reach the configured failure threshold.

### `source_failure_spike`

Warning when failures in the reporting window reach the threshold without a current consecutive-failure streak.

### `source_zero_results`

Warning when at least the threshold number of successful observations all returned zero jobs.

A zero-result warning points to Scheduler Center so the user can verify keywords, location, and enabled sources. Breakage alerts point to Operational Reliability.

## Adapter and application incidents

Phase 9 retains the existing adapter-health calculations for:

- `submission_uncertain`;
- repeated failed applications;
- validation-failure spikes;
- adapter/control/navigation breakage;
- login or MFA lockout risk;
- low confirmation rate.

The combined observability layer adds affected application IDs when they can be deterministically linked to the alert and produces an application-specific recovery link when exactly one application is affected.

## Material integrity

Recent application materials already marked `needs_review` by the verified-material system become `material_integrity_review` incidents.

Phase 9 does not independently reinterpret or override Phase 3's evidence verdict. It surfaces the authoritative existing state and links the operator to the affected application or Evidence & Materials workspace.

## Circuit breaker visibility

The combined report calls the existing circuit-breaker evaluator. An active user-level clustered-failure breaker becomes a critical policy incident with the retained application IDs and a recovery path to Operations Center.

Observability does not close, reset, or bypass a circuit breaker.

## Notification policy

The hourly operations task now synchronizes the combined incident report.

The historical task name remains unchanged for runtime compatibility:

`app.tasks.operations.refresh_adapter_health_alerts`

The task now calls `sync_operational_notifications`.

### Incident deduplication

Incident notification fingerprints bind:

- incident kind;
- domain;
- entity/source/platform;
- reason code;
- severity.

The same incident is not re-emitted during the configured 24-hour dedupe window.

### Routine success digest

Scheduled discovery no longer emits a separate `new_match` notification for every successful scheduler cycle.

Instead, Phase 9 emits at most one operations digest per UTC calendar date when there is activity. The digest summarizes:

- new jobs saved;
- application attempts;
- confirmed applications;
- applications requiring review.

Interactive searches retain their immediate `new_match` notification because the user initiated that action and expects immediate feedback.

The digest is a once-per-UTC-day snapshot generated by the hourly observer, not a promise that it runs at the end of the day.

## API

Existing adapter-health endpoint remains:

- `GET /api/adapter-health`

Phase 9 adds under the same authenticated/account-scoped router:

- `GET /api/adapter-health/observability`
- `POST /api/adapter-health/observability/notifications/refresh`

The POST only materializes deduplicated notifications. It cannot retry tasks or mutate application, approval, adapter-maturity, or outreach state.

## Operational Reliability UI

The existing `/adapter-health` route becomes the broader **Operational Reliability** console.

It shows:

- jobs saved;
- application attempts;
- confirmations;
- manual-review count;
- source failures;
- active incident count;
- source-health table;
- adapter-performance table;
- incident severity and exact reason;
- affected application IDs;
- actionable recovery links;
- manual alert synchronization.

The screen explicitly states its non-consequential safety boundary.

## Safety invariants

Phase 9 does not modify:

- `ALLOW_REAL_APPLICATION_SUBMIT`;
- `ALLOW_REAL_FOLLOWUP_SEND`;
- `AUTOPILOT_ENABLED`;
- scheduler policy activation;
- adapter maturity;
- submission approvals;
- submission attempts;
- recruiter-follow-up approvals;
- selector execution permissions;
- Answer Policy Vault contents;
- CAPTCHA/MFA/login/identity/assessment boundaries;
- idempotency or confirmation-evidence requirements.

Operational reports have explicit invariants:

- `read_only_report=true`;
- `cannot_change_adapter_maturity=true`;
- `cannot_authorize_submission=true`;
- `cannot_send_recruiter_outreach=true`.

## Regression coverage

Phase 9 adds coverage for:

- independent source observations;
- source exceptions without exception-text leakage;
- consecutive source-breakage detection;
- repeated zero-result degradation;
- user/account isolation;
- incident notification deduplication;
- one digest per UTC day;
- material-integrity incidents;
- account-scoped observability API;
- non-consequential notification refresh;
- reliability-console sections and recovery links;
- explicit safety copy;
- scheduled-search origin tracking and notification-noise suppression.

## Validation requirement

The Phase 9 implementation is not complete until the exact PR head passes the affected backend, frontend, Android, migration, dependency, security, reproducible-verification, and stabilization release gates.

The implementation PR remains draft and unmerged after validation unless the repository owner explicitly requests merge.
