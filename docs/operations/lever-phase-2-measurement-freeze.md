# Lever Phase 2 Measurement Freeze

**Effective:** July 29, 2026  
**Contract:** `2026-07-29.day8-fail-closed-amendment`  
**Execution queue:** #161  
**Platform tracker:** #86

## Day 8 fail-closed amendment

The Day 8 full backend suite detected that the Day 7 lock file referenced an older Git blob for `backend/app/services/lever_readiness_hardening.py` than the stricter implementation already present on `main`.

The older blob was not restored because that would weaken the evidence gate. The current pinned implementation:

- evaluates failed official-posting inspection only for records that otherwise reached the `ready_to_submit` and `dry_run_passed` candidate pair; and
- detects duplicate identities across the complete Phase B ledger, rather than only rows already classified as successful.

The pinned blob is now `5d856e726f82bc3576a3026b56d0a791451641f5`.

This amendment changes **no** evidence count. Lever remains **0/30** qualifying Phase A dry runs and **0/10** independently reviewed Phase B submissions. No record receives retroactive quota credit.

## Truthful starting point

Lever Phase A starts Phase 2 at **0 qualifying dry runs out of 30**.

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

A boolean stored in a CSV row cannot override these rules. The certifier recalculates qualification from the complete evidence record.

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

- `backend/evidence/lever-phase-a-baseline.csv`
- `backend/evidence/lever-phase-a-sources.csv`
- `backend/app/services/lever_readiness_hardening.py`
- `backend/scripts/export_lever_phase_a_record.py`
- `backend/scripts/certify_lever_pilot_readiness.py`
- `.github/workflows/lever-phase-a-certification.yml`

Generated readiness outputs:

- `backend/evidence/lever-pilot-readiness.json`
- `backend/evidence/lever-pilot-readiness.md`

## Safety and promotion boundary

Phase 2 does not authorize live submission or adapter promotion. The following remain disabled:

```text
AUTOPILOT_ENABLED=false
ALLOW_REAL_APPLICATION_SUBMIT=false
LEVER_SUPERVISED_PILOT_ENABLED=false
ENABLE_RESUMABLE_HANDOFFS=false
```

Lever remains `dry_run` after 30/30. Phase B supervised submissions and any later maturity promotion are separate gates with explicit user authorization.
