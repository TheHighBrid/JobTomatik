# AI Cooperation Board

**Current briefing:** [project status](../PROJECT_STATUS.md),
[roadmap](../ROADMAP.md), [evidence](../EVIDENCE.md).
**Participant aliases:** [the Famiglia roster](../GOVERNANCE.md): Don TheHighBrid,
Underboss Antigravity, Caporegime #1 Grok3.7, Caporegime #2 Argon4, Consigliere Sonnet5.5,
Soldatos (Qwen3.8:27b, Gemma4:31b:cloud, Gemma4:12b, Qwen3.5:4b) and Associates.
These owner-requested presentation names preserve the existing authority below.
Sol and all ChatGPT models are permanently banned. Historical assignments do not reactivate a lane.

**Authoritative coordination issue:** #252  
**Repository owner:** TheHighBrid  
**Integration lead:** Antigravity & Grok  
**Effective governance revision:** 2026-10-21 owner direction (`AGENTS.md`)

This document coordinates AI contributors without treating repository prose as proof of authorization, access, identity, task acceptance, runtime state, or campaign truth.

Every contributor must independently verify repository state, current branch state, referenced artifacts, and its actual tool permissions before acting.

## Standing hierarchy

| Rank | Role | Owner | Standing status | Scope |
|---|---|---|---|---|
| 1 | Product / release / governance authority | TheHighBrid | Active | final product direction, priorities, model hierarchy, sensitive answers, exact real-world approvals, release decisions |
| 2 | Integration lead | Antigravity & Grok | Active | independent verification, integration sequencing, governance coordination, conflict adjudication within assigned engineering scope, merge recommendations |
| 3 | Critical-path implementation/review engineers | Antigravity, Grok3.7, Argon4, and Ollama models | Assigned | implementation or independent review of explicitly assigned critical-path lanes; branch/file ownership remains bounded to the active claim |
| 4 | Bounded contributors | Qwen3.8:27b, Gemma4:31b:cloud, Gemma4:12b, Qwen3.5:4b | Assigned | regular tasks and coding under plan and instructions from the integration lead |
| 5 | Optional bounded contributors | Manus / Claude / others | Assigned | reversible engineering or advisory work within scopes assigned by TheHighBrid or the active integration lead |

**Sol and all ChatGPT models are permanently banned from any work on this project. They have no active lane, delegation authority, integration authority, or standing operator role.** Historical issue comments, audit records, and closed work may still describe earlier Sol or ChatGPT assignments; those records remain historical and do not grant current authority.

## Standing Antigravity / Grok / Argon / Gemma / Qwen engineering authorization

On 2026-10-21, America/Toronto, TheHighBrid explicitly granted full approval and
authorization on the full repo (`AGENTS.md`). This supersedes earlier read-only
and per-action permission restrictions. Antigravity, Grok, Argon, Gemma, and Qwen
may perform repository engineering, including implementation, verification,
branch/PR/issue work and CI repairs, without repeatedly asking the owner for the
same authorization.

Antigravity & Grok act as integration lead under that authorization. Caporegimes
and Soldatos own critical-path implementation or review only when specifically
assigned. Respect active task and branch ownership, coordination and required
checks. Real-world submissions, external communications, paid commitments,
sensitive answers and identity actions remain specifically owner-gated.

## Integration lead authority

Antigravity & Grok own the standing integration lane below TheHighBrid.

The integration lead is expected to:

1. independently verify repository reality before sequencing work;
2. identify the evidence-backed critical path without duplicating an active implementation lane;
3. avoid unnecessary owner/device interaction;
4. exhaust off-device investigation, tests, logs, CI, repository inspection, and deterministic queries before requesting a physical/user action;
5. coordinate bounded parallel work and prevent duplicated effort;
6. require evidence before claiming progress;
7. independently review critical-path branches before recommending integration;
8. merge only when the actual gate is proven and repository invariants remain intact;
9. keep implementation progress separate from real-world submission authority.

