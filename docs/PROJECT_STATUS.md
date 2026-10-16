# Project status

**Snapshot:** 2026-10-16, America/Toronto. **Product owner:** Don `TheHighBrid`.

This is the current project briefing. Historical campaign days, closed child PRs and old Android runtime instructions do not describe today's deployment. Status is evidence-based; no project-wide completion percentage or delivery date has been certified.

## Executive assessment

JT5 application execution and the OneHost owner-handoff stack are integrated into `main` through [#704](https://github.com/TheHighBrid/JobTomatik/pull/704). The merged commit is `6aac5b33701db6d13952f86c1faaeca76d66810f`; its tree matches tested implementation `1a8a0c7be8476894c51dfba5e62ea7a8b936d5fd`.

The operational record reports that implementation deployed on the existing OVH host, with healthy services, authenticated reads and retained rollback snapshots. This documentation refresh could inspect GitHub and CI, but could not independently inspect the current host: all Desktop Commander devices were offline. Reported deployment evidence is distinguished from fresh host verification throughout these documents.

A known release-control defect remains: the integrated JT5 path can bypass `ALLOW_REAL_APPLICATION_SUBMIT`. [#706](https://github.com/TheHighBrid/JobTomatik/pull/706) adds API and worker enforcement and corrects withdrawn-state handling. It is an open draft, not merged or deployed. Its exact head has 21 successful checks, one Codacy `action_required`, and one skipped check at this snapshot. Successful test checks do not make that gate clear.

## Operational matrix

| Component | Latest supported finding | Limit / next verification |
|---|---|---|
| API / authentication | Deployment record: public health/readiness and authenticated application/status/handoff reads returned 200 | Current process and revision require host access |
| PostgreSQL | Deployment record: healthy; contended handoff returned 423 in 24 ms without writes | Backup restore and sustained operation need retained evidence |
| Redis | Deployment record: healthy; queues inspected before cutover | Current queue depth not reverified |
| Celery | One worker, solo pool, concurrency 1; restart reconciliation tested | Do not add workers against the shared browser profile |
| Browser | Playwright-owned Chromium; shared persistent state and private native display | Profile lifecycle candidate #674 remains open; reconcile remaining delta |
| Owner UI | JT5 Apply, status polling, retained handoff, post-action uncertainty display integrated | Do not treat a manual Applied selection as employer confirmation |
| Host administration | OVH Desktop Commander offline at refresh | Blocks fresh administrative inspection and deployment of #706 |
| Live release control | Compose defaults false; #706 fixes missing JT5 enforcement | False configuration alone does not prove the current code blocks Apply |
| Unattended operation | Final product objective | Not certified for general autonomous use |

## Completed engineering

These are implementation or recorded validation milestones, not blanket production certification.

- [x] Integrate the JT5 execution and handoff chain into `main` through #704.
- [x] Route owner Apply through reservation plus worker dispatch; remove the public reserve-only route.
- [x] Preserve owner isolation, atomic attempt claims, target binding and duplicate protection.
- [x] Reconcile interrupted attempts on OneHost worker startup without automatic live replay.
- [x] Verify isolated production Compose startup, queue round trip, persistent browser and controlled restart.
- [x] Add retained owner-browser interaction and a separately checkpointed once-only final action.
- [x] Repair pending-review persistence, UTC lease handling, transient viewer recovery and contended locks.
- [x] Keep uncertain outcomes visible after final action and after manual application-status changes.
- [x] Verify #704's implementation head: 25 successful checks, two skipped, none failed or running.
- [x] Record deployment attestation, rollback images and database/configuration snapshots for that implementation.

## Remaining work in priority order

| Priority | Work | Evidence needed to close | Owner role |
|---|---|---|---|
| P0 | Finish #706 quality review, integrate and deploy | Clear exact-head checks including Codacy; owner/non-owner, disabled API/worker and withdrawal regressions; matching API/worker revision | Underboss integration; assigned Caporegime implementation |
| P0 | Prove live-release control on deployed build | Controlled no-employer test rejects disabled Apply before reservation/dispatch; worker recheck prevents browser entry | Assigned Soldato; independent review |
| P1 | Evidence-backed reconciliation of uncertain attempts | Audited same-attempt operation; preserve consumed final-action checkpoint; no replay or false confirmation | Assigned Caporegime |
| P1 | Classify proven pre-browser safety failures accurately | Regression distinguishes `failed_pre_submit` from genuinely uncertain browser outcomes | Assigned Soldato |
| P1 | Reconcile #674 / #675 and diagnostic remnants | Compare each remaining delta against merged main; retain necessary fixes, close superseded work with evidence | Underboss |
| P1 | Reconcile stale tracker items | #688/#689 still open despite implementation; review #676-#680 individually; do not close from title alone | Consigliere review lane |
| P1 | Finish OneHost acceptance / recovery record | Current host identity, restore evidence, resource observations, retained-page and unknown-outcome recovery | Underboss plus assigned operations lane |
| P2 | Reconcile Android release/signing status | Exact APK source, signer, upgrade compatibility and published artifact provenance; #485 remains open | Assigned release lane |
| P2 | Reconcile Greenhouse / Lever acceptance | Review #655/#24/#570/#539 against current supported runtime and actual receipts | Assigned adapter lanes |
| P2 | Bounded autonomous certification | Representative supported-path evidence, policy configuration, caps, alerts, kill switch and rollback drill | Don release decision |

## Outcome transparency

The latest owner-assisted application has one recorded final action and no employer confirmation evidence. Its user-selected status is Applied while automation remains uncertain. This is an unresolved outcome, not a successful autonomous submission. No retry, reset or new approval is implied by this documentation.

Historical confirmed submissions on Android establish historical behavior only. They do not certify today's OVH Chromium runtime or a new employer target.

## Reporting rules

Use **implemented**, **tests passed**, **deployed per record**, **host verified**, and **employer confirmed** as separate claims. Include the SHA, runtime, timestamp and artifact for each. Never use a green badge, queued task, button click, manual status or old campaign day as a substitute for a receipt.

Related: [product contract](PRODUCT.md), [roadmap](ROADMAP.md), [evidence ledger](EVIDENCE.md), [costs and machines](COSTS_AND_INFRASTRUCTURE.md), [governance](GOVERNANCE.md).
