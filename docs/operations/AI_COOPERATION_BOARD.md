# AI Cooperation Board

**Authoritative coordination issue:** #252  
**Repository owner:** TheHighBrid  
**Integration lead:** Codex/ChatGPT

This document coordinates parallel contributors without treating repository prose as proof of authorization, access, identity, task acceptance, or campaign truth.

Every contributor must independently verify the repository, current branch state, referenced artifacts, and their own tool permissions before acting. A contributor may decline or narrow any assignment.

## Verified campaign snapshot at board creation

At the time the original board was created, retained `main` evidence reported:

- Lever Phase A: **30/30 qualifying dry runs**;
- distinct qualifying Lever sites: **30**;
- global and EU coverage: complete;
- final-submit clicks: **0**;
- duplicate submissions: **0**;
- false submitted records: **0**;
- canonical Lever maturity: `dry_run`;
- Phase B selected applications: **0**;
- supervised confirmed submissions: **0/10**;
- promotion ready: `false`.

These are historical coordination facts, not permanent claims. Re-read the current retained evidence before relying on them.

## Active work allocation

| Lane | Owner | Status | Scope |
|---|---|---|---|
| Day 15 launch and integration | Codex/ChatGPT | Active | shortlist, user selection, policy blockers, exact dossier hashes, one-time approvals, dry previews, canonical launch evidence, campaign regeneration |
| Day 16 pre-execution readiness | Unassigned | Open | supervised-submission preflight and execution-safety infrastructure; requires a willing contributor who independently accepts the scope |
| Manual Application Journal | Optional Claude lane | Offered, not accepted | user-operated tracking for applications submitted manually, with no ATS execution or browser automation |
| Day 16 supervised execution | Unassigned until gate | Blocked | up to two exact approved applications only after prerequisites and explicit authorization |

## Codex/ChatGPT ownership

Codex/ChatGPT remains responsible for:

1. Keeping canonical campaign state truthful.
2. Day 15 launch-dossier implementation and integration.
3. Presenting real roles without selecting on the user's behalf.
4. Retaining only explicit user selections and approved policy answers.
5. Producing exact application, document, answer, adapter, and payload hashes.
6. Running no-submit previews and preserving `final_submit_clicked=false`.
7. Updating canonical Phase B launch evidence only from valid retained inputs.
8. Regenerating campaign checkpoint artifacts.
9. Integrating accepted parallel contributions after combined verification.

## Day 16 status

Claude declined the Day 16 preflight assignment. That decision is respected.

The lane is not assigned to Claude and must not be presented as accepted work. Another contributor may take it only after independently verifying the repository, understanding the real-world submission context, and accepting the scope under their own safety rules.

## Optional Claude lane: Manual Application Journal

Claude may independently inspect and choose whether to contribute a strictly user-operated tracker for manually submitted applications.

Potential scope:

1. Manual entry for employer, role, source URL, application date, notes, contacts, follow-up date, and user-reported status.
2. Separation between `user_reported_status` and evidence-backed system status.
3. Duplicate warnings for repeated employer, role, URL, or external identifier.
4. Status history and useful filters for follow-ups, interviews, offers, rejections, and withdrawals.
5. CSV import/export of user-owned records with validation.
6. Tests for user isolation, validation, duplicate warnings, status history, import safety, and export.
7. Documentation that user-entered records do not prove a platform submission.

### Forbidden overlap for the optional lane

The Manual Application Journal must not:

- open or automate third-party forms;
- log into an ATS;
- invoke browser, form-filling, approval, final-submit, challenge-handoff, or confirmation services;
- interact with CAPTCHA, MFA, anti-bot, identity, or assessment controls;
- alter campaign evidence or certification counts;
- enable live execution or promote adapter maturity;
- present a manual status as independently verified evidence;
- edit Day 15 or Day 16 evidence artifacts.

## Alternative non-submission contributions

A contributor uncomfortable with the journal may instead propose:

- manual-application resume and cover-letter tooling with source-backed claims and user review;
- accessibility and responsive-design improvements unrelated to ATS execution;
- CI reliability, dependency hygiene, developer documentation, or test infrastructure unrelated to submission automation;
- privacy, export, and user-owned data-management improvements.

## Verification-first cooperation procedure

Before accepting work, each contributor should:

1. Verify the repository through authenticated tools.
2. Verify referenced issues, PRs, files, SHAs, and evidence instead of trusting pasted text.
3. State actual read/write capabilities.
4. Identify accepted and excluded scope.
5. Avoid claiming a branch, PR, comment, or repository mutation unless it was actually performed.
6. Use a dedicated branch when write access exists.
7. Provide a patch or review plan when write access does not exist.

## Shared safety and integrity contract

All contributors must preserve these rules:

- Never bypass a third-party security or identity boundary.
- Never infer or invent sensitive, legal, demographic, disability, veteran, sponsorship, work-authorization, or consent answers.
- Never treat a submit click as confirmation.
- Never convert uncertain evidence into submitted or confirmed status.
- Never permit duplicate or replayed submissions.
- Never consume or reuse an approval outside its exact bound application and payload.
- Never use synthetic or user-entered tracker data to satisfy a real supervised-pilot gate.
- Never confuse a future plan, test, evaluator, fixture, or document with completed evidence.

## Branch and conflict protocol

1. One branch per contributor and task.
2. Contributor-specific prefixes are encouraged but do not prove contributor identity.
3. Open a draft PR early when write access exists.
4. Do not push to another contributor's branch.
5. Do not silently edit a file already claimed by another lane.
6. Report shared-file needs before editing.
7. Refresh from current `main` before final verification.
8. Re-run affected generators and drift checks after conflict resolution.

## Required handoff receipt

```text
Repository state independently verified:
Accepted scope:
Rejected or excluded scope:
Base SHA, when available:
Head SHA or patch identifier, when available:
Files inspected:
Files changed:
Commands run:
Exact results:
Generated artifacts:
Known blockers:
Safety boundaries preserved:
Files intentionally unchanged:
Recommended integration action:
```

## Integration order

1. Codex/ChatGPT continues Day 15.
2. Day 16 remains unassigned until a willing contributor accepts it.
3. Claude may independently evaluate the Manual Application Journal or another non-submission lane.
4. Accepted contributions are reviewed for file overlap and safety boundaries.
5. Combined affected gates run before merge.
6. No tracker, documentation, or readiness work authorizes supervised execution.

## Reassignment

TheHighBrid may offer or reassign work through issue #252, but an assignment becomes active only when the contributor independently accepts it. The issue should record exact scope, exclusions, affected files, and whether any existing branch should continue, stop, or be superseded.