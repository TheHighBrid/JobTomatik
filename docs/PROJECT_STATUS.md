# Project status

**Snapshot:** 2026-10-16, America/Toronto. **Product owner:** Don `TheHighBrid`.

This is the current project briefing. Historical campaign days, closed child PRs and old Android runtime instructions do not describe today's deployment. Status is evidence-based; no project-wide completion percentage or delivery date has been certified.

## Executive assessment

JT5 execution and owner handoff are integrated through [#704](https://github.com/TheHighBrid/JobTomatik/pull/704). Release-control correction [#706](https://github.com/TheHighBrid/JobTomatik/pull/706) is merged as `f7c2f6f7`; current main is `0c169a673ca0feb8cbbb806dcd6b5d532fb71c06`, including timezone correction #675.

OVH administration is online. Fresh inspection on 2026-10-16 found API and worker healthy on `jobtomatik:28b70d5`, with PostgreSQL and Redis healthy. Release-control enforcement has exact-source image tests and a retained cutover receipt. The effective real-submit, follow-up and Greenhouse/Lever pilot flags were freshly read as false. This is a healthy deployment, not general autonomous certification.

The immediate code candidate is [#711](https://github.com/TheHighBrid/JobTomatik/pull/711), head `4c9914a21aafb46efca051236ec7a403762f5733`. It preserves complete late confirmation receipts without rewriting a closed checkpoint and fixes a reproducible PostgreSQL lock-order deadlock. Local source tests, the built-image PostgreSQL proof and the new PostgreSQL CI job pass. Independent final-head code review found no major issues. Full backend CI and integration remain pending at this snapshot. The image is built but not deployed.

#708 was merged into a feature parent rather than current main. #710 remains a separate recovery candidate with unresolved review findings. Neither is described here as a deployed recovery API.

## Operational matrix

| Component | Latest supported finding | Limit / next verification |
|---|---|---|
| API / authentication | Fresh container health passes on deployed image `28b70d5`; prior cutover verified authenticated reads | Repeat supported-flow acceptance after a new deployment |
| PostgreSQL | Freshly healthy; #711 concurrent row-lock regression and 21-case recovery suite pass on isolated PostgreSQL15 | Backup restore and sustained operation still need retained evidence |
| Redis | Freshly healthy; queues inspected in prior cutover receipt | Current queue depth not reverified by this documentation refresh |
| Celery | One worker, solo pool, concurrency 1; restart reconciliation tested | Do not add workers against the shared browser profile |
| Browser | Playwright-owned Chromium; shared persistent state and private native display | Profile lifecycle candidate #674 remains open; reconcile remaining delta |
| Owner UI | JT5 Apply, status polling, retained handoff, post-action uncertainty display integrated | Do not treat a manual Applied selection as employer confirmation |
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

## Remaining work in priority order

| Priority | Work | Evidence needed to close | Owner role |
|---|---|---|---|
| P0 | Complete #711 final-head checks and integration | All required final-head checks; independent review; retained image/source and regression evidence | Underboss integration; assigned Caporegime implementation |
| P0 | Promote a verified late-result repair after integration | Matching API/worker source, unchanged release flags and application outcomes, retained rollback | Assigned operations lane; independent review |
| P1 | Evidence-backed reconciliation of uncertain attempts | Audited same-attempt operation; preserve consumed final-action checkpoint; no replay or false confirmation | Assigned Caporegime |
| P1 | Classify proven pre-browser safety failures accurately | Regression distinguishes `failed_pre_submit` from genuinely uncertain browser outcomes | Assigned Soldato |
| P1 | Reconcile #674 and diagnostic remnants | #675 is now merged; compare remaining deltas against current main without reopening completed work | Underboss |
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
