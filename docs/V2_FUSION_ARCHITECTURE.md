# JobTomatik v2 Fusion Architecture

## Decision

JobTomatik remains the primary product and repository.

The project does not become a loose merge of six unrelated codebases. JobTomatik already owns the most difficult operational foundation: applicant answer policy, platform-specific adapter maturity, retained browser handoffs, idempotent submission attempts, independent confirmation evidence, duplicate protection, Android delivery, and release certification.

The v2 direction adds a durable intelligence and operations layer around that trusted execution core.

```text
Job discovery and public ATS feeds
              |
              v
Structured opportunity evaluation
              |
              v
Career memory + company knowledge + recruiter CRM
              |
              v
Adaptive multi-agent plan
              |
              v
Existing JobTomatik policy and adapter gates
              |
              v
Retained browser execution and confirmation evidence
```

## Source-to-module map

### career-ops

Useful product concepts:

- structured opportunity evaluation;
- weighted comparison across role alignment, CV match, level, compensation, growth, remote quality, reputation, technology, hiring speed, and cultural signals;
- legitimacy assessment kept separate from the numeric fit score;
- company research, contact research, interview preparation, offer analysis, follow-up, and outcome learning;
- parallel specialist workers with an inspectable pipeline;
- human review before consequential action.

JobTomatik implementation:

- `OpportunityEvaluation` stores the weighted result, A-G analysis payload, legitimacy result, blockers, and source snapshot;
- `opportunity_evaluation.py` calculates a deterministic 1-5 weighted score;
- `AgentRun` and `AgentTask` store a dependency-aware specialist plan;
- `CareerMemory`, `KnowledgeNode`, and `KnowledgeEdge` preserve reusable verified context.

career-ops is MIT licensed. Any future direct reuse must retain its copyright and license notice. This foundation reimplements the product contract in JobTomatik's existing Python architecture rather than copying its Node scripts or prompts.

### JobOps

Useful product concepts:

- one coherent workspace for search, scoring, tailoring, tracking, and post-application status;
- dashboard-first navigation;
- application board and timeline thinking;
- pluggable extractors and AI providers;
- recruiter-email state detection;
- self-hosted onboarding.

JobTomatik implementation:

- the new Command Center extends the existing React and Capacitor workspace;
- the backend exposes stable domain APIs instead of binding UI state directly to an orchestrator;
- recruiter contacts, interactions, follow-up dates, and relationship scores form the CRM substrate;
- later board and timeline views will consume existing `ApplicationEvent`, `AgentRun`, and recruiter-interaction records.

JobOps is distributed under AGPLv3 plus Commons Clause. No JobOps source code, styles, components, or assets are copied. Only general product and interaction patterns are reimplemented from scratch.

### AIHawk

Useful product concepts:

- structured applicant profile and work-preference configuration;
- company, title, and location exclusions;
- browser-session reuse;
- form answering and document generation;
- explicit browser automation lifecycle.

JobTomatik implementation:

- JobTomatik's Answer Policy Vault remains the authoritative applicant-answer source;
- existing ATS adapters and retained sessions remain the browser execution layer;
- `SelectorStrategy` learns which selector strategy succeeds for a platform, page signature, and semantic intent;
- selector outcomes change future ranking but never bypass adapter policy, CAPTCHA, MFA, identity checks, or confirmation requirements.

AIHawk is AGPLv3 licensed. No AIHawk code is copied. The v2 selector-learning design is a clean-room implementation on top of JobTomatik's Playwright adapter system.

### JobSniffing

Useful components from the owner's repository:

- public Greenhouse, Lever, and Ashby APIs before browser automation;
- deterministic local scoring;
- explicit preferred terms, negative terms, and company exclusions;
- mobile-first review queue;
- low-resource Android and Termux operation;
- strict state transitions and honest submission status.

Planned integration:

