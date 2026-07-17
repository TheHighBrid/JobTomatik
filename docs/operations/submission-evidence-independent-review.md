# Submission evidence independent review

This gate sits after a supervised Greenhouse worker attempt and before an application is considered `confirmed`.

## Safety boundary

The review API does not open a browser, contact an employer, enable a feature flag, or submit an application. It reads retained evidence and stores only references, hashes, reviewer notes, and a decision.

A submit-button click is never sufficient evidence by itself.

## Acceptance requirements

An evidence record can be accepted only when all of these are true:

1. The application is `submitted`, `submission_uncertain`, or already `confirmed`.
2. A consumed exact-payload supervised approval exists.
3. The evidence is marked sufficient by the platform adapter.
4. The evidence type is a concrete confirmation type.
5. At least one concrete signal exists, such as confirmation text, an external application ID, a screenshot, or an HTML snapshot.
6. The operator types the exact employer, role, and evidence type.
7. The operator explicitly confirms that the evidence belongs to this application.
8. The acknowledgement is exactly `REVIEWED`.

Acceptance transitions the application to `confirmed` and creates an immutable review record.

## Rejection behavior

Rejected evidence never confirms an application. The application is routed to `submission_uncertain`, a manual-review task is created, and the operator receives a notification.

## Mutation protection

The review stores a SHA-256 snapshot of the evidence. Any later evidence mutation invalidates the review for pilot export. A new review is required.

## Pilot export

`GET /api/applications/{application_id}/supervised-pilot-record` exports a confirmed runtime application into the canonical supervised pilot ledger shape. Export requires:

- a consumed exact-payload approval
- a currently valid accepted evidence review
- a confirmed application state
- an idempotency key

The export contains hashes and evidence references, never raw applicant answers or browser credentials.

## Endpoints

- `GET /api/applications/{application_id}/evidence/{evidence_id}/review-preflight`
- `POST /api/applications/{application_id}/evidence/{evidence_id}/review`
- `GET /api/applications/{application_id}/evidence-reviews`
- `GET /api/applications/{application_id}/supervised-pilot-record`

This gate does not promote Greenhouse maturity and does not authorize unattended submission.
