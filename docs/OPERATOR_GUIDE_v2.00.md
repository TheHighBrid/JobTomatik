# JobTomatik v2.00 Operator Guide

> **Pre-release document.** Use this guide as the v2.00 operating baseline after the exact release candidate passes Day 41 and Day 42. Until then, the currently deployed runtime and retained evidence remain authoritative.

## Operating principle

JobTomatik v2.00 is designed for bounded autonomy. Normal operation should require little routine intervention, but the system must stop when identity, security, legal-answer, ambiguous-control, duplicate, confirmation, circuit-breaker, or policy boundaries require review.

The operator's job is not to force throughput. The operator verifies that the system remains inside its approved scope and intervenes only when the retained state identifies a genuine human boundary.

## Start-of-operation checks

Before allowing autonomous work on any runtime:

1. Confirm the exact runtime source revision.
2. Confirm the running adapter manifest matches that revision.
3. Confirm only adapters with retained `certified_autonomous` evidence are eligible for unattended real submission.
4. Confirm production policy is loaded and healthy.
5. Confirm real-submission and follow-up defaults match the intended operating mode.
6. Confirm no global or platform circuit breaker is active.
7. Confirm the live authorization, when required, is current, exact to the runtime revision, and within its start/expiry window.
8. Confirm the remaining daily/weekly attempt budget is sufficient.
9. Confirm worker, Beat, Redis, API, frontend, and browser runtime identity checks are healthy.
10. Confirm no unresolved critical incident or uncertain submission blocks operation.

A repository branch, CI badge, or environment variable does not replace these runtime checks.

## Android managed runtime

The canonical Android backend runtime is the Ubuntu PRoot checkout, not a second native Termux repository copy.

Typical entry point:

```bash
proot-distro login ubuntu --shared-tmp
cd /root/JobTomatik
```

Use the repository's managed Android commands and acceptance tooling rather than manually reconstructing process commands unless diagnosing a specific failure.

Before a certification or live operation after any code update, obtain a fresh exact-revision runtime acceptance. A runtime acceptance receipt from an older source revision is stale, even when every process is otherwise healthy.

## Routine autonomous operation

During normal operation, JobTomatik may:

- discover public job opportunities;
- score and prioritize eligible roles;
- prepare truthful application materials;
- schedule work within caps and quiet hours;
- execute an autonomous submission only through an adapter whose maturity and current authorization permit it;
- capture confirmation evidence;
- classify failures and uncertainty;
- prepare follow-up work when the follow-up policy permits it.

The operator should review alerts and evidence summaries, not manually advance applications simply to increase throughput.

## Human-review queue

Treat `needs_review`, retained handoff, and `submission_uncertain` as meaningful states rather than inconveniences.

### CAPTCHA, MFA, identity, or assessment

- Open the retained handoff only when the task belongs to the expected employer/posting.
- Complete only the external action the applicant must personally perform.
- Do not change stored application answers merely to get past the challenge.
- Resume only while the retained session remains valid and bound to the same target.

### Ambiguous required question

- Read the exact question and available options.
- Resolve it from truthful applicant information or an approved answer policy.
- If the applicant has not provided the necessary fact, keep the application paused.
- Never infer a sensitive or legally consequential answer from unrelated profile data.

### Submission uncertainty

- Do not click submit again.
- Inspect the employer confirmation page, portal history, confirmation email, application ID, timestamp, and submitted material hashes where available.
- Record strong evidence before moving to a successful terminal state.
- If the employer proves no application was received, resolve the review record before any controlled retry.

## Kill switch and emergency containment

For any suspected critical defect, duplicate submission, wrong target, unexpected real submission, guessed required answer, or breaker escape:

1. Set `ALLOW_REAL_APPLICATION_SUBMIT=false`.
2. Set `AUTOPILOT_ENABLED=false`.
3. Disable the affected platform or all platforms through the platform disable policy.
4. Leave application/evidence records intact.
5. Preserve relevant logs, screenshots, review records, queue state, and runtime revision.
6. Review all `applying` and `submission_uncertain` rows from the incident window.
7. Reproduce only with synthetic or dry-run data until the cause is understood.

