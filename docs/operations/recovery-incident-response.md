# JobTomatik recovery and incident response

## Purpose

This runbook covers interrupted application workers, uncertain submission outcomes, repeated adapter failures, and emergency shutdown. It does not authorize bypassing CAPTCHAs, anti-bot challenges, MFA, identity checks, assessments, or legal-answer review.

## Immediate containment

1. Set `AUTOPILOT_ENABLED=false`.
2. Set `ALLOW_REAL_APPLICATION_SUBMIT=false`.
3. Add the affected platform, or `all`, to `AUTOPILOT_DISABLED_PLATFORMS`.
4. Keep Celery workers available for review, alert, and recovery tasks unless the worker itself is suspected of corruption.
5. Do not manually reset an application from `submission_uncertain` to a retryable state until the employer portal or confirmation evidence has been checked.

These switches are independent. Disabling scheduled automation does not remove existing records, evidence, handoffs, or notifications.

## Stale worker recovery

The scheduled recovery task runs every 15 minutes. An application remaining in `applying` beyond `AUTOPILOT_STALE_ATTEMPT_MINUTES`, 30 minutes by default, is recovered fail closed:

- known dry-run attempt: `applying` to `needs_review`
- live attempt: `applying` to `submission_uncertain`
- unknown attempt mode: `applying` to `submission_uncertain`

Recovery creates:

- one open manual-review task
- one lifecycle recovery event
- one system notification
- a record of the preserved idempotency key and attempt count

Recovery never retries the application automatically. Replaying recovery after the application leaves `applying` creates no duplicate review, event, or notification.

## Operator verification

For a stale live or unknown attempt:

1. Open the application and its manual-review task.
2. Check the employer portal, application history, and any confirmation email.
3. Compare employer, role, timestamp, submitted document hashes, and candidate or application ID where available.
4. Record concrete evidence before moving the application to `submitted` or `confirmed`.
5. When evidence is absent or conflicting, keep `submission_uncertain` and do not retry.
6. When the portal proves no submission occurred, resolve the review with notes before a controlled retry.

## Repeated failure response

Adapter health alerts identify:

- uncertain submissions
- repeated failures
- validation spikes
- source or control breakage
- login or MFA lockout risk
- low confirmation rates

For a critical platform alert:

1. Disable the platform through `AUTOPILOT_DISABLED_PLATFORMS`.
2. Preserve the application logs, review records, screenshots, and sanitized snapshots.
3. Reproduce only in dry-run or synthetic certification mode.
4. Patch the reusable adapter or control layer.
5. Run backend tests, post-merge stabilization, and the platform certification suite.
6. Re-enable only after the exact failure path is green and the incident record is complete.

## Recovery drill

Run locally from `backend`:

```bash
ALLOW_REAL_APPLICATION_SUBMIT=false \
AUTOPILOT_ENABLED=false \
python scripts/run_recovery_incident_drill.py \
  --output recovery-incident-drill.json
```

The drill uses an isolated in-memory SQLite database and no browser or network connection. It simulates stale dry-run, live, and unknown attempts, runs recovery, replays it, and verifies:

- all three stale attempts recover
- dry-run routes to review
- live and unknown route to uncertainty
- no application reaches `submitted` or `confirmed`
- replay creates no duplicates
- idempotency keys and attempt counters remain intact
- global submission and autopilot gates remain disabled

GitHub Actions retains the signed JSON report for 90 days under the `recovery-incident-drill-report` artifact.

## Rollback

Application data should not be deleted during rollback.

1. Disable autopilot and real submission.
2. Disable the affected platform or all platforms.
3. Roll back the application deployment to the last known-good commit.
4. Leave database rows, evidence, events, reviews, and notifications intact.
5. Run database migration checks against a copy before any schema downgrade.
6. Run the recovery drill and post-merge stabilization on the rollback commit.
7. Review every `applying` and `submission_uncertain` record created during the incident window.
8. Restore platform access incrementally, beginning with dry-run.

## Exit criteria

An incident is closed only when:

- no stale `applying` rows remain
- every uncertain submission has an explicit review disposition
- duplicate-submission checks pass
- recovery drill passes
- adapter health has no unresolved critical alert for the affected platform
- real submission remains disabled unless the adapter's supervised release gates are independently satisfied
