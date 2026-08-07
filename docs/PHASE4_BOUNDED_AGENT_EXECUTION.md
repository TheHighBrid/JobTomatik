# Phase 4: Bounded Agent Execution

## Purpose

Phase 4 turns JobTomatik's inspectable `AgentRun` and `AgentTask` plans into dependency-aware Celery work without granting the orchestration layer permission to perform consequential external actions.

The control plane can prepare and inspect. It cannot submit an application, send recruiter outreach, negotiate, accept an offer, bypass authentication, or manufacture evidence.

## Design boundary

Bounded execution is intentionally separate from JobTomatik's submission engine.

Approval phrase:

```text
APPROVE BOUNDED RUN <run_id>
```

That approval authorizes only the scope recorded as:

```text
bounded_local_execution
```

Every execution snapshot explicitly retains:

```json
{
  "submission_authorized": false,
  "outreach_authorized": false
}
```

A bounded-run approval is not a supervised-submission approval, applicant consent, adapter certification, or permission to send a message. Existing submission approvals, platform maturity, unattended policy, idempotency, handoff, and confirmation-evidence gates remain authoritative.

## Durable state

Phase 4 reuses existing columns rather than introducing a migration:

- `AgentRun.run_context.execution_control` stores approval, pause, resume, cancellation, scope, and operator provenance.
- `AgentTask.status` records `pending`, `queued`, `running`, `blocked`, `completed`, `failed`, or `skipped`.
- `AgentTask.task_input` retains bounded inputs.
- `AgentTask.task_output.execution` stores Celery IDs, claim timestamps, lease expiry, handler version, attempt number, failure class, and retryability.
- `attempt_count` and `max_attempts` enforce hard retry limits.
- `AgentRun.result` receives the final task ledger.

No browser credential, approval secret, applicant answer, or résumé file is copied into orchestration output.

## Dependency execution

Tasks are released in waves:

1. The dispatcher locks the run.
2. Pending tasks are checked against plan dependencies.
3. Only tasks whose dependencies are complete or intentionally skipped become `queued`.
4. A worker claims a queued task under a bounded lease.
5. Duplicate workers observe the live lease and do not execute the same task concurrently.
6. Completion triggers another dispatch pass.
7. A blocked or failed dependency causes downstream tasks to be skipped with explicit dependency evidence.

Run status is derived from task status, except when an operator pause or cancellation is authoritative.

## Bounded handlers

### Discovery

Requires explicit `search_params` and keywords. It uses the existing public discovery pipeline, deterministic scoring, evaluation persistence, knowledge graph, and memory matching. Phase 4 reuses the parent AgentRun instead of creating a nested discovery run.

### Deduplication

Summarizes duplicate, saved, and blocked counts from the completed discovery output.

### Company research

Reads retained Job and Knowledge Graph records. It does not perform an open-ended external crawl.

### Evaluation

Reads a source-backed `OpportunityEvaluation`, or summarizes the evaluation output already created during discovery.

### Tailoring

Generates versioned verified cover-letter and résumé-summary materials using the Evidence Ledger. Materials with warnings become blocked for review.

### Application

Performs readiness preflight only. It checks:

- user-owned application and job context;
- employer application target;
- open manual reviews;
- latest verified cover letter;
- latest verified résumé summary;
- optional selector-health requirements.

Its output always records:

```json
{
  "submission_attempted": false,
  "submission_authorized": false
}
```

It never calls the application submission task.

### Recruiter CRM

Reads relationship state and due follow-ups. It records `messages_sent: 0` and `outreach_authorized: false`.

### Interview intelligence and coaching

Ranks active evidence units against the role and creates evidence-linked practice questions. It does not invent candidate stories or answers.

### Offer intelligence

Compares retained offer and job salary fields. It never sends negotiation language or accepts/declines an offer.

### Memory

Persists only a user-requested `verified_outcome` containing exact content and `source_ref`. Ordinary generated task output is not promoted into memory.

## Selector circuits

Selector diagnostics expose per-account:

- confidence;
- successful and failed outcomes;
- calculated health;
- healthy, degraded, critical, or open circuit state;
- last failure reason;
- explicit operator disable/enable state.

Application readiness can specify selector requirements in `run_context.selector_requirements`:

```json
[
  {
    "platform": "lever",
    "page_signature": "application-v1",
    "intent": "continue",
    "min_health": 0.65
  }
]
```

Missing, disabled, or unhealthy selectors block readiness. The execution layer does not silently substitute an unverified selector.

## API

Run control:

- `GET /api/intelligence/agent-runs/{run_id}/execution`
- `POST /api/intelligence/agent-runs/{run_id}/approve`
- `POST /api/intelligence/agent-runs/{run_id}/reject`
- `POST /api/intelligence/agent-runs/{run_id}/dispatch`
- `POST /api/intelligence/agent-runs/{run_id}/pause`
- `POST /api/intelligence/agent-runs/{run_id}/resume`
- `POST /api/intelligence/agent-runs/{run_id}/cancel`

Selector control:

- `GET /api/intelligence/selectors`
- `PATCH /api/intelligence/selectors/{strategy_id}/control`

All routes are user-scoped. Cross-account IDs return 404.

## Execution Center

The new `/execution` workspace provides:

- recent-run selection;
- exact-phrase bounded approval;
- dispatch, pause, resume, and cancellation controls;
- polling for active runs;
- task dependency timeline;
- attempt and error inspection;
- compact retained output inspection;
- selector circuit diagnostics and operator control;
- a persistent hard-boundary notice.

Planning remains in Command Center. Execution remains in Execution Center.

## Failure and recovery

Worker exceptions are classified separately from expected business blockers.

- Expected missing evidence or readiness conditions become `blocked` and notify the user.
- Unexpected worker exceptions retry only while `attempt_count < max_attempts`.
- Exhausted tasks become `failed`.
- A live task lease rejects duplicate claims.
- Enqueue failures return the task to `pending` with dispatch evidence.
- Pause prevents new claims.
- Cancellation skips pending/queued/blocked work and leaves running workers unable to release new tasks.

## Safety invariants

Phase 4 does not change:

- `ALLOW_REAL_APPLICATION_SUBMIT`;
- adapter maturity;
- platform supervised-pilot flags;
- CAPTCHA/MFA/login policy;
- applicant answer policy;
- application idempotency;
- submission evidence requirements;
- independent confirmation review;
- unattended execution policy.

No Phase 4 handler imports or calls the application submit task.

## Validation plan

Regression coverage verifies:

- exact approval phrase and bounded scope;
- approval cannot authorize submission or outreach;
- user ownership for runs and selectors;
- dependency-order dispatch;
- duplicate claim rejection;
- bounded attempts;
- downstream skipping after a blocked dependency;
- application preflight makes no submission attempt;
- selector circuit controls are account-scoped;
- discovery can reuse a parent run;
- task registration through the existing operations worker include;
- frontend route and production build;
- unchanged migration and release gates.
