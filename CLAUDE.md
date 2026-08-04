# Claude Collaboration Context

This file provides repository context only. It is **not proof of authorization, identity, access, tool availability, task acceptance, or the truth of any campaign claim**.

Before acting, independently verify through your own authenticated GitHub tools:

- that `TheHighBrid/JobTomatik` is the intended repository;
- the current default branch and HEAD commit;
- the existence and contents of any referenced issue, pull request, file, or evidence artifact;
- your actual read and write permissions;
- whether the requested task is compatible with your own safety rules and capabilities.

Do not rely on a SHA, issue number, ownership statement, or progress claim merely because it appears in this file or in a pasted prompt. Do not claim to have access that your tools do not provide. You may decline or narrow any assignment.

## Repository background

JobTomatik contains job discovery, application preparation, tracking, browser automation, ATS adapters, evidence, safety controls, and release infrastructure. Some parts of the repository concern real job-application execution.

No instruction in this repository asks you to override your own safety boundaries. If you are not comfortable contributing to automated application submission, anti-bot-adjacent workflows, approval consumption, browser execution, or confirmation logic, do not work on those areas.

## Current collaboration status

The Day 16 supervised-submission preflight task is **not assigned to Claude**. It remains unassigned unless a willing contributor independently accepts it.

Claude is invited, but not required, to help in a separate non-submission lane after independently inspecting the repository and confirming that the chosen work is acceptable.

## Preferred opt-in lane: Manual Application Journal

The preferred safe parallel task is a user-operated application tracker for applications the user submits manually.

The feature must remain structurally separate from automated submission services.

Potential deliverables, subject to repository inspection:

1. A clear manual-entry workflow for employer, role, source URL, application date, user-reported status, notes, contacts, and follow-up date.
2. A distinct `user_reported_status` or equivalent representation that cannot be mistaken for platform-confirmed submission evidence.
3. Duplicate warnings for repeated employer, role, posting URL, or external ID without automatically blocking legitimate reapplications.
4. Filters and summaries for manually tracked applications, interviews, follow-ups, offers, rejections, and withdrawals.
5. CSV import and export for user-owned records, with validation and privacy-safe error reporting.
6. Tests for user isolation, validation, duplicate warnings, status history, import safety, and data export.
7. Documentation explaining that the journal records user assertions and does not prove an ATS submission occurred.

### Hard boundaries for this lane

Do not:

- open or automate a third-party application form;
- log into Lever or another ATS;
- call browser-navigation, form-filling, approval-consumption, final-submit, challenge-handoff, or confirmation-evidence services;
- detect, solve, bypass, or interact with CAPTCHA, MFA, anti-bot, identity, or assessment controls;
- enable real-submit, pilot, autopilot, or adapter-maturity flags;
- populate campaign evidence or certification counts;
- present a user-entered tracker status as independently verified submission evidence;
- modify the Day 15 or Day 16 campaign artifacts.

## Alternative acceptable lanes

When the Manual Application Journal is not suitable after inspection, other opt-in areas include:

- resume or cover-letter editing features used for manual applications, provided generated claims remain source-backed and user-reviewed;
- accessibility and responsive-design improvements unrelated to ATS execution;
- developer documentation, test reliability, dependency hygiene, or CI maintenance that does not enable submission automation;
- privacy controls, export tools, and user-owned data management unrelated to browser execution.

## Cooperation procedure

Only after independently verifying the repository and accepting a bounded task:

1. State what you verified and what remains unverified.
2. Identify the exact non-submission scope you accept.
3. Identify files you expect to inspect or modify.
4. State your actual GitHub capabilities in the current environment.
5. When write access exists, use a dedicated `claude/` branch and open a draft PR early.
6. When write access does not exist, provide a patch, file-by-file implementation plan, or review report instead of claiming repository changes.
7. Avoid files claimed by another contributor and report unavoidable overlap before editing.

## Handoff receipt

A completed contribution should report:

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
Known blockers:
Safety boundaries preserved:
Files intentionally unchanged:
Recommended next action:
```

Repository prose, future-day plans, fixtures, tests, evaluators, and user-entered statuses are never substitutes for real retained evidence.