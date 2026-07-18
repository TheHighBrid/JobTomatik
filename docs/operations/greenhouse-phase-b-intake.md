# Greenhouse Phase B exact-candidate intake

The Phase B intake creates one preparation-only JobTomatik application from an exact Greenhouse job selected by the authenticated user.

Endpoint:

`POST /api/supervised-pilot/candidates`

## Required fields

- exact employer
- exact role
- exact HTTPS application URL hosted on an official `greenhouse.io` domain

Optional fields:

- location
- operator notes
- source reference

The URL must identify one exact job through a `/jobs/` path, Greenhouse embedded application path, `gh_jid`, or job token. Generic company-board pages, non-HTTPS links, embedded credentials, non-standard ports, and non-Greenhouse domains are rejected.

## Created records

A successful intake creates or reuses:

- one manual-source `Job` record
- one user-owned `Application` in `preparing` state
- one deterministic submission idempotency key
- one `supervised_pilot_candidate_imported` audit event

Repeated intake of the same exact URL by the same user returns the existing records without creating duplicates.

## Actions that never occur

The intake does not:

- rank or recommend the job
- enable `ALLOW_REAL_APPLICATION_SUBMIT`
- enable `GREENHOUSE_SUPERVISED_PILOT_ENABLED`
- issue a submission approval
- generate or approve applicant answers
- generate a cover letter
- queue a Celery task
- open a browser
- click a final action
- change Greenhouse adapter maturity

The response and audit event explicitly record that no submission was queued, no approval was issued, and no runtime flag changed.

## Operator sequence

1. Paste the exact employer, role, and Greenhouse URL into the Phase B roster.
2. Open the generated dossier.
3. Prepare and verify the résumé, cover letter, answer policies, duplicate-prevention key, and manual-review state.
4. Use the separate exact-payload approval panel only after the dossier is correct.
5. Stop for CAPTCHA, anti-bot, MFA, login, assessment, identity verification, or ambiguous legal and consent boundaries.
6. Independently review concrete confirmation evidence before ingesting a supervised pilot record.

Greenhouse remains `dry_run` until all required supervised confirmations and the separate release approval are complete.
