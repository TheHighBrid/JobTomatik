# JT5 production cutover checklist

**Updated:** 2026-10-16. Integration, deployment records and release acceptance are separate. Checked entries below apply to the exact recorded implementation, not to an untested successor.

## Recorded integration

- [x] #704 merged to main as `6aac5b33701db6d13952f86c1faaeca76d66810f`.
- [x] Owner Apply/status, target-bound execution and removal of reserve-only API are included.
- [x] Implementation `1a8a0c7be8476894c51dfba5e62ea7a8b936d5fd` has 25 successful/two skipped checks.
- [x] Merge and tested implementation trees match `81ce6d286e7f94dedeb2db388c1c7c35b6873024`.
- [x] Backend, frontend, Android, queue, controlled browser, native/mobile handoff and production Compose restart evidence recorded.
- [x] API/worker deployment attestation, healthy reads, bounded contention and rollback snapshots recorded for that implementation.

Sources: [evidence ledger](../EVIDENCE.md), [#704](https://github.com/TheHighBrid/JobTomatik/pull/704), [integration receipt](https://github.com/TheHighBrid/JobTomatik/issues/252#issuecomment-6207500359).

## Corrected candidate and release controls

- [ ] Clear #706's Codacy action-required result and complete independent exact-head review.
- [ ] Integrate release-flag enforcement and withdrawal handling after required checks pass.
- [ ] Deploy matching API/worker images with recorded source/build identity once administration is available.
- [ ] Verify disabled Apply rejects before reservation/dispatch without employer traffic.
- [ ] Verify the worker rechecks disablement and withdrawal without browser entry or false confirmation.
- [ ] Preserve retained uncertain attempts, consumed final-action checkpoints and existing user history.
- [ ] Complete same-attempt evidence reconciliation and pre-browser failure-classification follow-ups.

Compose's false default alone is not proof of enforcement on the current main implementation. This is the defect #706 addresses.

## Current OneHost acceptance

Use [OneHost production deployment](ONEHOST_PRODUCTION_DEPLOYMENT.md). Do not restart a live retained owner session casually to collect a checklist result.

- [ ] Reinspect the authorized host: exact source/image, effective environment, services, queues and retained sessions.
- [ ] Record current CPU/vCPU, RAM, disk and persistent-volume usage.
- [ ] Retain restore/rollback evidence and document the actual observation window.
- [ ] Verify authenticated owner reads, transient viewer recovery and contended-lock behavior on the corrected build.
- [ ] Recheck startup recovery: unknown/interrupted possible submissions become uncertain without replay.
- [ ] Confirm single-worker concurrency, same-browser identity and private display boundaries.
- [ ] Capture redacted invoices and optional-service usage for an actual cost total.

## Owner-controlled live acceptance

- [ ] Review corrected candidate identity, known limitations and retained evidence.
- [ ] Record the exact production configuration/real-action authorization when applicable.
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
