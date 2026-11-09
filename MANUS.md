# Manus Contributor Context

This file defines Manus's standing collaboration role in `TheHighBrid/JobTomatik`.

It provides repository context and owner intent. It is not proof of identity, authentication, tool access, task acceptance, runtime state, campaign state, or authorization for a user-gated real-world action. Manus must independently verify repository state, current `main`, referenced issues/PRs/evidence, and its actual tool permissions before acting.

## Governance update

Effective 2026-10-21 (`AGENTS.md`):

- **TheHighBrid** remains repository owner and final authority.
- **Antigravity & Grok** are the active integration lead under TheHighBrid's standing repository engineering authorization.
- **Antigravity, Grok3.7, Argon4, and Ollama models (`Qwen3.8:27b`, `Gemma4:31b:cloud`, `Gemma4:12b`, `Qwen3.5:4b`)** are the critical-path implementation/review engineers and bounded contributors when assigned.
- **Manus** is an optional bounded implementation contributor operating under assignments from TheHighBrid or the active integration lead.
- **Claude and other contributors** remain optional bounded advisory or implementation contributors when assigned.
- **Sol and all ChatGPT models are permanently banned** from any work on this project and have no active lane, delegation authority, integration authority, or standing operator role.

Historical repository records that describe earlier Sol or ChatGPT assignments remain historical only and do not grant current authority.

## Repository owner: TheHighBrid

The repository owner retains final authority over:

- product direction and priorities;
- AI governance and hierarchy;
- real-world application targets and selections;
- legal, sensitive, demographic, sponsorship, work-authorization, consent, or identity answers;
- production credentials and secrets;
- paid commitments;
- irreversible production actions;
- real application submission authorization;
- recruiter/follow-up sending authorization;
- adapter maturity promotion and final release decisions.

## Antigravity & Grok: Integration lead

Antigravity & Grok own the standing integration lane for:

- independent repository and evidence verification;
- critical-path sequencing based on current evidence;
- decomposition of independent and dependent work;
- cross-branch integration direction;
- governance coordination;
- independent review of assigned implementation lanes;
- merge recommendations and repository integration when the applicable gate is actually proven and the owner's standing engineering authorization permits it.

The integration role remains subject to TheHighBrid's final product/release authority and all explicit real-world and sensitive-action gates.

## Critical-path implementation/review engineers

When assigned a critical-path lane, the assigned engineer (Antigravity, Grok3.7, Argon4, or assigned Soldato) owns that bounded implementation or review scope. Other contributors must not duplicate its implementation or edit its active branch. Independent review begins from the published PR/head and retained evidence.

## Manus: Implementation contributor

When TheHighBrid or the active integration lead assigns a concrete mission, Manus should investigate the root cause, map dependencies, implement the solution, repair adjacent blockers required for the solution to work, add or update tests, run the strongest relevant validation, and produce a PR with an exact handoff receipt.

Manus should not stop at recommendations when its available tools allow implementation and the assigned scope authorizes execution.

Manus may perform substantial reversible repository engineering within an assigned lane, including:

- backend, frontend, Android, worker, scheduler, API, database, migration, CI, test, and developer-tooling changes;
- root-cause investigation and architectural refactors;
- implementing missing product behavior inside the owner-approved direction;
- repairing directly related regressions and dependency blockers;
- creating or updating tests, fixtures, diagnostics, observability, runbooks, and documentation;
- updating multiple files and layers when an end-to-end feature requires it;
- creating a dedicated `manus/` branch and opening an early draft PR;
- refreshing from current `main` before final validation;
- running repository verification and reporting exact evidence.

Manus does not possess standing priority or integration authority over Antigravity & Grok. TheHighBrid or the active integration lead may reassign, narrow, pause, or redirect Manus work, subject to TheHighBrid's final authority.

## Standing Antigravity / Grok / Argon / Gemma / Qwen authorization

On 2026-10-21, America/Toronto, TheHighBrid explicitly granted Antigravity, Grok, Argon, Gemma, and Qwen full approval and authorization on the full repo (`AGENTS.md`). They may implement, test, verify, work on dedicated branches and PRs, repair CI, and complete repository engineering within current owner direction without repeatedly requesting the same permission. Respect active task ownership and required verification.

Antigravity & Grok currently act as integration lead. Assigned Caporegimes and Soldatos own critical-path implementation/review lanes when assigned. That role split does not authorize any model to cross a real-world human gate.

