# Durable Submission Identity and Idempotency

## Purpose

JobTomatik must never perform two terminal submission actions for one applicant and
one posting merely because discovery produced duplicate rows, a URL redirected,
a user double-clicked, a queue message was repeated, a worker restarted, a timeout
triggered retry machinery, or confirmation evidence was ingested twice.

This contract is intentionally stricter than a per-row random token. It creates three
durable layers of identity and replay control.

## 1. Posting identity aliases

Every application may own multiple user-scoped aliases:

- verified ATS platform, region, site, and posting ID;
- source-board external ID;
- canonical source-listing URL;
- canonical employer/ATS target URL combined with normalized employer and role.

The database uniquely assigns each alias to one application for one user. This means:

- changed URL, same verified posting: duplicate;
- redirect or tracking-parameter variation, same posting: duplicate;
- duplicate discovery rows for one posting: duplicate;
- same reusable URL, changed employer or role: distinct unless a stronger posting ID
  proves they are the same.

Aliases discovered later, including resolved employer targets and final confirmation
URLs, are claimed before the workflow may continue. A conflict becomes a safety review,
not a guessed merge and not another submission.

## 2. Exact approval and attempt binding

A supervised approval is bound to:

- authenticated applicant and application;
- employer and role;
- canonical application URL and posting identity;
- profile snapshot;
- résumé hash;
- cover-letter hash;
- approved answer-policy payload hash;
- adapter version;
- target identity hash;
- approval reference, timestamps, and one application idempotency key.

The queue creates a durable `SubmissionAttempt` before publishing a Celery message.
The record has unique constraints on approval reference, queue task ID, and application
attempt number.

The worker must atomically change the attempt from `queued` to `in_progress` before it
may consume approval or open the target. Exactly one worker can win that compare-and-swap.
Every other worker, retry, restart, or duplicate message returns the persisted attempt
as an idempotent replay without browser navigation or a final action.

## 3. Confirmation-evidence receipts

Confirmation pages, external application IDs, provider receipts, payload hashes, and
confirmation emails receive a deterministic receipt fingerprint. A fingerprint can be
attached only once.

- replay for the same application returns the existing evidence;
- replay against a different application is rejected as a conflict;
- a replay can never manufacture a second terminal transition.

## Retry policy

Dry-run workers may retain normal transient retry behavior.

A live worker that has claimed a one-time attempt never receives permission for another
final action. An exception after claim records the attempt as `uncertain`, suppresses
final-action retry, and requires evidence review or a fresh explicit approval. Framework
retry messages carrying the old attempt reference exit idempotently before browser work.

## Required invariants

1. One user and one durable posting identity map to at most one application.
2. One approval maps to at most one queue reservation.
3. One reservation can be claimed by at most one worker.
4. A consumed approval is never sufficient for another final action.
5. A successful or uncertain attempt never silently returns to `queued`.
6. One confirmation receipt maps to at most one application.
7. `submitted` and `confirmed` still require sufficient accepted evidence.
8. Real submission, autopilot, and adapter promotion defaults remain disabled.

## Day 5 assault matrix

The release gate exercises:

- request replay;
- double click;
- duplicate queue publication;
- two-worker concurrency;
- worker restart and stale replay;
- timeout/exception after attempt claim;
- changed URL for the same verified posting;
- the same URL used for a changed posting;
- confirmation-email replay;
- document, answer, adapter, and approval-context drift.
