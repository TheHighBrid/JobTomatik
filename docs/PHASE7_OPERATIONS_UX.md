# Phase 7: Operations UX

## Purpose

Phase 7 turns the existing JobTomatik v2 records into one operational workspace without creating a new execution authority.

The Operations Center is a read-heavy, mobile-first view over existing application, recruiter, evaluation, career-memory, knowledge, and selector data. It may correct user-owned career-memory records, but it cannot submit applications, approve submissions, send recruiter outreach, promote adapter maturity, or bypass human/security boundaries.

## Route

Frontend:

- `/operations`

Backend:

- `GET /api/operations/workspace`
- `PATCH /api/operations/memories/{memory_id}`
- `GET /api/operations/knowledge/edges`

All backend routes are authenticated and account-scoped.

## Workspace snapshot

`GET /api/operations/workspace` builds a deterministic snapshot from authoritative existing tables.

### Pipeline board

Applications are grouped into the existing JobTomatik states:

- pending
- applying
- applied
- interviewing
- offer
- rejected
- withdrawn

Each card shows the application/job identity, automation state, target status, dated progress, open-review count, active follow-up count, and latest application event.

The board does not introduce a second application status. Application state remains owned by `Application.status` and `Application.automation_state`.

### Daily agenda

The agenda combines:

- scheduled interviews;
- recruiter CRM follow-up dates;
- supervised follow-up drafts and approved deliveries;
- open/in-progress manual review tasks.

The default window is 14 days. Overdue items remain visible instead of silently disappearing.

Agenda actions only route to the existing authoritative review surfaces. An approved recruiter follow-up still requires the Phase 6 exact-payload approval and delivery gate.

### Unified timeline

The timeline merges two user-owned evidence streams:

- `ApplicationEvent` records;
- `RecruiterInteraction` records.

Application-event payload JSON is deliberately not exposed by the Operations Center snapshot. The timeline returns normalized event type, state transition, company/application identifiers, and timestamps. Recruiter interactions expose their existing user-owned summary.

### Evaluation comparison

The comparison view uses the latest `OpportunityEvaluation` for each application/job identity and displays:

- weighted score;
- recommendation;
- legitimacy status;
- hard blockers;
- per-dimension scores.

Legitimacy and hard blockers remain separate from the weighted score. A high numeric score cannot erase a blocker.

## Career-memory review and correction

`PATCH /api/operations/memories/{memory_id}` allows the owner to change:

- content;
- confidence;
- active/inactive state.

Changing content or confidence:

1. appends the prior content, confidence, source, source reference, and correction timestamp to a bounded `correction_history` in `memory_metadata`;
2. marks `corrected_by_user=true`;
3. changes the current source to `user_correction`.

Only the most recent 20 correction-history entries are retained. Toggling active/inactive state alone does not rewrite provenance.

Cross-account memory IDs return 404.

## Knowledge explorer

The existing node API remains authoritative for nodes. Phase 7 adds a read-only, account-scoped edge list at:

`GET /api/operations/knowledge/edges`

The UI can search/filter nodes and inspect inbound/outbound evidence relationships without adding graph mutation behavior to the Operations Center.

## Selector diagnostics

The Selector Health view consumes the existing selector-diagnostics API and orders strategies by health. It displays:

- platform;
- semantic intent;
- page signature;
- selector;
- health score;
- success/failure counts;
- last failure time and reason;
- disabled state.

Control changes remain in Execution Center. Operations Center does not enable, disable, generate, or promote selector strategies.

## Storage and migration

Phase 7 adds no database tables or columns.

It reuses:

- `Application`
- `ApplicationEvent`
- `ManualReviewTask`
- `FollowUp`
- `RecruiterContact`
- `RecruiterInteraction`
- `OpportunityEvaluation`
- `CareerMemory`
- `KnowledgeNode`
- `KnowledgeEdge`
- `SelectorStrategy`

No Alembic revision is required.

## Safety invariants

Phase 7 does not change:

- `ALLOW_REAL_APPLICATION_SUBMIT`;
- `ALLOW_REAL_FOLLOWUP_SEND`;
- submission approvals or attempts;
- recruiter follow-up approvals;
- final-submit confirmation evidence;
- adapter maturity;
- selector execution permissions;
- CAPTCHA, MFA, login, identity, anti-bot, or assessment policy;
- bounded AgentRun execution approval;
- application idempotency or duplicate protection.

The UI explicitly states that Operations Center does not grant application-submission or recruiter-outreach permission.

## Regression coverage

Backend coverage verifies:

- pipeline, timeline, agenda, and evaluation snapshot composition;
- application/recruiter timeline normalization;
- account isolation across application and recruiter records;
- memory-correction provenance history;
- cross-account memory correction rejection;
- account-scoped knowledge-edge reads.

Frontend source-contract coverage verifies:

- all seven Phase 7 views remain present;
- the non-consequential safety statement remains visible;
- workspace, correction, and graph APIs remain separate;
- `/operations` remains routed from primary navigation.
