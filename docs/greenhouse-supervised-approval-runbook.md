# Greenhouse supervised submission approval runbook

This runbook defines the supported path for the Greenhouse reviewed real-submission pilot. It is an evidence-collection stage on the path from `dry_run` to `human_reviewed_submit` and ultimately `certified_autonomous`.

The reviewed pilot uses an exact one-time approval. A later autonomous release uses its own explicit adapter promotion and operating-profile controls rather than silently inheriting this pilot approval mechanism.

## Pilot boundary

A Greenhouse live worker run under this reviewed pilot requires all three gates:

1. `ALLOW_REAL_APPLICATION_SUBMIT=true`
2. `GREENHOUSE_SUPERVISED_PILOT_ENABLED=true`
3. One active, short-lived approval bound to the exact application payload

The approval is one-time. It is consumed before the worker starts. A crash, timeout, or retry therefore requires a fresh user approval during this pilot stage.

The pilot flags remain `false` outside a reviewed evidence-collection window. This does not prohibit a separately promoted autonomous release profile.

## Approval scope

Each pilot approval is bound to:

- authenticated user and application
- exact employer and role
- exact Greenhouse application URL
- application idempotency key
- profile snapshot hash
- résumé file hash
- cover-letter hash
- approved answer-policy payload hash
- combined payload hash
- expiry timestamp

Applicant answers, browser credentials, MFA codes, CAPTCHA responses, browser endpoints, and resume tokens are never stored in the approval record.

Any change to the target, résumé, cover letter, profile, or approved policies invalidates the pilot approval.

## Preconditions

Before enabling the two pilot flags:

- confirm the application is in `ready_to_apply`
- resolve every open manual-review task
- verify the résumé file is present and readable
- verify the exact employer, role, and Greenhouse URL
- verify the selected cover letter and approved answer policies
- verify the idempotency key and absence of a previous confirmed submission
- confirm the kill switch and recovery procedure are available
- stop for CAPTCHA, anti-bot, MFA, login, assessment, identity, or ambiguous legal boundaries

## API sequence

### 1. Inspect preflight

```http
GET /api/supervised-submissions/applications/{application_id}/preflight
```

`ready` must be `true`. Review every hash and target field before proceeding.

### 2. Issue exact approval

```http
POST /api/supervised-submissions/applications/{application_id}/approvals
Content-Type: application/json

{
  "confirm_employer": "Exact employer name",
  "confirm_role": "Exact role title",
  "confirm_application_url": "https://job-boards.greenhouse.io/...",
  "confirm_final_submit": true,
  "expires_in_minutes": 20,
  "notes": "Explicit supervised pilot approval"
}
```

The response returns an approval reference and hashes only. Treat the reference as an audit identifier, not a reusable authorization token.

### 3. Queue the supervised attempt

```http
POST /api/supervised-submissions/applications/{application_id}/approvals/{approval_reference}/submit
```

The worker revalidates every pilot gate and hash, then consumes the approval before opening the live attempt.

### 4. Verify evidence

A successful result must have concrete confirmation evidence. A click without sufficient evidence must remain `submission_uncertain` and require review.

### 5. Close the pilot execution window

Immediately restore:

```env
ALLOW_REAL_APPLICATION_SUBMIT=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
```

Restart the API and workers so cached settings are replaced.

This closes the reviewed pilot profile only. It does not prevent a later `certified_autonomous` profile from enabling the global real-submission and autopilot controls under its own release record.

## Revocation

```http
POST /api/supervised-submissions/applications/{application_id}/approvals/{approval_reference}/revoke
Content-Type: application/json

{
  "reason": "revoked_by_user"
}
```

Revocation is idempotent for an already terminal approval. A consumed approval cannot be reused.

## Failure handling

- Missing pilot approval: worker stops before changing the application state.
- Expired pilot approval: worker stops and records the blocked attempt.
- Payload mismatch: approval is revoked and the mismatched hash fields are logged.
- Open manual review: pilot approval and submission are blocked.
- Worker crash after consumption: do not replay the reviewed pilot automatically. Run recovery, inspect state and evidence, then issue a fresh pilot approval only when appropriate.
- Uncertain confirmation: keep `submission_uncertain`; never record success without evidence.

## Promotion path

This runbook collects the reviewed real-submission evidence required for `human_reviewed_submit`. Promotion still requires the complete 30 dry-run matrix, 10 independently reviewed submissions, zero duplicates, zero false submitted records, and an explicit release approval reference.

After that stage, Greenhouse is intended to progress toward `certified_autonomous` through the autonomy release gates, including replay recovery, handoff notifications, configured limits and kill switches, and incident-response validation.
