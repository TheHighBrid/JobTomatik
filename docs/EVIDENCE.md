# Evidence ledger

**Collected:** 2026-10-16. GitHub metadata, fresh host observations, synthetic tests and employer receipts are distinct evidence classes. The timestamped [machine-readable snapshot](evidence/2026-10-16-project-snapshot.json) retains both this update and the initial historical snapshot.

## Current source and runtime identity

| Item | Exact identity | Supported claim |
|---|---|---|
| Current main | `0c169a673ca0feb8cbbb806dcd6b5d532fb71c06` | Includes #704, #706 and timezone correction #675 |
| Running API / worker | `28b70d530055d3c37e0c57364f1428900bee48ac`, image `jobtomatik:28b70d5` | Fresh Docker inspection: both healthy on the prior verified release |
| Late-result candidate #711 | `4c9914a21aafb46efca051236ec7a403762f5733` | Source candidate only; not merged or deployed |
| Candidate tree | `cb4a91b9c52b7a6ff99eb5e0f8259fd0ab8a88e8` | Published source fetched back and compared with tested worktree |
| Candidate image | `jobtomatik:4c9914a`; image ID `sha256:49a612a2e17584d7dd73b7d34ec3e48f3a6cf08f7d44f8721c822830e93d4784` | Built on OVH; revision label and all three changed Python file hashes verified |
| Latest published release | [v2.1.0](https://github.com/TheHighBrid/JobTomatik/releases/tag/v2.1.0), 2026-09-05 | Fresh GitHub release metadata; a built image is not a published APK |

## Release-control closure

[#706](https://github.com/TheHighBrid/JobTomatik/pull/706) is merged and deployed, superseding the initial pre-deployment documentation snapshot. The retained [cutover receipt](https://github.com/TheHighBrid/JobTomatik/issues/252#issuecomment-6210255597) records 22 successful exact-head checks, a 40-test network-disabled production-image proof, matching source/container hashes, rollback snapshots, healthy reads and unchanged application/attempt/evidence counts.

Its API rejects disabled Apply before reservation or dispatch, and its worker rechecks release state and withdrawal before browser entry. Fresh inspection found real-submit, follow-up and Greenhouse/Lever pilot settings false. No real application was executed to verify these controls.

## Late-result retention and PostgreSQL race

[#711](https://github.com/TheHighBrid/JobTomatik/pull/711) retains full confirmation text, receipt IDs and artifact references when browser work returns after recovery has closed its attempt. It refreshes locked rows and preserves the independently saved outcome and owner history.

The original candidate's opposite lock order was a real defect: a concurrent PostgreSQL regression reproduced `DeadlockDetected` with the worker as victim. Final candidate `4c9914a` locks the attempt before the application, matching the stale reconciler.

| Verification | Result | Boundary |
|---|---|---|
| Source worker/reservation/status suites, network disabled | 54 passed, 1 PostgreSQL-specific skip | Synthetic tests using production image dependencies |
| PostgreSQL receipt suite | 15 passed | Includes simultaneous stale recovery and browser completion |
| Exact new PostgreSQL CI configuration | 21 passed | Receipt and stale-recovery suites on disposable PostgreSQL15 |
| Built candidate image on isolated PostgreSQL | 21 passed | No source mount or test-fixture rebinding |
| [PostgreSQL CI job](https://github.com/TheHighBrid/JobTomatik/actions/runs/38917353643) | Successful | Runs the concurrency regression permanently in CI |
| Independent code review | No major issues on final head | Prior lock-order thread resolved after reproduction and repair |
| Final-head aggregate CI at snapshot | 17 success, 4 full backend checks running | Not yet an all-green integration or release claim |

The earlier [handoff receipt](https://github.com/TheHighBrid/JobTomatik/issues/252#issuecomment-6217141159) describes the first candidate. The newer review correction and exact final-head CI supersede its lock-order and source-identity claims.

## Fresh OVH observations

On 2026-10-16, Desktop Commander was online for `vps-10618f0e`. Fresh inspection found API, worker, PostgreSQL and Redis healthy; Caddy running. The candidate image was built without restarting production services.

At 14:46 UTC the guest reported Ubuntu 26.04.1 LTS, x86_64, 4 virtual CPUs, 7,746 MiB RAM and root disk `72G` total / `56G` available. These are guest observations, not a provider plan or physical-host attestation. [Infrastructure details and billing limits](COSTS_AND_INFRASTRUCTURE.md) remain explicit.

Prior #704/#706 operational receipts retain public health/readiness and authenticated-read results, bounded PostgreSQL contention, source attestation, database/configuration snapshots and rollback images. This refresh did not execute a backup restore or certify sustained unattended operation.

## Employer outcome boundary

The Daniels Health application was freshly read as user status Applied and automation state `submission_uncertain`. No outcome was resolved or retried. A narrow search of the connected personal inbox found no matching receipt; the application used the Melato address, so that search is not conclusive.

A button click, manual status, missing email, fixture page or green test does not prove employer receipt or non-submission. #708 was merged into a feature parent, not current main. #710's proposed recovery API remains unintegrated and has outstanding review findings.

## Historical implementation evidence

#704 merged as `6aac5b33701db6d13952f86c1faaeca76d66810f`; its tree matched tested implementation `1a8a0c7be8476894c51dfba5e62ea7a8b936d5fd`, tree `81ce6d286e7f94dedeb2db388c1c7c35b6873024`. That implementation had 25 successful and two skipped checks. The skipped `public-proof` and `publish-static-runtime (main only)` checks were not passing production proof.

Historical Android confirmations establish that earlier runtime's behavior. They do not certify current OVH Chromium or a different employer target.

## Retention

Keep revision, image, runtime, timestamp, target scope, command/result, artifact hash, observed outcome and unresolved limits in every receipt. Preserve original evidence and append corrections. Never commit secrets, applicant payloads, browser profiles or payment details. A CI artifact link alone does not establish that its bytes were inspected.