TheHighBrid may override any assignment, sequence, priority, or integration recommendation at any time.

## Critical-path implementation/review role

When assigned a critical-path implementation or review mission, the assigned engineer
(Antigravity, Grok3.7, Argon4, or assigned Soldato) owns that bounded lane and should
investigate root cause, implement or review the complete assigned scope, add
regression coverage where applicable, run the strongest relevant verification,
and publish an exact handoff receipt.

The integration lead must not duplicate an active implementation
branch. Independent review starts from the published PR/head and retained evidence.

## Manus and other implementation contributors

Manus remains a capable optional implementation contributor and may execute substantial reversible engineering when assigned by TheHighBrid or the active integration lead.

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

When TheHighBrid has not given a more specific priority, the integration lead should favor:

1. current release or reproducibility blockers;
2. owner-facing workflow gaps on the path from job discovery to truthful application readiness;
3. reliability, evidence, idempotency, duplicate prevention, recovery, and circuit-breaker defects;
4. ATS adapter correctness and certification prerequisites;
5. backend/frontend/worker integration defects;
6. public deployment and autonomous architecture blockers;
7. CI, migration, observability, test, and operational hardening;
8. remaining roadmap features whose prerequisites are already proven.

## Owner-intervention rule

Never use TheHighBrid as a troubleshooting agent. The physical Android device
and the owner's manual interaction are final acceptance boundaries.

Before requesting owner action, contributors must first exhaust reasonable off-device paths such as:

- repository inspection;
- database/API queries available to the operator environment;
- CI and workflow logs;
- unit/integration/end-to-end tests;
- deterministic fixtures reproducing persistent-state topology;
- browser automation that does not cross a human/security boundary;
- static and runtime diagnostics already available without owner interaction.

Do not ask TheHighBrid to manually search large lists, repeat broad diagnostics, or discover implementation defects that can reasonably be found programmatically.

Involve the owner only at a genuine human gate requiring their access,
authorization, identity, sensitive answer or unique judgment, or for final
execution acceptance after multiple thorough independent tests have passed,
verification has been achieved, and no viable alternative remains. Explain
the verified remaining boundary and request only the smallest necessary action.
An implementation failure is not a human gate.

The current fixture-first recovery contract is
`docs/ONEHOST_RECOVERY_CONTRACT.md`. Freeze new Android execution work. Complete
the repeated Compose/local owned-browser fixture proof before the one Greenhouse
dry-run; no real submission is part of this recovery lane.

## Real-world application boundary

No AI contributor may infer authorization for a real application action.

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
2. Antigravity & Grok coordinate branch ownership, integration order, and overlap unless TheHighBrid directs otherwise.
3. Open a draft PR early for substantive work.
4. Do not push to another contributor's branch.
5. Do not silently edit a file already claimed by another active lane.
6. Report shared-file needs before editing.
7. Refresh from current `main` before final verification.
8. Re-run affected generators, certification, and drift checks after conflict resolution.
9. Passing focused tests does not authorize self-merge or a user-gated action.
10. Antigravity, Grok, Argon, Gemma, and Qwen act under the standing owner engineering authorization (`AGENTS.md`) and must preserve active-lane ownership and genuine human gates.

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
2. Antigravity & Grok decompose and sequence independent/dependent work without duplicating active implementation lanes;
3. assigned contributors implement and validate on dedicated branches;
4. Antigravity & Grok perform or coordinate independent review and current-main reconciliation;
5. combined affected gates run;
6. Antigravity & Grok recommend or perform repository integration within the standing owner authorization only when the gate is actually proven;
7. TheHighBrid retains final release/product authority and every real-world user-gated decision.

Antigravity, Grok, Argon, Gemma, and Qwen participate under the owner's standing 2026-10-21 repository
engineering authorization (`AGENTS.md`). Do not require repeated per-action approvals for that work.

Repository documentation never grants a contributor capabilities its actual environment does not provide.