See `docs/operations/recovery-incident-response.md` for the complete recovery procedure.

## Circuit breakers

A circuit breaker is a stop condition, not a warning to dismiss. Do not clear a breaker solely because queued work is waiting.

Before clearing a breaker:

- identify the clustered failure mode;
- preserve the incident evidence;
- verify no incorrect successful states were recorded;
- patch or isolate the cause;
- run the affected deterministic tests and certification lane;
- obtain exact-head runtime verification where required;
- document why re-enabling is safe.

## Application caps and quiet hours

Production policy uses configured rolling limits and quiet-hour rules. The exact implementation in the release candidate is authoritative.

Do not manually alter timestamps or application history to create capacity. A previously reserved live attempt remains consumed when the system deliberately treats the reservation as non-reclaiming.

If capacity is exhausted, allow the policy window to advance naturally or change the configured cap through the intended policy mechanism with explicit review.

## Live-pilot authorization

A live authorization is deliberately narrow. It is expected to bind:

- owner/approver;
- adapter;
- adapter version;
- exact source revision;
- start and expiry time;
- maximum consequential attempt count;
- approval reference;
- exact acknowledgment.

Do not reuse an authorization after:

- runtime source revision changes;
- adapter version changes;
- expiration;
- revocation;
- the allowed attempt budget is exhausted;
- the associated release/promotion evidence becomes invalid.

## Follow-up operation

Application submission authority and follow-up send authority are separate.

When real follow-up sending is disabled, JobTomatik may still generate schedules, drafts, reminders, and review agenda items. Do not interpret a successful application submission as permission to send an external message.

## Database and evidence handling

The application database and evidence ledger are part of the safety system.

- Back up before migration or release drills.
- Prefer non-destructive restore verification against copies.
- Do not delete uncertain or failed application rows to make dashboards look clean.
- Preserve idempotency keys and attempt counters during rollback.
- Keep evidence hashes and source revision references attached to their original records.
- Do not edit retained certification JSON manually to force a gate to pass.

## Upgrade procedure

Before upgrading an installed Android client/runtime:

1. Disable autonomous/live operation.
2. Preserve the database and retained evidence.
3. Review the new release `SOURCE-COMMIT.txt`, APK checksum, build info, signing certificate, and candidate metadata.
4. Confirm the release target commit equals the documented source revision.
5. Confirm the installed signing identity is compatible with the existing APK. A changed signing key may require uninstall/reinstall.
6. Update the runtime to the exact release commit.
7. Run fresh Android Runtime V2 acceptance on that exact commit.
8. Verify current maturity and policy manifests before re-enabling any bounded autonomous mode.
9. Create a new live authorization when live operation is intended. Never reuse one from the previous commit.

## Rollback procedure

1. Disable live submission and autopilot first.
2. Preserve the current database/evidence state.
3. Deploy the last known-good application revision.
4. Do not downgrade the database in place without testing the downgrade against a backup/copy.
5. Run recovery and compatibility checks on the rollback revision.
6. Reconcile every application created or modified in the incident window.
7. Re-enable first in non-submitting mode, then only through the normal certification/authorization path.

## Release verification

For v2.00, the final published artifact should be checked against:

- Git tag `v2.0.0`;
- release target exact commit;
- `SOURCE-COMMIT.txt`;
- `JobTomatik-v2.00.sha256`;
- `BUILD-INFO.txt`;
- `APK-SIGNING.txt`;
- `CANDIDATE-METADATA.json` including candidate workflow run ID;
- `DAY42-READINESS-SHA256.txt`;
- final maturity manifest;
- README and CHANGELOG autonomy scope.

A mismatch is a release incident. Do not treat it as harmless metadata drift.

## Daily operator review

For unattended production periods, review at minimum:

- critical/clustered adapter alerts;
- uncertain submissions;
- duplicate-prevention alerts;
- live-attempt budget consumption;
- circuit-breaker state;
- queue backlog and policy deferrals;
- confirmation quality;
- follow-up agenda status;
- runtime revision and process health after upgrades/restarts.

The absence of an alert is not evidence that a release or promotion gate passed. Certification state comes from retained machine-readable evidence.