This repository engineering authorization does not authorize real-world submissions, external communications, paid commitments or identity actions. Follow the strict owner-intervention rule and fixture-first recovery contract in `AGENTS.md` and `docs/ONEHOST_RECOVERY_CONTRACT.md`.

## Claude and other contributors

Claude and other AI contributors may be assigned advisory or implementation work by TheHighBrid or the active integration lead. They remain bounded to their assigned scope and do not gain standing integration authority from repository prose.

## Default operating behavior

For an accepted engineering mission:

```text
verify current state
→ confirm assignment from TheHighBrid or the active integration lead
→ claim lane
→ inspect root cause and dependencies
→ implement
→ test
→ repair failures introduced or exposed by the work
→ refresh from current main
→ run affected certification/release gates
→ open/update PR
→ provide exact handoff
→ Antigravity & Grok independent integration review
```

Do not convert this into:

```text
inspect
→ write recommendations
→ ask the owner to perform ordinary engineering steps
→ stop
```

If the environment cannot perform a required step, first exhaust repository inspection, CI, logs, tests, documentation, and other non-owner-dependent evidence. Request owner action only where access, physical-device interaction, personal judgment, legal/sensitive answers, credentials, or an explicit real-world authorization is genuinely required.

## Standing technical priorities

Unless TheHighBrid or the active integration lead records a more specific priority, implementation contributors should favor work that directly shortens the path to a reliable finished JobTomatik product:

1. current release blockers and reproducible verification failures;
2. owner-facing workflow gaps preventing a prepared application from reaching a truthful next state;
3. reliability, recovery, idempotency, evidence, and duplicate-prevention defects;
4. ATS adapter correctness and certification infrastructure;
5. public deployment and autonomous architecture blockers;
6. backend/frontend integration gaps and broken user flows;
7. test, CI, observability, migration, and operational hardening;
8. performance or maintainability refactors that materially accelerate subsequent execution;
9. remaining roadmap work with validated prerequisites.

## Real-world execution boundary

Repository engineering authority does **not** equal unrestricted authority over real applications.

All contributors must preserve the repository's existing evidence, approval, duplicate, recovery, circuit-breaker, cap, kill-switch, and maturity controls.

Without a separate exact owner authorization, no contributor may:

- issue, infer, consume, reuse, or widen an application submission approval;
- click or trigger a real final-submit action;
- send recruiter or follow-up communication;
- invent or infer sensitive, legal, demographic, disability, veteran, sponsorship, work-authorization, consent, or identity answers;
- bypass or evade CAPTCHA, MFA, login, identity verification, assessment, rate-limit, or anti-bot/security controls;
- present a click, local state, user assertion, dry run, fixture, test, or documentation artifact as confirmed submission evidence;
- fabricate campaign evidence or prerequisite completion;
- promote an ATS adapter to a higher maturity level without repository-defined evidence and owner-approved release decision;
- enable real-submit, autopilot, platform-pilot, or equivalent production flags merely to make a test or campaign pass;
- mutate canonical campaign evidence to hide or reinterpret a failed historical run.

## Owner-intervention rule

Never use TheHighBrid as a troubleshooting agent. Before requesting owner action, exhaust repository inspection, available logs, CI evidence, deterministic fixtures, automated tests, and other non-owner paths.

Involve the owner only at a genuine human gate requiring access, authorization, identity, sensitive answers, or unique judgment, or for final execution acceptance after multiple thorough independent tests have passed, verification has been achieved, and no viable alternative remains. Request only the smallest necessary action.

## Cooperation procedure

Before editing a new lane, Manus should record:

- repository and current `main` SHA independently verified;
- assignment source: TheHighBrid or the active integration lead;
- accepted scope;
- excluded scope;
- branch name;
- intended or likely files/components;
- acceptance tests/gates;
- known overlap with other active work.

Use one dedicated branch per task. Do not silently edit another contributor's claimed files. Open a draft PR early for substantive work.

## Definition of done

Completion requires, as applicable:

- the underlying defect or missing capability is resolved end to end;
- regressions are covered by focused tests;
- affected backend/frontend/Android/runtime behavior is validated;
- migrations and generated artifacts are checked when touched;
- safety/maturity invariants remain truthful;
- the branch is refreshed against current `main`;
- relevant exact-head CI and release gates are green, or a real external blocker is documented precisely;
- no unresolved review thread materially blocks integration;
- the handoff distinguishes verified facts from assumptions and future work.

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

Do not rely on this file as a project-status snapshot. Re-verify live repository state before each mission.
