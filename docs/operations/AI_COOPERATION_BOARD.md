# AI Cooperation Board

**Authoritative coordination issue:** #252  
**Repository owner:** TheHighBrid  
**Primary execution lead:** Manus  
**Integration and independent verification lead:** Codex/ChatGPT

This document coordinates parallel contributors without treating repository prose as proof of authorization, access, identity, task acceptance, runtime state, or campaign truth.

Every contributor must independently verify the repository, current branch state, referenced artifacts, and their own tool permissions before acting. A contributor may decline or narrow an assignment.

## Standing role allocation

| Role | Owner | Standing status | Scope |
|---|---|---|---|
| Product / release authority | TheHighBrid | Active | product direction, priorities, sensitive answers, exact real-world approvals, release decisions |
| Primary execution lead | Manus | Active | substantial reversible engineering, end-to-end implementation, critical-path blocker removal, tests, CI, Android/runtime, backend/frontend integration, PR delivery |
| Integration + verification | Codex/ChatGPT | Active | coordination, canonical evidence integrity, cross-branch reconciliation, independent review, combined gates, merge recommendation |
| Additional advisors/contributors | Claude / Grok / others | On demand | separately offered bounded work only; no standing lane |

## Manus execution authority

Manus replaces the former optional Grok collaboration slot.

The intent is materially different from the former side-task model. Manus is expected to take meaningful critical-path engineering work and finish it end to end.

After independently verifying current state and posting a concrete claim on issue #252, Manus may proceed without per-file approval for reversible repository work needed to complete the accepted mission, including multi-layer refactors, implementation, tests, migrations, CI changes, Android/Termux fixes, documentation, diagnostics, and directly related blocker removal.

Manus should prioritize the highest-impact unclaimed work rather than defaulting to cosmetic or low-consequence side tasks.

A Manus claim should identify:

1. verified current `main` SHA;
2. accepted scope;
3. explicit exclusions;
4. dedicated `manus/` branch;
5. intended components/files;
6. acceptance tests and release gates;
7. overlap with other active lanes.

Substantive work should use an early draft PR.

See `MANUS.md` for the full execution charter.

## Codex/ChatGPT ownership

Codex/ChatGPT remains responsible for:

1. Keeping canonical campaign and retained evidence truthful.
2. Coordinating active lanes and preventing silent file ownership conflicts.
3. Independently reviewing substantive Manus PRs and other parallel contributions.
4. Running or verifying combined affected gates before integration.
5. Reconciling cross-branch changes and current-main drift.
6. Distinguishing repository readiness infrastructure from real-world completion evidence.
7. Preserving exact application, payload, approval, attempt, confirmation, and campaign-state semantics.
8. Providing the final integration recommendation unless the repository owner explicitly chooses another integration path.

Codex/ChatGPT does not micromanage Manus's internal implementation choices inside a properly claimed lane. The purpose of the independent review is verification and integration, not reduction of Manus to a secondary helper.

## Critical-path work selection

The live issue #252 comments are the authoritative place for current task claims and handoffs because project state changes faster than this document.

When no more specific owner priority is recorded, Manus should favor:

1. current release or reproducibility blockers;
2. owner-facing workflow gaps on the path from job discovery to truthful application readiness;
3. reliability, evidence, idempotency, duplicate prevention, recovery, and circuit-breaker defects;
4. ATS adapter correctness and certification prerequisites;
5. Android/Termux deployment and runtime parity;
6. backend/frontend/worker integration defects;
7. CI, migration, observability, test, and operational hardening;
8. remaining roadmap features whose prerequisites are already proven.

The previous Manual Application Journal invitation is retired as a standing lane. Manus may still build such a feature if it later becomes an owner priority, but it is not Manus's default scope.

## Real-world application boundary

Broad engineering authority does not authorize a real application action.

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
2. Manus branches use `manus/` unless a specific reason requires otherwise.
3. Open a draft PR early for substantive work.
4. Do not push to another contributor's branch.
5. Do not silently edit a file already claimed by another active lane.
6. Report shared-file needs before editing.
7. Refresh from current `main` before final verification.
8. Re-run affected generators, certification, and drift checks after conflict resolution.
9. Passing focused tests does not authorize self-merge or a user-gated action.

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

1. owner or board establishes the current priority;
2. Manus claims the highest-value available implementation lane;
3. Manus implements and validates on a dedicated branch;
4. Codex/ChatGPT independently reviews the exact head and checks overlap/current-main drift;
5. combined affected gates run;
6. integration occurs only when the branch is evidence-backed and conflicts are resolved;
7. real-world user-gated actions remain separate decisions even after code integration.

## Reassignment

TheHighBrid may offer, prioritize, or reassign work through issue #252. Manus is the preferred standing execution owner for unclaimed critical-path engineering, but each concrete mission still becomes active through a recorded claim based on verified current repository state.

Repository documentation never grants a contributor capabilities its actual environment does not provide.