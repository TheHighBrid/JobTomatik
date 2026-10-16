# JT5 outcome recovery

This recovery action resolves an existing uncertain attempt. It does not submit,
publish a task, create an approval, enable a release flag, or contact an employer.
An unknown outcome remains blocked. Changing an application's display status is
not proof of an employer outcome.

## Supported findings

| Finding | Required basis | Saved result |
| --- | --- | --- |
| Confirmed | Current, sufficient retained confirmation for this application and attempt, with the exact evidence snapshot reviewed | Same attempt succeeds; application becomes confirmed; later owner history is preserved |
| Not submitted | Authenticated owner's explicit verification from an authoritative employer response or portal, with reference and review notes | Same attempt becomes a pre-submit failure; a separate Apply action may reserve a new attempt |
| Still unknown | No authoritative finding available | No resolution; no retry |

Non-submission is an **owner-reviewed external finding**, not independently
verified computer evidence. A missing email, missing screenshot, timeout,
rejected confirmation record, or lack of response does not establish it.
Keep sensitive answers, passwords, tokens and raw applicant payloads out of the
reference and notes. No live outcome is resolved by this implementation's tests.

## Owner flow

Open the application with an uncertain JT5 attempt and use **Resolve the prior
outcome**. Review the retained confirmation, or identify the employer verification
and explain what it establishes for the exact application. Record only a verified
finding. If neither finding is established, leave **Outcome remains unknown**.

Recording non-submission requires a reachable, idle sole OneHost worker and no
active retained handoff or unrelated review. Existing sufficient submission
evidence and later owner history block a contradictory non-submission finding.
An unreachable or busy worker preserves the retry block. Queued messages for a
closed attempt cannot claim it again. Recovery does not click Apply afterward.

## API and audit

- `GET /api/applications/{id}/jt5/reconciliation` reads the latest attempt and
  eligible confirmation snapshots; it performs no browser or worker operation.
- `POST /api/applications/{id}/jt5/reconcile` locks the owned application and
  exact attempt. Only the latest uncertain JT5 attempt, or a queued JT5 attempt
  with an uncertain broker publication, is eligible for a first resolution.
- The request binds the exact attempt, outcome, evidence reference, evidence
  snapshot where relevant, review notes and explicit verification.
- The attempt retains the original result and an immutable resolution receipt
  with reviewer, timestamp and request hash. Application events retain the audit
  link. Exact request replay returns the receipt without a second state change;
  a conflicting decision is refused.
- Old evidence, changed snapshots, another application's evidence, withdrawn
  records, non-JT5 attempts and stale attempt references fail closed.
- A browser result arriving after its checkpoint was closed cannot rewrite the
  saved outcome. Its observed classification and artifact references are kept in
  a separate late-result event for investigation.

The operation uses existing tables and lifecycle transitions. It does not reset
consumed approvals, remove duplicate identities, promote adapters, alter pilot
counts or certify an autonomous release. Legacy operator-assisted handoffs keep
their existing recovery path; this action does not reinterpret them as JT5 runs.

## Verification

Use `backend/tests/test_jt5_outcome_resolution.py` with the existing JT5 worker,
reservation, isolation and stale-attempt tests. Browser verification must use
synthetic API responses and assert that recovery never sends Apply or Submit.
Production deployment requires the tested exact source revision, existing CI
and independent integration review. Never use a real application to test this
operation or resolve an uncertain production record merely to unblock rollout.
