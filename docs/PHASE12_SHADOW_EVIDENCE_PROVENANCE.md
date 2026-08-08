# Phase 12: Shadow Evidence Provenance Binding

## Purpose

Phase 12 closes the trust gap between the Phase 11 full-stack shadow campaign system and the Phase 10 certification ledger.

Phase 11 already creates durable 4-hour, 8-hour, and 24-hour no-submit campaigns and can bridge a completed qualifying campaign into an unreviewed `CertificationEvidence` row. Before Phase 12, however, the generic certification endpoint could also accept a hand-written `shadow_run_4h`, `shadow_run_8h`, or `shadow_run_24h` record when the caller supplied a measured duration plus a few no-submit metadata flags. Once independently reviewed, the Phase 10 evaluator did not reopen the underlying Phase 11 campaign because no campaign was required to exist.

That meant a correctly hashed timer claim could satisfy the same evidence type as a reconciled full-stack campaign.

Phase 12 makes the durable campaign the source of truth.

## Core rule

A shadow certification evidence row is a claim, not the authority.

For `shadow_run_4h`, `shadow_run_8h`, and `shadow_run_24h`, JobTomatik must be able to reopen exactly one account-owned `ShadowRunSession` and prove that the evidence still describes that completed campaign.

No linked campaign means no qualifying shadow evidence.

## Creation path

The generic endpoint:

```text
POST /api/certification/evidence
```

no longer accepts any shadow-run evidence type.

Shadow certification evidence can only be created through:

```text
POST /api/shadow-runs/{session_id}/record-evidence
```

The Phase 11 bridge already requires the campaign to be completed, bound to the current candidate revision, qualification-eligible, and backed by an intact retained report hash before it creates an **unreviewed** certification record.

The Certification Center therefore no longer exposes 4h / 8h / 24h shadow types in the manual evidence selector. Operators run the campaign in `/shadow-campaigns`, record the bridged evidence there, then independently review the resulting ledger record in `/certification`.

## Verification-time provenance

Before a shadow evidence row can transition from `unreviewed` to `verified`, Phase 12 reopens its linked campaign and checks all of the following.

### Evidence ownership and identity

- evidence is user-owned, not system-scoped;
- evidence owner matches the expected account;
- environment is exactly `full-stack-shadow`;
- `full_stack_shadow_session=true` is retained;
- a valid `session_id` is retained;
- source reference is exactly `full-stack-shadow-session:<session_id>:<report_sha256>`.

### Session identity

- linked session exists;
- session owner matches the evidence owner and current account;
- session status is `completed`;
- target evidence type exactly matches the evidence type;
- candidate revision exactly matches the evidence commit;
- session points back to this exact evidence row;
- exactly one shadow session points to the evidence row.

### Campaign execution

- requested duration is exactly 14,400 / 28,800 / 86,400 seconds for the selected target;
- at least one production scheduler cycle completed;
- zero campaign cycles failed;
- `final_submit_allowed=false` remained intact.

### Retained report identity

- final report exists;
- session report SHA-256 exists;
- embedded report hash recomputes correctly;
- session hash, embedded hash, and evidence metadata hash agree;
- report version is `phase11-full-stack-shadow-v1`;
- report session, revision, target, requested duration, and cycle counts match the durable session;
- report status is `completed`;
- `qualification_eligible=true` remains intact.

### Measured duration

- measured duration parses safely;
- evidence duration equals the retained report duration;
- duration meets the exact target minimum.

Malformed numeric data becomes a blocker. It does not raise a server error.

### Reconciliation and quality

The retained report must still say `reconciled=true` and every Phase 11 quality gate must remain true:

- duration satisfied;
- scheduler cycles completed;
- no cycle failures;
- discovery path observed;
- application path observed;
- no leaked or missing application records;
- no duplicate scheduler application references;
- no false submitted state;
- no runaway retry;
- no unexplained failures;
- no policy escape;
- no active application work.

### Safety boundary

The retained report must still prove:

- `final_submit_enabled=false`;
- `final_submit_clicked=false`;
- real submission remained disabled;
- dry-run was required;
- the shadow supervisor did not mutate runtime settings;
- `submission_authorized=false`;
- `outreach_authorized=false`.

Copied evidence metadata must also remain consistent with the durable session and report.

## Release-time revalidation

Verification is not a permanent trust stamp.

Every later certification-manifest / release-track evaluation reruns the same provenance checks. If the session, report, owner, linkage, cycle counts, safety state, or report hash drifts after review, the previously verified evidence becomes non-qualifying immediately.

Examples:

- a verified campaign later shows `cycles_failed=1`;
- report quality is mutated without a matching report hash;
- session ownership changes;
- two sessions point at one evidence row;
- report duration becomes malformed;
- retained session disappears.

All fail closed.

## Legacy evidence

Legacy or manually inserted shadow evidence is not grandfathered.

A historical row may still remain in the ledger for audit history, but it cannot satisfy a 4h / 8h / 24h gate unless it resolves to a valid Phase 11 full-stack campaign with the exact provenance described above.

This is intentional. Historical duration alone is weaker evidence than the current release gate requires.

## Policy-only rehearsal

`backend/app/services/shadow_rehearsal.py` remains available as a fast no-submit diagnostic harness.

It measures elapsed time and checks static runtime/ATS manifests. It does **not** exercise the production scheduler, discovery, or application-preparation path.

Its output now explicitly contains:

```json
{
  "certification_evidence_eligible": false,
  "certification_evidence_source": "full_stack_shadow_campaign_required"
}
```

Even when its local diagnostic `qualification_eligible` flag becomes true after four, eight, or twenty-four hours, the report cannot be submitted through the generic certification endpoint and cannot satisfy a release shadow gate.

This Phase 12 rule supersedes the older Phase 10 documentation language that described the policy-only timer harness as sufficient for 4h / 8h / 24h certification.

## Runtime controls remain independent

Phase 12 changes evidence trust only.

It does not change:

- `ALLOW_REAL_APPLICATION_SUBMIT`;
- `ALLOW_REAL_FOLLOWUP_SEND`;
- scheduler/autopilot enablement;
- global kill switch;
- platform disablement;
- ATS maturity;
- owner release authorization.

Recording, verifying, or revalidating shadow evidence never grants submission or recruiter-outreach authority.

## Regression matrix

Phase 12 adds explicit tests for:

- generic manual 4h / 8h / 24h POST rejection;
- valid Phase 11 bridge → independent verification → qualifying evidence;
- legacy/manual stored shadow row with no linked session;
- session cycle failure introduced after verification;
- final report tampering after verification;
- session owner drift;
- duplicate session-to-evidence linkage;
- malformed measured duration without a 500;
- system-scoped shadow claims;
- policy-only timer threshold crossing remaining ineligible for certification evidence.

## Operational sequence

A real shadow certification gate is now:

```text
1. Start exact-head full-stack shadow campaign
2. Run real scheduler/discovery/application-preparation path in dry-run mode
3. Reach target duration
4. Settle in-flight work
5. Pass Phase 11 reconciliation and safety gates
6. Retain hash-bound final report
7. Record campaign evidence through /shadow-runs/{id}/record-evidence
8. Independently review evidence in Certification Center
9. Revalidate campaign provenance on every release-readiness evaluation
10. Only then may the shadow prerequisite be qualifying
```

CI can prove this mechanism and its fail-closed behavior. CI does not fabricate a real 4-hour, 8-hour, or 24-hour production-like campaign history.
