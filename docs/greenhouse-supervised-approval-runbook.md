# Greenhouse supervised submission approval runbook

This runbook defines the only supported path for a Greenhouse real-submission pilot. It does not authorize unattended or autonomous submission.

## Safety boundary

A Greenhouse live worker run requires all three gates:

1. `ALLOW_REAL_APPLICATION_SUBMIT=true`
2. `GREENHOUSE_SUPERVISED_PILOT_ENABLED=true`
3. One active, short-lived approval bound to the exact application payload

The approval is one-time. It is consumed before the worker starts. A crash, timeout, or retry therefore requires a fresh user approval.

All flags remain `false` outside a tightly supervised execution window.

## Approval scope

Each approval is bound to:

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

Any change to the target, résumé, cover letter, profile, or approved policies invalidates the approval.

## Preconditions

Before enabling the two runtime flags:

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

The worker revalidates every gate and hash, then consumes the approval before opening the live attempt.

### 4. Verify evidence

A successful result must have concrete confirmation evidence. A click without sufficient evidence must remain `submission_uncertain` and require review.

### 5. Close the execution window

Immediately restore:

```env
ALLOW_REAL_APPLICATION_SUBMIT=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
```

Restart the API and workers so cached settings are replaced.

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

- Missing approval: worker stops before changing the application state.
- Expired approval: worker stops and records the blocked attempt.
- Payload mismatch: approval is revoked and the mismatched hash fields are logged.
- Open manual review: approval and submission are blocked.
- Worker crash after consumption: do not retry automatically. Run recovery, inspect the application state and evidence, then issue a fresh approval only when safe.
- Uncertain confirmation: keep `submission_uncertain`; never mark submitted manually without evidence.

## Promotion boundary

This gate enables supervised evidence collection only. It does not promote Greenhouse to `human_reviewed_submit`, and it never authorizes `certified_autonomous`. Promotion still requires the complete 30 dry-run matrix, 10 independently reviewed supervised submissions, zero duplicates, zero false submitted records, and an explicit release approval reference.