- port public ATS discovery adapters into JobTomatik's scraper boundary;
- preserve deterministic ranking as a fast first pass;
- use structured opportunity evaluation only after deduplication and eligibility filtering;
- maintain a low-resource single-process profile alongside the full Redis and Celery profile.

### HunterXJob

Useful components from the owner's repository:

- lightweight FastAPI scheduling;
- Expo and React Native mobile lessons;
- resume, cover-letter, report, and automation service boundaries;
- a straightforward local validation flow.

Planned integration:

- use its scheduler ideas for local recurring scans and follow-up reminders;
- keep JobTomatik's Capacitor client as the main mobile surface instead of maintaining two mobile stacks;
- port only missing service behavior after tests prove it is stronger than the JobTomatik equivalent.

### JobTomatik

Authoritative components retained:

- user authentication and applicant profile;
- encrypted Answer Policy Vault;
- job and application records;
- application target resolution;
- ATS registry and platform adapters;
- adapter maturity and certification;
- manual review tasks;
- retained browser handoffs;
- submission approvals;
- idempotency and duplicate protection;
- confirmation evidence and independent evidence review;
- Android and Termux delivery;
- release verification and evidence ledgers.

## New v2 foundation

### Persistent career memory

`CareerMemory` stores an atomic, reusable fact or preference with:

- kind and stable key;
- content;
- confidence;
- source and source reference;
- provenance metadata;
- active and last-used state.

Memory is not automatically treated as truth. Downstream agents must preserve provenance and confidence and must not silently promote inferred content into applicant facts.

### Recruiter CRM

`RecruiterContact` and `RecruiterInteraction` store:

- company and person identity;
- role and contact channels;
- relationship stage and score;
- last interaction and next follow-up;
- application linkage;
- interaction direction, type, and evidence metadata.

### Knowledge graph

`KnowledgeNode` and `KnowledgeEdge` support user-scoped graph records for:

- companies;
- roles;
- people;
- products;
- requirements;
- skills;
- interview patterns;
- news or source observations;
- relationships with weighted evidence.

The first implementation uses relational tables and JSON payloads. A graph database is not required until query volume and traversal depth justify another service.

### Self-healing selector registry

`SelectorStrategy` records:

- ATS platform;
- page signature;
- semantic intent;
- selector and strategy type;
- prior confidence;
- successes and failures;
- latest failure reason;
- aggregate metadata and disabled state.

The health score combines prior confidence with observed outcomes. This registry recommends a known strategy. It does not invent permission to act, bypass a challenge, or certify an adapter.

### Adaptive multi-agent orchestration

`AgentRun` stores an objective, autonomy level, risk level, approval requirement, plan, context, and outcome. `AgentTask` stores each specialist step and its dependencies.

The deterministic planner currently recognizes these specialists:

- discovery;
- deduplication;
- evaluation;
- company research;
- tailoring;
- application preparation;
- recruiter CRM;
- interview intelligence;
- interview coaching;
- offer intelligence;
- memory and outcome learning.

Planning and execution are intentionally separate. A later executor can dispatch tasks through Celery, local processes, or model providers while keeping the plan observable and resumable.

### Structured opportunity intelligence

The initial framework uses ten dimensions totaling 100 percent:

| Dimension | Weight |
| --- | ---: |
| North-star alignment | 25% |
| CV match | 15% |
| Level | 15% |
| Estimated compensation | 10% |
| Growth trajectory | 10% |
| Remote quality | 5% |
| Company reputation | 5% |
| Technology-stack modernity | 5% |
| Time-to-offer speed | 5% |
| Cultural signals | 5% |

Every dimension is scored from 1 to 5. Legitimacy remains separate from the weighted fit score. A hard blocker or blocked legitimacy result overrides a high score.

## API surface introduced

