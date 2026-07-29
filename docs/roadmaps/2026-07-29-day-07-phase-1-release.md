# Day 7 Phase 1 Release Audit

## Decision

Phase 1 is ready to close only after this change passes the exact-head release matrix.

The control plane built during Days 1–6 is present on `main`: clean reproduction, canonical application states, evidence-gated terminal outcomes, answer-policy trust, duplicate prevention, secure handoffs, kill switches, and clustered-failure circuit breakers.

This audit does **not** authorize autonomous or real submission. It establishes a stable launchpad for collecting Lever Phase A evidence under rules that cannot move silently during Phase 2.

## Completed Phase 1 controls

| Day | Control domain | Evidence |
|---|---|---|
| 1 | Truthful baseline and campaign control | Day 1 baseline snapshot |
| 2 | Clean, one-command reproduction | PR #155 |
| 3 | Canonical state transitions and crash recovery | PR #156 |
| 4 | Answer Policy Vault trust and blockers | PR #157 |
| 5 | Submission identity, idempotency, and replay resistance | PR #158 |
| 6 | Kill switches, target-bound handoffs, and circuit breakers | PR #160 |

PR #159 is a load-bearing corrective change. It hardened readiness calculations and corrected Lever Phase A from the earlier 2/30 interpretation to the current truthful value of **0/30 qualifying dry runs**.

## Phase 1 gate

The release gate requires all of the following on one exact PR head:

- full backend and browser suite;
- clean migration smoke test;
- frontend production build and runtime regressions;
- Android lint, assembly, identity, and version verification;
- deployment configuration and fail-safe default verification;
- CodeQL security analysis;
- reproducible verification aggregate release gate;
- post-merge stabilization aggregate release gate;
- Lever Phase A evidence certification;
- dedicated Phase 1 contract checks.

Required observed safety results:

```text
false_submitted_records=0
duplicate_terminal_submissions=0
unsafe_handoff_resumes=0
adapter_promotions=0
live_submissions=0
```

## Current adapter state

| Adapter | Maturity |
|---|---|
| Greenhouse | `dry_run` |
| Lever | `dry_run` |
| Ashby | `dry_run` |
| SmartRecruiters | `detect_only` |
| Workday | `detect_only` |

There are currently no `certified_autonomous` adapters.

## Lever Phase 2 starting line

Phase 2 starts from:

- **0/30 qualifying Lever Phase A dry runs**;
- two retained CAPTCHA/manual-boundary rows that remain auditable but receive no quota credit;
- **0/10** independently reviewed supervised Lever submissions;
- Lever maturity `dry_run`;
- real submission, autopilot, and resumable live handoffs disabled.

The frozen measurement contract is recorded in:

- `docs/operations/lever-phase-2-measurement-freeze.json`
- `docs/operations/lever-phase-2-measurement-freeze.md`

Issue #161 is the exact Days 8–14 evidence queue. Issue #86 remains the broader Lever platform and pilot tracker.

## Backlog surgery

The audit did not close open issues merely to improve a dashboard count.

- #13 stays open as the master product roadmap.
- #154 stays open as the 42-day execution tracker.
- #86 stays open as the complete Lever evidence, supervised-pilot, and promotion tracker.
- #161 is the new bounded Phase 2 collection queue.
- PR #152 is treated as merged historical evidence, not an active draft or promotion gate.
- PR #150 remains correctly archived as superseded by merged PR #151.
- PRs #155–#160 remain immutable Phase 1 implementation evidence.

The machine-readable surgery ledger is `docs/roadmaps/2026-07-29-day-07-backlog-surgery.json`.

## Unresolved risks

### R1: Lever Phase A evidence gap

Lever has zero qualifying records under the hardened contract. Thirty distinct qualifying dry runs remain before Phase A can complete.

### R2: Lever supervised evidence gap

There are zero independently reviewed confirmed real Lever submissions. Phase B remains entirely ahead and user-gated.

### R3: No autonomous adapter

No adapter has reached `certified_autonomous`. Unattended final submission therefore remains blocked by canonical maturity.

### R4: Truthful user boundaries remain

Real-job selection and approval, sensitive or legal policy changes, CAPTCHA, MFA, assessments, identity verification, private credentials, and adapter promotion remain explicit user boundaries.

### R5: Environment-specific coverage

Some browser or device tests are skipped when their required environment is absent. Dedicated Chromium, Android, migration, and release workflows remain mandatory and are not replaced by generic unit coverage.

## Safety defaults

The release keeps these controls disabled:

```text
AUTOPILOT_ENABLED=false
ALLOW_REAL_APPLICATION_SUBMIT=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
LEVER_SUPERVISED_PILOT_ENABLED=false
ENABLE_RESUMABLE_HANDOFFS=false
```

`AUTOMATION_GLOBAL_KILL_SWITCH` remains available as an emergency stop and defaults inactive. Its inactive default is not an authorization to run automation; the independent execution gates above remain off.

## Next mission

Day 8 builds and locks the Lever target corpus: at least 40 reviewed active postings yielding at least 30 viable distinct Lever sites across global and EU hosts. No evidence run begins until the corpus and provenance manifest are reviewable.
