# Lever Phase A Certification

Lever remains at canonical maturity `dry_run` throughout Phase A.

## Purpose

Phase A gathers thirty qualifying dry runs across thirty distinct Lever sites where practical, including both `jobs.lever.co` and `jobs.eu.lever.co`. Every run must stop before final submit or at a declared retained-browser handoff.

## Automated exercise

The `Lever synthetic live exercise` workflow:

1. selects one current public Lever posting;
2. inspects official posting metadata and the hosted application form;
3. fills the form with a fictional certification profile in dry-run mode;
4. verifies résumé upload and form controls;
5. asserts `final_submit_clicked=false`;
6. exports one reviewable CSV candidate row with the retained report digest and immutable workflow-run reference.

The exporter never appends to `backend/evidence/lever-phase-a-baseline.csv`. An operator must review the report, digest, exact site, posting ID, region, employer, role, controls, upload evidence, and handoff state before accepting a row into the baseline.

## Qualification boundary

A candidate qualifies only when:

- the adapter is Lever at the expected version;
- the exact hosted `/apply` URL matches site, posting ID, and region;
- the report records no final-submit click;
- the outcome is `ready_to_submit` with `dry_run_passed`, or a declared manual challenge handoff with `needs_review`;
- the report artifact has a valid SHA-256 digest;
- the source reference is immutable;
- required unknown controls were not guessed.

## Certification command

From `backend`:

```bash
python scripts/certify_lever_pilot_readiness.py \
  --baseline evidence/lever-phase-a-baseline.csv \
  --ledger evidence/lever-pilot-ledger.jsonl \
  --json-output evidence-ci/lever-pilot-certification.json \
  --markdown-output evidence-ci/lever-pilot-certification.md
```

Add `--require-phase-a` only when the retained baseline is expected to meet all Phase A thresholds. A missing baseline counts as zero evidence, never success.

## Safety

The certification workflow keeps these values false:

- `ALLOW_REAL_APPLICATION_SUBMIT`
- `LEVER_SUPERVISED_PILOT_ENABLED`
- `AUTOPILOT_ENABLED`
- `ENABLE_RESUMABLE_HANDOFFS`

Phase A cannot issue an approval, queue a submission, click final submit, or promote Lever maturity.