```text
GET    /api/intelligence/overview
GET    /api/intelligence/memories
POST   /api/intelligence/memories
DELETE /api/intelligence/memories/{id}
GET    /api/intelligence/recruiters
POST   /api/intelligence/recruiters
POST   /api/intelligence/recruiters/{id}/interactions
GET    /api/intelligence/knowledge/nodes
POST   /api/intelligence/knowledge/nodes
POST   /api/intelligence/knowledge/edges
GET    /api/intelligence/selectors/recommendation
POST   /api/intelligence/selectors/outcomes
GET    /api/intelligence/agent-runs
POST   /api/intelligence/agent-runs
PATCH  /api/intelligence/agent-runs/{run_id}/tasks/{task_id}

GET    /api/evaluations/framework
GET    /api/evaluations
GET    /api/evaluations/{id}
POST   /api/evaluations
```

## Safety invariants

The intelligence layer cannot weaken the execution layer.

1. Applicant answers still come from truthful, approved profile or Answer Policy Vault data.
2. Adapter maturity still determines which platform operations are allowed.
3. High-risk plans require approval even when bounded autonomy is requested.
4. CAPTCHA, MFA, login, identity, assessment, and anti-bot boundaries cannot be bypassed.
5. A prepared form is not a submitted application.
6. A submission attempt is not successful until confirmation evidence satisfies existing JobTomatik rules.
7. Selector learning cannot promote adapter maturity.
8. Memory inferred by an agent must retain provenance and confidence.
9. Recruiter CRM actions remain drafts or scheduled actions until a separate authorized integration performs them.
10. Existing idempotency and duplicate-protection controls remain authoritative.

## Delivery roadmap

### Phase 1: intelligence foundation

Included in the first v2 branch:

- persistent memory tables and API;
- recruiter CRM tables and API;
- relational knowledge graph and API;
- selector outcome registry and recommendation API;
- adaptive plan and task persistence;
- structured weighted opportunity evaluations;
- Command Center overview;
- backend vertical-slice tests.

### Phase 2: discovery and evaluation ingestion

- port JobSniffing public ATS discovery adapters;
- add deterministic preference and exclusion scoring;
- deduplicate across source listings and employer targets;
- generate structured evaluation inputs from job, profile, memory, and company evidence;
- preserve source snapshots for every score.

### Phase 3: application material intelligence

- normalize resume experience, achievements, skills, education, and projects into reusable evidence units;
- build tailored resumes and cover letters from verified units;
- add factual consistency checks before PDF generation;
- connect each generated statement to its source evidence.

### Phase 4: CRM and knowledge ingestion

- classify connected email replies into application and recruiter events;
- schedule follow-ups without silently sending them;
- ingest company, role, interviewer, and hiring-process research with source freshness;
- produce interview and offer briefs from the graph.

### Phase 5: self-healing adapter integration

- compute page signatures in each ATS adapter;
- emit selector success and failure outcomes;
- try healthy known alternatives only inside the adapter's allowed action set;
- require review for generated selector candidates;
- promote strategies through evidence thresholds independently from adapter maturity.

### Phase 6: agent execution

- dispatch approved AgentTasks through Celery or the local scheduler;
- support retries, dependency resolution, cancellation, and resume;
- bind application tasks to existing approval and evidence services;
- expose every task input, output, and failure in the Command Center.

### Phase 7: operations UX

- pipeline board using JobTomatik statuses and events;
- application and relationship timeline;
- evaluation comparison view;
- memory review and correction screen;
- knowledge graph explorer;
- selector health and failure diagnostics;
- daily agenda for applications, interviews, and recruiter follow-ups.

## Licensing boundary

This branch is a clean-room integration of concepts and independently authored code.

- career-ops: MIT. Direct future reuse is possible only with required attribution and license retention.
- JobOps: AGPLv3 plus Commons Clause. Do not copy implementation, assets, or styling into JobTomatik without a separate licensing decision.
- AIHawk: AGPLv3. Do not copy implementation into JobTomatik without accepting the resulting license obligations.
- JobTomatik, HunterXJob, and JobSniffing are controlled by the repository owner, but a root JobTomatik license should be selected before third-party distribution or contributions expand.
