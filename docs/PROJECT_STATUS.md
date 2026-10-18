# Project status

**Snapshot:** 2026-10-17, America/Toronto (OVH inspected 2026-10-18 03:46 UTC). **Product owner:** Don `TheHighBrid`.

This is the current project briefing. Historical campaign days, closed child PRs and old Android runtime instructions do not describe today's deployment. Status is evidence-based; no project-wide completion percentage or delivery date has been certified.

## Executive assessment

The production OneHost runtime is healthy but **not at the latest repository revision**. OVH read-only inspection at 2026-10-18 03:46 UTC found healthy API, Celery worker, PostgreSQL and Redis, an HTTP 200 readiness endpoint, and the current API and worker running image `jobtomatik:28b70d5`. The current production image retains the deployed release-control correction [#706](https://github.com/TheHighBrid/JobTomatik/pull/706); `ALLOW_REAL_APPLICATION_SUBMIT=false` was observed on **both** API and worker. No release flags were changed.

**Current `main`: `5279bd56a4cf66cc6bff4281f9ea3bbecebd9352`.** [#711](https://github.com/TheHighBrid/JobTomatik/pull/711) late-result receipt and deadlock fixes, [#674](https://github.com/TheHighBrid/JobTomatik/pull/674) Chromium lifecycle fixes, and [#707](https://github.com/TheHighBrid/JobTomatik/pull/707) documentation were already integrated. On 2026-10-17, [#714](https://github.com/TheHighBrid/JobTomatik/pull/714) merged the independently reviewed [#712](https://github.com/TheHighBrid/JobTomatik/pull/712) outcome-recovery UI/service and [#713](https://github.com/TheHighBrid/JobTomatik/pull/713) owner status diagnostics, plus security and consistency fixes. #712 and #713 are now closed as superseded, **not separately merged**.

The #714 exact-head GitHub CI completed **14/14 successfully**, Codacy found zero new issues, and a fresh independent Codex review of `f4b10b2259` found no major issues. Separate disposable PostgreSQL15 tests passed 72/72, frontend tests 160/160, isolated Chromium lifecycle tests 33/33; a clean checkout of the published source passed 58 additional focused backend tests with two PostgreSQL-only skips. These are **integration and synthetic acceptance** claims, not production promotion or confirmation of an employer submission.

The production database was accessed **read-only**. It currently has **two applications in `submission_uncertain`**, one uncertain submission attempt, **zero active handoffs**, and zero queued jobs in the four Celery/Redis queues checked. No live application was reset, retried or promoted. An older backup `database-before.dump` and rollback-tagged images were found; their presence **does not certify a successful restore drill**. Next P0 is a separate controlled deployment/cutover with current DB snapshots, exact release identity, queue/handoff preservation, protected flags, and rollback evidence.

## Operational matrix

| Component | Latest supported finding | Limit / next verification |
|---|---|---|
| API / authentication | HTTP 200 readiness on deployed `jobtomatik:28b70d5` | #714 code and owner recovery API not deployed; verify authenticated reads after controlled cutover |
| PostgreSQL | Production healthy; read-only counts: two uncertain applications and one uncertain attempt; #714 disposable PostgreSQL15 suite 72/72 | Preserve data; previous backup found but no latest restore/rollback drill recorded |
| Redis | Healthy, queue lengths for celery, scraping, applications and followup each zero at inspection | Recheck immediately before/after a cutover |
| Celery | Single production worker, solo concurrency 1, healthy; `ALLOW_REAL_APPLICATION_SUBMIT=false` verified | Preserve browser identity and no-replay recovery across release |
| Browser | Playwright-owned Chromium; #674 lifecycle code is merged but current production image predates it | Recheck retained profile ownership and handoff behavior after controlled update |
| Owner UI | #714 adds audited same-attempt recovery and owner diagnostics to main | Production frontend is mounted from `/home/ubuntu/JobTomatik/frontend/dist`; build/promote frontend separately |
| Host administration | OVH Desktop Commander online and inspected | No owner copy/paste was required for this refresh |
| Live release control | #706 merged/deployed; API and worker rejection tested; effective real-submit false | Do not enable real-world actions from documentation or general continuation instructions |
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
- [x] Merge and deploy #706 release-control/withdrawal correction; retain its exact-image 40-test proof and cutover receipt.
- [x] Reproduce #711 lock-order failure on PostgreSQL, then pass the corrected 21-case recovery proof and add a permanent PostgreSQL CI job.
- [x] Reverify online OVH administration, healthy containers and current hardware without owner troubleshooting.
- [x] Merge #711 late-result and deadlock fix and #674 Chromium profile lifecycle changes into main.
- [x] Merge #714 recovery/UI/diagnostics with exact-head 14/14 CI, zero new Codacy issues, fresh Codex review and retained synthetic evidence.
- [x] Close superseded #712 and #713 without double-integrating their stacked branches.
- [x] Reinspect OVH live image/flags, ready endpoint, aggregate uncertain outcomes, queue depths and active handoffs read-only after integration.


## Remaining work in priority order

| Priority | Work | Evidence needed to close | Owner role |
|---|---|---|---|
| P0 | Controlled production promotion of integrated #711/#674/#714 code | Exact source/image and frontend attestation, fresh DB snapshot, unchanged disabled real-submit controls, monitored health, evidence and rollback | Underboss operations; Don release boundary |
| P0 | Preserve uncertain outcomes through deployment | Same-attempt state and checkpoint checks, before/after redacted counts, no replay, no fictional confirmation | Assigned operations lane |
| P1 | Validate newly integrated owner reconciliation UI on supported OneHost | Authenticated owner read and audited recovery, no duplicate request, positive or unresolved outcome evidence accurately rendered | Assigned Caporegime |
| P1 | Classify proven pre-browser safety failures accurately | Regression distinguishes `failed_pre_submit` from genuinely uncertain browser outcomes | Assigned Soldato |
| P1 | Production-verify #674 browser profile lock lifecycle | Retained page + startup recovery on promoted image; do not interrupt a live handoff casually | Underboss operations |
| P1 | Reconcile stale tracker items | #688/#689 still open despite implementation; review #676-#680 individually; do not close from title alone | Consigliere review lane |
| P1 | Finish OneHost acceptance / recovery record | Current host identity, restore evidence, resource observations, retained-page and unknown-outcome recovery | Underboss plus assigned operations lane |
| P2 | Reconcile Android release/signing status | Exact APK source, signer, upgrade compatibility and published artifact provenance; #485 remains open | Assigned release lane |
| P2 | Reconcile Greenhouse / Lever acceptance | Review #655/#24/#570/#539 against current supported runtime and actual receipts | Assigned adapter lanes |
| P2 | Bounded autonomous certification | Representative supported-path evidence, policy configuration, caps, alerts, kill switch and rollback drill | Don release decision |

## Outcome transparency

At current OVH inspection there are **two uncertain application states** and **one uncertain attempt**. A prior owner-assisted application has a recorded final action but no employer confirmation; its owner-selected Applied label does not change automation uncertainty. The new #714 recovery UI is *not yet live*, so it has not reconciled these records. No retry, reset or new approval is implied by this documentation.

Historical confirmed submissions on Android establish historical behavior only. They do not certify today's OVH Chromium runtime or a new employer target.

## Reporting rules

Use **implemented**, **tests passed**, **deployed per record**, **host verified**, and **employer confirmed** as separate claims. Include the SHA, runtime, timestamp and artifact for each. Never use a green badge, queued task, button click, manual status or old campaign day as a substitute for a receipt.

Related: [product contract](PRODUCT.md), [roadmap](ROADMAP.md), [evidence ledger](EVIDENCE.md), [costs and machines](COSTS_AND_INFRASTRUCTURE.md), [governance](GOVERNANCE.md).
