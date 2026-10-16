# JT5 simplified application execution

**Updated:** 2026-10-16. **Implementation:** integrated through #704. **Release control:** #706 merged and deployed. **Current candidate:** #711 late-result retention and PostgreSQL recovery locking.

## Product contract

One authenticated Apply action for a selected application reserves and dispatches a target-bound attempt. No additional legacy approval reference or pilot-lease ceremony is required for the ordinary JT5 path. Preserve authentication, ownership, atomic duplicate prevention and honest uncertain-outcome reconciliation.

Operational release controls, target identity, privacy and browser resource isolation still apply. In particular, `ALLOW_REAL_APPLICATION_SUBMIT` is a real release control. The #706 correction enforces API rejection before reservation/dispatch and a worker recheck; it is merged and deployed. The phrase “four protections” must not be interpreted as authorization to ignore this flag.

## Implemented path

| Component | Source |
|---|---|
| API Apply / read-only status | `backend/app/api/jt5_applications.py` |
| Decision gate | `backend/app/services/application_execution_gate.py` |
| Reservation | `backend/app/services/application_attempt_jt5.py` |
| Atomic claim / finalization | `backend/app/services/application_attempt_lifecycle_jt5.py` |
| Worker | `backend/app/tasks/jt5_execution.py` |
| Owner application UI | `frontend/src/pages/ApplicationDetail.jsx` |

The public reserve-only route was removed. Owner Apply and status polling use JT5. Legacy helpers still serve bounded operator/recovery callers; the ordinary Apply migration is not permission to delete every approval, handoff or scheduled-work component.

## Required behavior

- Authenticate and check ownership before disclosing outcomes or creating attempts.
- Reject disabled live submission before reservation/dispatch and recheck in the worker. This is implemented and deployed through #706; preserve the regression coverage.
- Preserve the resolved URL and application identity at reservation; reject target drift.
- Atomically claim at most one execution despite duplicate requests or queue delivery.
- Return retained confirmed or uncertain outcomes without automatic resubmission.
- Distinguish proven pre-submit failure from a possible final-action outcome. Preserve uncertainty when evidence is incomplete.
- Never treat withdrawal or a user-selected Applied status as employer confirmation.
- Keep retained owner handoff separate from the ordinary Apply action. Final human action remains explicit and durably checkpointed.
- Reconcile interrupted attempts at worker startup before new consumption, without replay.
- Run API and worker from the same verified implementation revision.

## Acceptance and remaining work

Integrated evidence includes auth/owner isolation, target binding, atomic claims, status contracts, Greenhouse/Lever controlled execution, queue and restart behavior, and native/mobile owner handoff. See [the evidence ledger](../EVIDENCE.md) for exact heads and check links.

Remaining acceptance includes final #711 verification/integration, evidence-backed same-attempt reconciliation, accurate known pre-browser failure classification, remaining branch delta review and supported-host/platform release evidence. See [current status](../PROJECT_STATUS.md).

## Migration discipline

Re-run repository-wide caller searches before any deletion. [The caller inventory](JT5_CALLER_INVENTORY.md) is a migration aid, not proof that a call site is unused. Preserve legacy operator/recovery paths until their current callers migrate and regression evidence supports removal. Historical plans to remove redundant UI ceremonies do not override a justified global release control.
