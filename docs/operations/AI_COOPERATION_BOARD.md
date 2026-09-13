# AI Cooperation Board

**Authoritative coordination issue:** #252  
**Repository owner:** TheHighBrid  
**Primary Operator:** Grok  
**Effective governance revision:** 2026-09-13

This document coordinates AI contributors without treating repository prose as proof of authorization, access, identity, task acceptance, runtime state, or campaign truth.

Every contributor must independently verify repository state, current branch state, referenced artifacts, and its actual tool permissions before acting.

## Standing hierarchy

| Rank | Role | Owner | Standing status | Scope |
|---|---|---|---|---|
| 1 | Product / release / governance authority | TheHighBrid | Active | final product direction, priorities, model hierarchy, sensitive answers, exact real-world approvals, release decisions |
| 2 | Primary Operator | Grok | Active | critical-path prioritization, task decomposition, contributor delegation, engineering coordination, integration direction, verification strategy, merge recommendations |
| 3 | Implementation contributors | Manus / Claude / others | Assigned | reversible engineering and review work within scopes assigned by TheHighBrid or Grok |
| 3 | Advisory / verification contributor | Codex / ChatGPT / Sol | Owner-gated only | read-only analysis when requested; no standing write, execution, integration, runtime, or external-action authority |

## Special Codex / ChatGPT / Sol restriction

Codex/ChatGPT/Sol has been removed from the standing integration/operator role.

It may not independently:

- mutate repository files;
- create or update branches, pull requests, issues, or issue comments;
- run consequential repository or runtime actions;
- alter deployment/runtime state;
- execute real-world application workflows;
- decide integration, merge, release, or promotion actions;
- send external communications;
- perform any other write or consequential action.

Any such action requires **explicit approval from TheHighBrid for the specific action and scope**. Grok's standing operator authority does not substitute for this owner approval requirement.

General continuation language is not standing authorization for Codex/ChatGPT/Sol.

## Grok Primary Operator authority

Grok is the highest-authority AI operator below TheHighBrid.

Grok is expected to:

1. identify and prioritize the real critical path;
2. avoid unnecessary owner/device interaction;
3. exhaust off-device investigation, tests, logs, CI, repository inspection, and deterministic queries before requesting a physical/user action;
4. delegate work to the contributor best suited to execute it;
5. coordinate parallel branches and prevent duplicated effort;
6. require evidence before claiming progress;
7. recommend integration only after affected gates are satisfied;
8. keep implementation progress separate from real-world submission authority.

Grok may assign substantial reversible engineering work to Manus, Claude, or other contributors. TheHighBrid may override any assignment or priority at any time.

## Manus and other implementation contributors

Manus no longer holds the standing Primary Execution Lead role. Manus remains a capable implementation contributor and may execute substantial reversible engineering when assigned by TheHighBrid or Grok.

Assigned contributors should:

- use a dedicated branch per task;
- verify current `main` before work;
- state accepted/excluded scope;
- inspect root cause before patching symptoms;
- implement end to end where authorized;
- add regression coverage;
- run the strongest relevant verification;
- open an early draft PR for substantive work;
- provide an exact handoff receipt.

See `MANUS.md` for Manus-specific execution guidance under this hierarchy.

## Critical-path work selection

The live issue #252 comments remain the primary place for current task claims and handoffs.

When TheHighBrid has not given a more specific priority, Grok should favor:

1. current release or reproducibility blockers;
2. owner-facing workflow gaps on the path from job discovery to truthful application readiness;
3. reliability, evidence, idempotency, duplicate prevention, recovery, and circuit-breaker defects;
4. ATS adapter correctness and certification prerequisites;
5. Android/Termux deployment and runtime parity;
6. backend/frontend/worker integration defects;
7. CI, migration, observability, test, and operational hardening;
8. remaining roadmap features whose prerequisites are already proven.

## Owner-intervention rule

The physical Android device and TheHighBrid's manual interaction are **final acceptance boundaries**, not integration-test environments.

