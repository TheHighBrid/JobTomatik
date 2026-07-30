# Lever Phase 2 Measurement Freeze

**Effective:** July 29, 2026
**Contract:** `2026-07-29.day7.3`
**Execution queue:** #161
**Platform tracker:** #86

## Truthful starting point

Lever Phase A started Phase 2 at **0 qualifying dry runs out of 30**. This is an immutable launch snapshot; the current verified count may advance without editing the freeze.

Two retained historical rows remain in the evidence baseline. Both are useful CAPTCHA and manual-boundary exercises, but neither reached the hardened qualifying outcome. They therefore contribute **zero** toward the 30-run quota.

| Measure | Starting value |
|---|---:|
| Qualifying Phase A dry runs | 0/30 |
| Retained historical safety rows | 2 |
| Historical rows receiving quota credit | 0 |
| Phase B confirmed supervised submissions | 0/10 |
| Canonical Lever maturity | `dry_run` |

This replaces the earlier interpretation that counted the two retained challenge rows as qualifying dry runs. The rows are not deleted or rewritten. Their safety value and provenance remain intact.

## Qualification rule

A Phase A record advances the count only when every condition below is true:

1. The exercise uses a synthetic profile in `dry_run` mode.
2. The reviewed posting is active, distinct, and represented by stable Lever site, posting ID, region, and canonical application URL metadata.
3. A successful official-posting inspection matches that exact target.
4. Workflow run, artifact ID, source reference, and SHA-256 provenance are immutable and valid.
5. The explicit adapter version equals the certified Lever adapter version used by the active contract.
6. The execution reaches `ready_to_submit` with outcome `dry_run_passed`.
7. `final_submit_clicked=false`.
8. No sensitive, demographic, consent, work-authorization, sponsorship, or legal answer was inferred or improvised.
9. No duplicate target, identity collision, target mismatch, or provenance conflict exists.
10. Readiness is recalculated from locked inputs and exactly matches the committed JSON and Markdown outputs.

A boolean stored in a CSV row cannot override these rules. The certifier hashes and parses the retained JSON artifact, then verifies one matching Lever exercise and one matching official-posting inspection for the exact target.

## Boundaries that receive no quota credit

CAPTCHA, MFA, login, anti-bot, assessment, legal-answer, sensitive-answer, ambiguous-control, unsupported-control, and uncertain-confirmation boundaries remain auditable safety evidence. They do not increase the 30-run count unless a separate complete run later satisfies the full qualification contract.

## No retroactive softening

Historical evidence may receive credit only if it independently satisfies this current contract. The contract will not be weakened to preserve an earlier count, and records will not be relabelled after the fact.

Any change to qualification logic, evidence schema, source manifest, adapter-version rule, target-identity rule, or readiness calculation during Days 8–14 requires:

- a dedicated reviewed pull request;
- explicit explanation of measurement impact;
- regeneration of all readiness outputs from locked inputs;
- exact-head CI; and
- an updated contract version.

Bug fixes may improve the adapter without changing measurement rules. A bug fix that changes whether existing evidence qualifies is a measurement change and follows the process above.

## Day 7.2 regression amendment

This amendment keeps the starting count at **0/30** and does not authorize any submission or maturity change. It closes three certification holes:

- the Phase 1 workflow now triggers when the frozen retained-artifact verifier changes;
- the Phase A exporter preserves a verifier-safe report path when the retained report is in a subdirectory of the output CSV location;
- roadmap Days 16–21 cannot pass unless the complete Lever Phase A gate is already true.

A dedicated regression contract now recalculates the committed readiness JSON and Markdown, exercises the cross-directory export layout, and rejects Phase B or promotion completion when Phase A is incomplete.

## Day 7.3 artifact-integrity amendment

This amendment repairs the retained Campaign Days 12–22 checkpoint after the Day 7.2 gate-order change. It does not alter the frozen **0/30** starting point, authorize submissions, or promote adapter maturity.

- `backend/evidence/campaign-days-12-22.json` is regenerated from the committed Lever and Greenhouse readiness snapshots.
- Days 16–21 retain `phase_a_complete: false` and the `complete Lever Phase A` blocker while Phase A remains incomplete.
- The regression contract now compares the committed campaign checkpoint JSON byte-for-byte with fresh deterministic evaluator output.
- The amended regression suite is re-locked under this contract version so exact-head CI rejects future artifact drift.

## Daily targets

| Campaign day | Frozen objective |
|---|---|
| Day 8 | Review at least 40 active postings and lock at least 30 viable distinct Lever sites |
| Day 9 | 5/30 qualifying dry runs |
| Day 10 | 10/30 qualifying dry runs |
| Day 11 | 15/30 qualifying dry runs |
| Day 12 | 20/30 qualifying dry runs |
| Day 13 | 25/30 qualifying dry runs |
| Day 14 | 30/30 and full Phase A certification |

The targets are planning checkpoints, not permission to accept weak evidence. A truthful lower count with a blocker report is preferable to fabricated or ambiguous progress.

## Frozen inputs and outputs

Canonical inputs:

Mutable evidence inputs:

- `backend/evidence/lever-phase-a-baseline.csv`
- `backend/evidence/lever-phase-a-sources.csv`
- `backend/evidence/lever-phase-a-artifacts/*.json`

Blob-locked qualification and certification rules:

- `backend/app/services/ats_lever.py`
- `backend/app/services/lever_phase_a_evidence.py`
- `backend/app/services/lever_pilot_ingestion.py`
- `backend/app/services/lever_pilot_ledger_boundary.py`
- `backend/app/services/lever_readiness_hardening.py`
- `backend/app/services/campaign_day_gates.py`
- `backend/scripts/export_lever_phase_a_record.py`
- `backend/scripts/certify_lever_pilot_readiness.py`
- `.github/workflows/lever-phase-a-certification.yml`
- `.github/workflows/phase-1-release-gate.yml`
- `backend/tests/test_phase_1_release_gate.py`
- `backend/tests/test_certification_regressions.py`

Generated readiness outputs:

- `backend/evidence/lever-pilot-readiness.json`
- `backend/evidence/lever-pilot-readiness.md`
- `backend/evidence/campaign-days-12-22.json`

## Safety and promotion boundary

Phase 2 does not authorize live submission or adapter promotion. The following remain disabled:

```text
AUTOPILOT_ENABLED=false
ALLOW_REAL_APPLICATION_SUBMIT=false
LEVER_SUPERVISED_PILOT_ENABLED=false
ENABLE_RESUMABLE_HANDOFFS=false
```

Lever remains `dry_run` after 30/30. Phase B supervised submissions and any later maturity promotion are separate gates with explicit user authorization.
