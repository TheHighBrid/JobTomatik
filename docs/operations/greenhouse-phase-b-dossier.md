# Greenhouse Phase B candidate dossier

The candidate dossier is a read-only review object for one existing Greenhouse application.

It does not rank jobs, select an employer, issue an approval, enable a feature flag, open a browser, bypass a challenge, or queue a submission.

## Purpose

Before a supervised pilot attempt, the operator must verify the exact employer, role, URL, résumé, cover letter, answer-policy payload, duplicate-prevention key, unresolved review state, feature-flag scope, and retained evidence boundary.

The dossier puts those checks into one sanitized JSON snapshot with a deterministic SHA-256 digest.

Endpoint:

`GET /api/supervised-pilot/applications/{application_id}/dossier`

The application must belong to the authenticated user and must target Greenhouse.

## Included data

The dossier contains:

- exact employer, role, URL, host, and platform
- application and automation state
- submission-attempt count and idempotency-key presence
- hashes for the profile snapshot, résumé, cover letter, approved answer policies, and combined payload
- structural blockers and execution blockers
- current global and Greenhouse pilot flag state
- manual-review reason codes and statuses, without question text or answer content
- approval references, statuses, payload hashes, and expiry state
- submission-evidence types, sufficiency, hashes, and retention indicators
- independent-review references, decisions, and snapshot hashes
- audit event counts
- Phase A and Phase B readiness counters
- a deterministic dossier digest and download filename

## Excluded data

The dossier never copies:

- applicant phone, address, profile values, or credentials
- raw answer-policy values
- cover-letter text
- manual-review summaries or details
- confirmation text or captured HTML
- approval notes or metadata
- evidence-review notes or metadata
- application-event payloads

Only hashes, bounded status fields, references, counts, and retention indicators are exposed.

## Digest behavior

`dossier_sha256` is calculated from the sanitized dossier before the digest and filename fields are added.

Repeated reads produce the same digest while the exact payload and retained state are unchanged. Changes to the résumé, cover letter, approved answer policies, application state, approvals, evidence, independent reviews, or audit state change the digest.

The operator should re-fetch the dossier immediately before using the separate exact-approval panel. A changed digest requires a fresh review.

## Mandatory handoff boundary

The dossier records that bypass is forbidden and that execution must stop for:

- CAPTCHA
- anti-bot challenges
- MFA
- login requirements
- assessments
- identity verification
- ambiguous legal or consent boundaries

These are policy markers only. The dossier contains no challenge-solving mechanism.

## User interface

The Applications page shows the existing non-ranked Phase B roster. Selecting `Review dossier` loads only that application’s dossier and provides a local JSON download.

Opening or downloading a dossier does not create an approval and does not perform a submission.

## Promotion boundary

The dossier is preparation evidence only. Greenhouse remains `dry_run` until the required supervised submissions, concrete confirmation evidence, independent reviews, ledger records, and explicit release approval are complete.
