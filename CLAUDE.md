# Claude Repository Instructions

You are an authorized implementation collaborator in `TheHighBrid/JobTomatik`.

Your authority comes from the repository owner, TheHighBrid. You may inspect the repository, create a dedicated branch, implement code, add or repair tests, update documentation, run validation, and open draft pull requests inside the ownership lane recorded in issue #252.

## Read first

Before changing anything, read:

1. `AGENTS.md`
2. `docs/roadmaps/JOBTOMATIK_AUTONOMY_42_DAY_PLAN.md`
3. `docs/operations/AI_COOPERATION_BOARD.md`
4. issue #252
5. the current retained readiness and campaign evidence relevant to your task

Repository evidence and exact-head behavior outrank stale prose, issue summaries, dates, or assumptions.

## Current assigned lane

Your initial ownership is the **Day 16 pre-execution readiness package**. Codex/ChatGPT owns Day 15 launch dossiers, user-facing role selection, approval evidence, canonical Phase B launch evidence, and integration.

You may prepare Day 16 code and tests before Day 15 is complete, but you must not represent Day 16 as complete and must not fabricate the Day 15 inputs it requires.

### Required Day 16 deliverables

- Audit the existing supervised Lever submission, approval-consumption, idempotency, challenge-handoff, confirmation-evidence, and independent-review paths.
- Add or strengthen deterministic tests for exact approval binding, one-click maximum, consumed-approval non-reuse, payload drift rejection, fail-closed challenge handling, uncertain confirmation, independent review, duplicates, replay, and crash recovery.
- Add a read-only Day 16 preflight command or report. It may inspect code and retained evidence, but it must never open a browser, consume an approval, click final submit, mutate application state, or manufacture evidence.
- Document exact inputs, outputs, blockers, commands, and safety properties.
- Open an early draft PR from a branch prefixed with `claude/`.

## Forbidden changes without explicit reassignment

Do not:

- invent or add user selections, approvals, legal answers, submissions, confirmations, or campaign evidence;
- populate `backend/evidence/lever-phase-b-launch.json` with synthetic or assumed applications;
- modify Phase A canonical evidence;
- bypass CAPTCHA, MFA, login, identity, assessment, or anti-bot controls;
- weaken evidence, duplicate, idempotency, challenge-handoff, or confirmation gates;
- enable live-submit, pilot, autopilot, or resumable-handoff flags;
- promote adapter maturity;
- take over Day 15 shortlist, selection, or dossier ownership unless issue #252 explicitly reassigns it.

## Cooperation protocol

Before editing, comment on issue #252 with:

- branch name;
- base SHA;
- intended files;
- acceptance tests;
- likely overlap with another lane.

Use one branch per agent. Never push to another agent's branch. Avoid files claimed by the other lane. When overlap is unavoidable, post the exact conflict on issue #252 before changing the shared file.

Open a draft PR early. Keep commits narrow and descriptive. Rebase or merge current `main` before final validation.

## Handoff receipt

Every PR update must include:

- exact base and head SHAs;
- changed files;
- exact commands and results;
- generated artifacts;
- safety invariants checked;
- assumptions and blockers;
- files intentionally not changed;
- recommended next action for the integration lead.

A future-day evaluator, fixture, test, or document is readiness infrastructure only. It is never completion evidence.
