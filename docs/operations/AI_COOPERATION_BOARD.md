# AI Cooperation Board

**Authoritative coordination issue:** #252  
**Repository owner:** TheHighBrid  
**Integration lead:** Codex/ChatGPT  
**Parallel implementation collaborator:** Claude

This document defines how multiple AI contributors may work on JobTomatik at the same time without duplicating work, overwriting evidence, weakening safety gates, or mistaking preparation for completion.

## Truthful campaign state at creation

The retained `main` evidence proves:

- Lever Phase A: **30/30 qualifying dry runs**;
- distinct qualifying Lever sites: **30**;
- global and EU coverage: complete;
- final-submit clicks: **0**;
- duplicate submissions: **0**;
- false submitted records: **0**;
- durable archive failures: **0**;
- exact-target inspection failures: **0**;
- canonical Lever maturity: `dry_run`;
- Phase B selected applications: **0**;
- supervised confirmed submissions: **0/10**;
- promotion ready: `false`.

The Phase A gate is complete. Day 15 is not complete because no retained application selections, one-time approval dossiers, or passed no-submit previews exist yet.

## Active work allocation

| Lane | Owner | Scope | May start now | Completion dependency |
|---|---|---|---|---|
| Day 15 launch and integration | Codex/ChatGPT | shortlist, user selection, policy blockers, exact dossier hashes, one-time approvals, dry previews, canonical launch evidence, campaign regeneration | Yes | real user selections and retained evidence |
| Day 16 pre-execution readiness | Claude | read-only preflight, deterministic safety tests, approval-consumption and evidence-path audit, documentation | Yes | may merge as infrastructure, but Day 16 execution still depends on completed Day 15 inputs and user authorization |
| Day 16 supervised execution | Unassigned until gate | up to two exact approved applications, challenge handling, strong confirmation evidence, independent review | No | Day 15 complete, explicit approval, preflight green |

## Codex/ChatGPT ownership

Codex/ChatGPT is responsible for:

1. Keeping the canonical campaign state truthful.
2. Implementing or repairing the Day 15 launch-dossier path.
3. Presenting ten high-match real Lever roles without selecting on the user's behalf.
4. Retaining only explicit user selections and approved policy answers.
5. Producing exact application, document, answer, adapter, and payload hashes.
6. Running no-submit previews and preserving `final_submit_clicked=false`.
7. Updating `backend/evidence/lever-phase-b-launch.json` only from valid retained inputs.
8. Regenerating campaign checkpoint artifacts.
9. Reviewing and integrating Claude's draft PR after combined verification.

## Claude ownership

Claude is authorized to build the Day 16 readiness package on a dedicated `claude/` branch.

Expected work:

1. Trace current supervised Lever execution from approval validation through final evidence review.
2. Identify the exact services, models, state transitions, scripts, workflows, and tests involved.
3. Add or strengthen coverage for:
   - exact application and payload binding;
   - single-use approval consumption;
   - maximum one final-submit attempt per approval;
   - stale, changed, mismatched, replayed, and cross-target approvals;
   - duplicate worker and crash-recovery behavior;
   - CAPTCHA, MFA, login, anti-bot, assessment, and ambiguity handoffs;
   - insufficient confirmation remaining `submission_uncertain`;
   - strong confirmation evidence and independent review before campaign credit.
4. Add a read-only preflight command or report that returns blockers without performing an application action.
5. Document how the preflight is run and what it proves.

Claude does not own Day 15 application discovery, selection, user approval, launch evidence, or campaign artifact mutation.

## Shared safety contract

All agents must preserve these rules:

- Never bypass a third-party security or identity boundary.
- Never infer or invent sensitive, legal, demographic, disability, veteran, sponsorship, work-authorization, or consent answers.
- Never treat a submit click as confirmation.
- Never convert uncertain evidence into submitted or confirmed status.
- Never permit duplicate or replayed submissions.
- Never consume or reuse an approval outside its exact bound application and payload.
- Never enable live execution or promote maturity through a documentation-only or test-only change.
- Never use synthetic evidence to satisfy a real supervised-pilot gate.

## Branch protocol

1. Create one dedicated branch per agent and task.
2. Claude branches must begin with `claude/`.
3. Codex branches should begin with `codex/` unless an existing campaign convention is more precise.
4. Before editing, post a claim comment on issue #252 containing:
   - branch name;
   - base SHA;
   - intended file list;
   - acceptance tests;
   - expected shared-file overlap.
5. Do not push to another agent's branch.
6. Do not silently edit a file already claimed by the other lane.
7. Open a draft PR early so overlap is visible.
8. Refresh from current `main` before final verification.

## Conflict protocol

When both lanes need the same file:

1. Stop before editing the shared file.
2. Post the desired change and reason on issue #252.
3. Prefer one agent owning the shared-file edit while the other supplies a patch suggestion or test requirement.
4. Let the integration lead apply the final shared-file change after both lane-specific changes are visible.
5. Re-run every affected generator and drift check after conflict resolution.

Evidence files, generated readiness summaries, maturity manifests, workflow gates, and state-machine code are treated as high-conflict files.

## Required PR handoff receipt

Each agent PR must include:

```text
Base SHA:
Head SHA:
Ownership lane:
Files changed:
Commands run:
Exact results:
Generated artifacts:
Safety invariants verified:
Known blockers:
Assumptions:
Files intentionally unchanged:
Recommended integration action:
```

Statements such as "tests pass" are insufficient without naming the commands and exact result.

## Integration order

1. Claude opens a draft Day 16 preflight PR.
2. Codex/ChatGPT continues Day 15 work and obtains real user-gated inputs.
3. Claude updates its branch if Day 15 changes any consumed schema or path.
4. Codex/ChatGPT reviews Claude's changed files and handoff receipt.
5. Run focused tests, affected certification workflows, campaign drift checks, and the repository's required exact-head matrix.
6. Merge only after the combined state remains truthful.
7. Do not begin Day 16 supervised execution until Day 15 evidence is complete and the user explicitly authorizes the exact applications.

## Reassignment

TheHighBrid may reassign any lane through issue #252. A reassignment must identify the new owner, exact scope, affected files, and whether existing branches should continue, stop, or be superseded.
