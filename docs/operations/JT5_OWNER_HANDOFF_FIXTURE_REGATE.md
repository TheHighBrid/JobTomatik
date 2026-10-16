# JT5 owner handoff fixture revalidation

Date: 2026-10-15

## Finding

PR #698 source `8b89a0e799a56698383b475c785e972657961f82` completed its full backend CI with 2,559 passed, 3 skipped and two failures. Both failures arise from `lever:fixture_regression_sha256_drift`: Phase 4 candidate selection and Day 35 operations rehearsal. The independent cross-adapter run also reports that same drift.

Both failures were reproduced locally before editing. The only added digest input is `backend/tests/test_lever_handoff_posting_routes.py`. Recomputing the Lever digest without this one new file reproduces the previous frozen value exactly. All five adapter source, retained evidence and manifest live-evidence digests, versions and maturity remain equal to their frozen values.

## Change and evidence

The current Lever fixture digest is updated with an appended, dated revalidation record. Original Day 28 hashes and all previous revalidation records remain intact. The new record retains both the previous and current fixture digest and references source workflow `38781876200`, artifact `11996447766`, SHA-256 `fbdf7e0ce09d681fe28f8d814cf143a69edc156a052fa570e356145a9d33e53b`.

That artifact documents the original failed drift check. It does not represent successful certification. The handoff posting-identity runtime repair lies outside the frozen adapter-source corpus and is covered separately by the handoff regressions.

## Local validation

Validation source: `975e13d3`, based on exact deployed source `8b89a0e799a56698383b475c785e972657961f82`. Python 3.12, repository-pinned backend dependencies, synthetic secret root, real submit and autopilot disabled.

- Before editing: both reported failing tests reproduced.
- After editing: 135 tests passed, including Phase 4 candidate gate, historical freeze provenance, Day 35 operations rehearsal, Lever posting identity, handoff UTC, leases, browser input boundaries, display lifecycle, final-action safety, reconciliation and OneHost recovery.
- Historical source provenance independently returned `verified=true`, with no errors.
- No runtime Python, frontend, workflow, adapter maturity or consequential-action setting changed.

The existing full backend CI result belongs to the parent source. Full CI on this follow-up must be evaluated separately. Local checks are synthetic and do not establish real employer challenge acceptance or confirmed submission.

## Deployment and remaining work

Current main inspected: `a4092528e0d472fc748ab6ebaffaa70407c06316`.

The OVH Desktop Commander execution request timed out. Public `/api/system/ready` returned the API's ready response. Live containers, application state and the expired Daniels Health attempt were not reverified during this continuation. No employer action, approval replay, application preparation or final Submit was executed.

Next: review this follow-up's exact-head CI and the parent Codacy findings, then reconcile the expired attempt using retained production evidence before preparing any fresh handoff. Keep #698 and its parents unmerged until their applicable gates pass.
