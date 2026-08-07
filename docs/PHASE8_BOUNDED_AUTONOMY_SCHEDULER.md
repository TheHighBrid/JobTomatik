# Phase 8: Bounded Autonomy Scheduler

## Purpose

Phase 8 turns JobTomatik's existing six-hour scheduled task into an explicit, inspectable bounded-autonomy scheduler.

It does not introduce a new submission mechanism or weaken the existing unattended worker. The scheduler decides what may be discovered and what may be considered for unattended application creation. The existing unattended policy gate and submission worker remain authoritative immediately before any browser execution.

## Routes

Frontend:

- `/scheduler`

Backend:

- `GET /api/scheduler/preview`
- `POST /api/scheduler/run`
- `GET /api/settings`
- `PATCH /api/settings`

All scheduler APIs are authenticated and account-scoped.

## Fail-safe defaults

New scheduler defaults are deliberately inert:

- `dry_run_mode=true`
- `auto_search_enabled=false`
- `auto_apply_enabled=false`
- minimum match score `0.65`
- daily application cap `5`
- weekly application cap `20`
- per-employer daily cap `1`
- quiet hours `00:00–06:00 UTC`
- no unattended platform opt-ins
- no employer allow/exclude entries
- no saved search keywords or location

The environment-backed `AUTOPILOT_ENABLED` gate also remains `false` by default.

`ALLOW_REAL_APPLICATION_SUBMIT` is not modified by Phase 8.

## Versioned policy activation

Historical JobTomatik builds exposed `auto_search_enabled=true`, `auto_apply_enabled=true`, and `dry_run_mode=false` as UI/API defaults. A value persisted by those builds is not reliable evidence that the account explicitly accepted the Phase 8 bounded-autonomy contract.

Phase 8 therefore requires the JSON marker:

`scheduler_policy_version = bounded-autonomy-v1`

Until that marker exists:

- effective scheduled discovery is forced off;
- effective autonomous candidate processing is forced off;
- effective dry-run mode is forced on;
- Scheduler Center reports `policy_upgrade_required`.

The marker is written only when a Phase 8 scheduler field is explicitly saved. On first activation, historical true switches are not resurrected unless those switches are present in the activating update. Editing a cap or constraint alone therefore activates the new contract with discovery/apply still off and dry run still on.

No schema migration is required because the marker lives in the existing `User.automation_settings` JSON object.

## Saved discovery policy

Scheduled discovery uses, in order:

1. explicit scheduler search keywords, or the user's saved preferred titles/skills;
2. an explicit scheduler location, or the user's first saved preferred location;
3. explicitly selected supported sources plus any verified ATS targets in the user's job preferences.

If keywords or location are unavailable, discovery fails closed with an explicit configuration blocker.

Phase 8 removes the prior scheduler fallback that invented generic AML/KYC/fraud search terms and an Ottawa location. The scheduler no longer creates a search identity that the account did not provide.

## Application policy

The Scheduler Center exposes the policy vocabulary already enforced by the unattended gate:

- minimum match score;
- daily application cap;
- weekly application cap;
- daily per-employer cap;
- UTC quiet hours;
- employer allow list;
- employer exclude list;
- allowed locations;
- minimum salary;
- allowed seniority;
- allowed languages;
- explicit per-platform unattended opt-in.

Employer allow/exclude overlap is rejected. Weekly caps cannot be lower than daily caps. Supported sources and platforms are validated before saving.

Partial settings updates are validated against the saved scheduler state whenever a cross-field invariant changes. Unrelated legacy settings remain editable instead of being retroactively rejected.

Legacy comma-separated scheduler lists are normalized on read, and the Settings API exposes the same environment-backed cap and quiet-hour defaults used by the runtime policy engine.

## Adapter maturity boundary

Per-platform opt-in is necessary but never sufficient.

`evaluate_unattended_job_policy` reads the live canonical ATS certification manifest and requires:

`certified_autonomous`

Anything else fails closed, including:

- `unsupported`
- `detect_only`
- `dry_run`
- `human_reviewed_submit`
- missing or malformed maturity

At the time Phase 8 was implemented, the repository's canonical adapters remain below `certified_autonomous`, so policy preview should expose zero autonomous application candidates unless a later, separately reviewed maturity promotion changes the live manifest.

Phase 8 does not promote any adapter.

## Candidate priority

Queued jobs above the configured minimum match score are ranked deterministically.

Base priority:

- relevance score converted to a 0–100 base.

Closing-date urgency boost:

