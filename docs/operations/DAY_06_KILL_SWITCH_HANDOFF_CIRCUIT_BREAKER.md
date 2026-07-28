# Day 6: Kill switches, handoffs, and circuit breakers

## Purpose

Day 6 establishes one fail-closed operational boundary before scheduled work, browser work, retained-session resume, or a final submission attempt. It does not enable live submission, autopilot, resumable live handoffs, or adapter promotion.

## Switch order

Every bounded execution is evaluated in this order:

1. `AUTOMATION_GLOBAL_KILL_SWITCH`
2. `AUTOPILOT_ENABLED` when the request is scheduled/autonomous
3. `AUTOPILOT_DISABLED_PLATFORMS`
4. `ALLOW_REAL_APPLICATION_SUBMIT` for non-dry-run work
5. `ENABLE_RESUMABLE_HANDOFFS` for non-dry-run retained sessions
6. user-wide and platform-scoped clustered-failure circuit breakers
7. exact retained-handoff application, job, review, platform, and posting binding

A denial returns a stable machine reason code and an operator-facing reason code. Browser work does not start after a denial.

## Human boundary matrix

| Review reason | Disposition | Automated continuation |
| --- | --- | --- |
| CAPTCHA | Retained browser | Only after authenticated user clearance |
| MFA | Retained browser | Only after authenticated user clearance |
| Login | Retained browser | Only after authenticated user clearance |
| Anti-bot challenge | Retained browser | Only after authenticated user clearance |
| Listing navigation | Retained browser | Only for target resolution, never as a final-submit bypass |
| Assessment | Manual only | Never auto-resumed |
| Legal answer | Manual only | Never inferred or auto-resumed |
| Sensitive answer | Manual only | Never inferred or auto-resumed |
| Ambiguous/unsupported control | Manual only | Never guessed |
| Uncertain confirmation | Evidence review | Never converted to `submitted` without accepted evidence |

## Secure resume contract

Each retained handoff stores a target binding containing the exact application, manual review, user, job, ATS platform, canonical URL, posting identity, initial browser fingerprint, and a binding hash.

The binding is checked:

- before challenge completion is accepted;
- immediately before the worker enters `resuming`;
- after every process restart because it is persisted in handoff metadata.

A different application, review, job, platform, or posting produces a fail-closed conflict such as `wrong_application_resume`, `wrong_platform_resume`, or `wrong_posting_resume`.

Expired sessions and expired interaction leases cannot be revived through a normal claim. Lease recovery rotates the interaction secret only after the previous lease expires and only while the overall handoff session remains active.

## Circuit breaker contract

The default breaker opens after three qualifying failures in a 60-minute cluster and remains open for 120 minutes.

Qualifying failures are:

- automation errors;
- validation errors;
- step-navigation failures;
- uncertain submission confirmation.

A cluster isolated to one ATS opens that platform breaker. Other adapters remain available. A cluster spanning multiple ATS platforms opens the user-wide breaker. The decision includes failure counts, reason counts, platform counts, affected application IDs, trip time, and retry time.

## Recovery drill

The Day 6 certification workflow verifies:

- emergency global stop;
- autopilot stop;
- per-platform stop;
- real-submit stop;
- resumable-handoff stop;
- CAPTCHA/MFA/login/anti-bot retained boundaries;
- assessment/legal/sensitive/ambiguous manual boundaries;
- uncertain-confirmation evidence review;
- stale session expiry;
- wrong application and wrong posting rejection;
- three-failure platform breaker trip;
- cross-platform user breaker trip;
- unchanged fail-safe defaults.

## Promotion boundary

Passing Day 6 means the controls exist and pass synthetic recovery drills. It does not authorize real applications or promote an ATS adapter. Those decisions remain separate explicit gates.