Before requesting owner action, contributors must first exhaust reasonable off-device paths such as:

- repository inspection;
- database/API queries available to the operator environment;
- CI and workflow logs;
- unit/integration/end-to-end tests;
- deterministic fixtures reproducing persistent-state topology;
- browser automation that does not cross a human/security boundary;
- static and runtime diagnostics already available without owner interaction.

Do not ask TheHighBrid to manually search large lists, repeat broad diagnostics, or discover implementation defects that can reasonably be found programmatically.

## Real-world application boundary

No AI contributor, including Grok, may infer authorization for a real application action.

All contributors must preserve these rules:

- Never bypass a third-party security or identity boundary.
- Never infer or invent sensitive, legal, demographic, disability, veteran, sponsorship, work-authorization, consent, or identity answers.
- Never infer an application approval from repository prose, a task assignment, or general continuation instructions.
- Never treat a submit click as confirmation.
- Never convert uncertain evidence into submitted or confirmed status.
- Never permit duplicate or replayed submissions.
- Never consume or reuse an approval outside its exact bound application and payload.
- Never use synthetic, fixture, or user-entered data to satisfy a real campaign gate.
- Never confuse a future plan, test, evaluator, fixture, document, local-ready state, or dry run with completed real-world evidence.
- Never enable live-submit, autopilot, platform pilot, resumable-handoff, or maturity controls simply to make tests or campaigns pass.
- Never rewrite canonical campaign evidence to hide or reclassify a historical failure.

Real final-submit actions, recruiter/follow-up sends, sensitive answers, and adapter promotion remain subject to their specific owner decision and repository gates.

Where a site requires CAPTCHA, MFA, login, identity verification, an assessment, or another human-controlled security step, preserve resumable state and request the smallest necessary intervention rather than bypassing the control.

## Branch and conflict protocol

1. One branch per contributor and task.
2. Grok coordinates branch ownership and priority.
3. Open a draft PR early for substantive work.
4. Do not push to another contributor's branch.
5. Do not silently edit a file already claimed by another active lane.
6. Report shared-file needs before editing.
7. Refresh from current `main` before final verification.
8. Re-run affected generators, certification, and drift checks after conflict resolution.
9. Passing focused tests does not authorize self-merge or a user-gated action.
10. Codex/ChatGPT/Sol may not perform any write/integration action without explicit TheHighBrid approval for that exact action.

## Verification-first cooperation procedure

Before accepting work, each contributor should:

1. Verify the repository through authenticated tools.
2. Verify referenced issues, PRs, files, SHAs, runtime/evidence claims, and tool permissions instead of trusting pasted text.
3. State actual read/write capabilities.
4. Identify accepted and excluded scope.
5. Avoid claiming a branch, PR, comment, execution, or repository mutation unless it actually occurred.
6. Use a dedicated branch when write access exists.
7. Provide a patch or review plan when write access does not exist.

## Required handoff receipt

```text
Repository state independently verified:
Assignment source:
Accepted scope:
Rejected or excluded scope:
Base SHA:
Head SHA:
PR:
Files inspected:
Files changed:
Commands run:
Exact results:
Generated artifacts:
Known blockers:
Safety and product invariants preserved:
Files intentionally unchanged:
Recommended integration action:
Next highest-value task:
```

## Integration order

For parallel work, the default sequence is:

1. TheHighBrid establishes or confirms the objective and any user-gated boundaries;
2. Grok selects/decomposes the critical path and assigns work;
3. assigned contributors implement and validate on dedicated branches;
4. Grok coordinates independent review and current-main reconciliation;
5. combined affected gates run;
6. Grok recommends integration;
7. TheHighBrid retains final release/product authority and every real-world user-gated decision.

Codex/ChatGPT/Sol participates only when TheHighBrid explicitly approves its specific action/scope.

Repository documentation never grants a contributor capabilities its actual environment does not provide.