# Lever Post-Phase-B Promotion Decision

Date: 2026-09-16

Tracking issue: #503

## Decision summary

Phase B owner-reviewed objective completion has reached **10 / 10** on the frozen certification runtime.

The separate downstream feature-work lock is released because its threshold was **4 / 10** objective completions.

Lever canonical maturity is **not promoted by this record**. Keep the adapter fail-safe until the repository-defined maturity gate is independently proven in a dedicated promotion pull request.

## Why completion and maturity promotion are separate

The September completion sprint measures the owner-reviewed material objective at the retained final-submit-ready boundary. Accepted rows prove exact-target resolution, completed form filling, required-control and upload verification, no-duplicate safety, retained evidence, and no automated final submit.

Canonical `human_reviewed_submit` maturity is stricter. `backend/app/services/ats_maturity.py` requires a `human_reviewed_release` record with:

- `approved=true`;
- a non-empty `approval_reference`;
- `supervised_real_submission_pilot_complete=true`;
- `zero_false_positive_submitted_records=true`;
- `duplicate_prevention_verified=true`;
- `confirmation_evidence_verified=true`.

The campaign Day 21 gate additionally expects the canonical readiness evidence to report Phase B submission-confirmation gates complete, `promotion_ready=true`, and explicit separate promotion approval.

The 10/10 September sprint intentionally stopped before employer final Submit. It therefore must not be rewritten as ten real submitted-and-confirmed applications merely to satisfy the older promotion validator.

## Safety posture after Phase B

Keep all of the following fail-safe unless a later promotion PR proves the corresponding release gate:

- global real submission disabled;
- Lever automated pilot disabled;
- autopilot disabled;
- automated submit authority disabled;
- queue submit authority disabled;
- final employer Submit remains a human boundary;
- retained certification history is immutable.

## Downstream unlock

Day 39-42 adjacent engineering work may resume because the temporary Phase B feature-work lock has been satisfied and exceeded.

This unlock means implementation, tests, diagnostics, release preparation, shadow work, and other no-submit engineering may continue. It does **not** mean that the Day 39 live unattended pilot itself is authorized. That pilot still requires the separate post-shadow autonomous promotion and owner-authorized live configuration defined by the 42-day roadmap.

## Next execution lane

1. Resume the downstream Day 39-42 engineering backlog from current `main`.
2. Preserve the frozen certification runtime and completed Phase B rows without further mutation.
3. Keep Lever at its current canonical maturity until a dedicated promotion candidate has immutable evidence satisfying the release contract.
4. If real supervised submissions are later chosen for promotion evidence, collect them in a separate lane with confirmation evidence and independent review rather than altering the completed September sprint.

## Owner direction

The owner explicitly directed the project to proceed after Phase B completion. This record treats that direction as authorization to execute the post-Phase-B decision workflow and resume downstream engineering. It does not waive any repository-defined evidence gate for submission-capable maturity.


## September 18, 2026 owner amendment

The owner changed the Lever supervised promotion-evidence sample from ten genuine confirmed submissions to **three**.

This amendment changes only the sample-size threshold. It does not relax exact target binding, truthful answer policy, one-time approval, one final-submit action maximum, strong employer confirmation evidence, independent review, duplicate prevention, false-submission protection, or uncertain-outcome handling.

Current execution direction is to perform **three fresh supervised Lever submissions**. If a candidate expires or becomes unusable, replace that candidate rather than extending the quota beyond three.