- <= 1 day: +18
- <= 3 days: +12
- <= 7 days: +7
- <= 14 days: +3
- expired posting: blocked with `posting_deadline_passed`

Supported deadline fields are:

- `closing_date`
- `application_deadline`
- `deadline`
- `expires_at`

The preview shows both the priority evidence and the exact policy decision for every displayed candidate.

## Discovery versus application caps

Daily and weekly application caps stop application creation, not discovery.

If the only user-policy blocker is `application_cap_reached`, a configured discovery cycle may still run. This keeps JobTomatik aware of newly posted roles while respecting the application limit.

Quiet hours, the global kill switch, global autopilot disablement, and active circuit breakers still stop scheduled work as applicable.

## Scheduler cycle

The existing six-hour Celery beat continues to call:

`app.tasks.scraping.daily_auto_search_all`

Phase 8 routes each account through the shared bounded scheduler cycle.

A user-specific manual cycle is also available through:

`app.tasks.scraping.run_user_scheduler_cycle`

The API `POST /api/scheduler/run` queues only the authenticated user's cycle and refuses to dispatch when no action is policy-ready.

A cycle may:

- queue source discovery when the saved search plan is complete;
- inspect queued candidates through the unattended policy;
- create an application only for a policy-allowed candidate;
- prepare verified materials;
- queue the existing unattended worker.

Newly discovered jobs are processed on a later scheduler cycle rather than racing the asynchronous discovery task in the same cycle.

## Double policy check

The scheduler policy is not final submission authority.

Before application creation, Phase 8 evaluates the live unattended job policy, including live adapter maturity.

Immediately before browser execution, `submit_unattended_application_task` evaluates the same unattended policy again.

A maturity downgrade, circuit breaker, changed account policy, platform disablement, cap, or other blocker that appears after scheduling therefore stops execution at the worker chokepoint.

## Dry-run precedence

For scheduled application attempts:

`effective_dry_run = user_dry_run_mode OR NOT ALLOW_REAL_APPLICATION_SUBMIT`

Therefore:

- a user-selected dry run cannot be overridden by enabling the server's real-submit flag;
- disabling dry run in the account still does not enable real submission while the server gate is off;
- live adapter maturity and all worker safety checks still apply after both conditions.

## Existing safety boundaries preserved

Phase 8 does not change:

- `ALLOW_REAL_APPLICATION_SUBMIT`;
- `ALLOW_REAL_FOLLOWUP_SEND`;
- `AUTOPILOT_ENABLED` default;
- adapter maturity;
- supervised approval semantics;
- idempotency and duplicate-submission protection;
- confirmation-evidence requirements;
- Answer Policy Vault rules;
- CAPTCHA, anti-bot, MFA, login, identity, or assessment handoffs;
- selector execution permissions;
- recruiter-outreach approval.

Work authorization and sensitive/legal answer truth remain owned by the Answer Policy Vault and downstream application gates. The scheduler does not infer those answers from résumé or job text.

## Storage and migration

No new table or database column is introduced.

Phase 8 uses the existing `User.automation_settings` JSON field for scheduler policy and the existing Job/Application records for candidate and cap evaluation.

No Alembic revision is required.

## Scheduler Center

The new mobile-friendly Scheduler Center exposes:

- scheduler and environment state;
- explicit safety boundary;
- saved discovery policy;
- caps and quiet hours;
- employer/job constraints;
- per-platform opt-in plus live maturity;
- current account-policy verdict;
- candidate priority and exact block reason;
- preview refresh;
- bounded account-scoped manual cycle dispatch.

The general Settings page now links to Scheduler Center instead of maintaining a second competing Auto-Pilot configuration surface.

## Regression coverage

Phase 8 adds regression coverage for:

- fail-safe scheduler defaults;
- legacy true flags remaining inert before versioned policy activation;
- first activation not resurrecting historical scheduler switches;
- unsupported source rejection;
- partial-update cap validation against saved settings;
- allow/exclude conflict validation against saved settings;
- missing search identity failing closed without invented values;
- profile-owned search fallback;
- closing-date priority;
- global autopilot blocking manual dispatch;
- incomplete discovery configuration not dispatching search;
- application caps blocking apply but not discovery;
- candidate preview remaining read-only;
- Scheduler Center routing/navigation;
- full policy-control visibility;
- explicit non-submission safety copy;
- separate preview and bounded-run API actions.

## Validation

Phase 8 must pass the repository's normal affected release matrix before it is considered complete. The implementation PR remains draft and unmerged until exact-head CI is green.
