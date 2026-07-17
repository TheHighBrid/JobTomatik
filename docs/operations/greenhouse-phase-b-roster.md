# Greenhouse Phase B technical roster

The roster is a preparation and visibility tool. It never selects a job, ranks an employer, issues an approval, or queues a submission.

## Ordering and selection

Greenhouse applications are displayed in stable application creation order. This is not a recommendation order. The operator must open and choose each exact application.

## Technical readiness

The roster separates two categories:

1. Structural blockers, such as a missing résumé, unresolved manual review, missing URL, missing idempotency key, or an application that is not `ready_to_apply`.
2. Execution flags, `ALLOW_REAL_APPLICATION_SUBMIT` and `GREENHOUSE_SUPERVISED_PILOT_ENABLED`, which remain disabled by default.

An application can be structurally ready while execution remains disabled.

## Progress

The roster reads canonical readiness and shows:

- Phase A qualifying dry runs
- Phase A distinct employers
- Phase B independently confirmed records
- remaining records toward the target of ten

Completed or already-ingested applications remain visible with explicit status so they are not silently selected again.

## Privacy and decision boundary

The roster does not display applicant answers, demographic information, legal declarations, credentials, or browser secrets. It does not evaluate job suitability or make employment decisions. The user still performs the exact employer, role, URL, payload, and final-action confirmation in the per-application supervised panel.

## Endpoint

`GET /api/supervised-pilot/roster`

The endpoint is authenticated and returns only the current user's Greenhouse applications.
