# JT5 production cutover checklist

**Updated:** 2026-10-17 (America/Toronto). Integration, deployment records and release acceptance are separate. Checked entries below apply to the exact recorded implementation, not to an untested successor.

## Recorded integration

- [x] #704 merged to main as `6aac5b33701db6d13952f86c1faaeca76d66810f`.
- [x] Owner Apply/status, target-bound execution and removal of reserve-only API are included.
- [x] Implementation `1a8a0c7be8476894c51dfba5e62ea7a8b936d5fd` has 25 successful/two skipped checks.
- [x] Merge and tested implementation trees match `81ce6d286e7f94dedeb2db388c1c7c35b6873024`.
- [x] Backend, frontend, Android, queue, controlled browser, native/mobile handoff and production Compose restart evidence recorded.
- [x] API/worker deployment attestation, healthy reads, bounded contention and rollback snapshots recorded for that implementation.

Sources: [evidence ledger](../EVIDENCE.md), [#704](https://github.com/TheHighBrid/JobTomatik/pull/704), [integration receipt](https://github.com/TheHighBrid/JobTomatik/issues/252#issuecomment-6207500359).

## Corrected candidate and release controls

- [x] Clear #706 quality findings and complete its exact-head checks.
- [x] Merge release-flag enforcement and withdrawal handling through #706.
- [x] Deploy matching API/worker `28b70d5` images with source/build identity and rollback receipt.
- [x] Verify disabled Apply rejects before reservation/dispatch without employer traffic.
- [x] Verify worker disablement/withdrawal rejection without browser entry or false confirmation.
- [x] Integrate #711 late-result repair, #674 Chromium lifecycle and #714 owner recovery/diagnostics into `main` as `5279bd56` (14/14 #714 CI; Codacy zero new issues; independent review no major issues).
- [x] Validate #714 synthetic same-attempt recovery, evidence binding, duplicate prevention and original-worker-result privacy (72 PostgreSQL tests and 160 frontend tests).
- [ ] Recheck the **two production uncertain application states and one uncertain submission attempt** before and after controlled promotion; preserve owner history and checkpoints without automatic replay.
- [ ] Complete same-attempt evidence reconciliation and pre-browser failure-classification follow-ups.

Compose's false default alone is not enforcement proof. Preserve the API/worker correction and regressions delivered in #706.

## Current OneHost acceptance

Use [OneHost production deployment](ONEHOST_PRODUCTION_DEPLOYMENT.md). Do not restart a live retained owner session casually to collect a checklist result.

- [x] Reinspect authorized OVH host: deployed API/worker `jobtomatik:28b70d5`, 5 running services healthy/active, HTTP 200 readiness, real-submit=false on API and worker, zero active handoffs, and four checked queue lengths zero. **This is the old image, not #714.**
- [x] Record current OS, CPU/vCPU, total RAM and root-disk observations; see the costs/infrastructure document.
- [ ] Measure persistent-volume and evidence growth separately.
- [ ] Retain a **fresh** pre-promotion DB backup, test non-destructive restore/rollback on an isolated target, and document the observation window. Previous 2026-10-16 backup and rollback images exist, but their presence alone is not a new restore proof.
- [ ] On the **promoted** image verify authenticated owner reads, #714 recovery UI and diagnostics, transient viewer recovery and contended-lock behavior, with the same no-retry invariant.
- [ ] Recheck startup recovery: unknown/interrupted possible submissions become uncertain without replay.
- [x] Observe one healthy production solo Celery worker with concurrency 1 and shared OneHost namespace contract.
- [ ] Reconfirm same-browser identity and private display boundaries after promotion, with redacted runtime evidence.
- [ ] Capture redacted invoices and optional-service usage for an actual cost total.

## Next promotion boundary

- [ ] Confirm exact target release commit `5279bd56`, API/worker image identity, frontend build hash, correct Compose config and rollback artifacts.
- [ ] Keep `ALLOW_REAL_APPLICATION_SUBMIT=false` on both API and worker; do not enable autopilot, paid services or external sends.
- [ ] Confirm no active handoff, inspect queue/stale sessions, retain new DB snapshot, then use a controlled image+frontend cutover only within the owner's authorized release window.
- [ ] Preserve before/after redacted uncertain-outcome counts; no application retry, fabricated receipt, or checkpoint reset.
- [ ] Confirm HTTP 200 readiness, authenticated owner recovery and diagnostics, single worker health, browser profile and rollback readiness on the actually deployed image.

## Owner-controlled live acceptance

- [ ] Review corrected candidate identity, known limitations and retained evidence.
- [ ] Obtain explicit owner approval for the exact candidate revision and reviewed production configuration before any real application action.
- [ ] Record the exact employer/application/payload authorization and its once-only scope; never reuse a consumed approval.
- [ ] Apply any live-submit flag transition only within that reviewed owner authorization, retain before/after values, and restore the closed setting after the scoped action.
- [ ] Verify employer, role, canonical target, application identity and materials before an authorized action.
- [ ] Observe an actual outcome and retain confirmation evidence or explicit uncertainty.
- [ ] Verify no duplicate attempt or automatic retry occurs.
- [ ] Reconcile uncertainty on the same attempt before considering another action.

## Distribution and final release

- [ ] Record exact APK source, signer, upgrade compatibility, artifact hash and rollback path.
- [ ] Reconcile #485 and current release evidence; do not infer signing completion from a build.
- [ ] Confirm supported-platform scope and operational limits.
- [ ] Publish a version/tag/release only through the owner's authorized release process.

Current candidate/public release identities and milestone status are in [the README](../../README.md), [roadmap](../ROADMAP.md) and [integration notes](../RELEASE_NOTES_JT5.md).
