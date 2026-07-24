# Greenhouse Pilot Ledger Runbook

This runbook explains how to retain and aggregate evidence for issue #24.

It does not itself execute live submission, change adapter maturity, or replace the approval requirements in `greenhouse-supervised-certification.md`. Its output supplies evidence for the next maturity stage.

## Workflow output

Run the **Supervised live Greenhouse certification** workflow with `exercise=true`.

Every successful exercise produces the artifact:

`greenhouse-supervised-live-certification-report`

The artifact contains:

- `greenhouse-live-certification.json`
- `greenhouse-live-certification-output.txt`
- `greenhouse-pilot-ledger.jsonl`
- `greenhouse-pilot-readiness.json`
- `greenhouse-pilot-readiness.md`

Only successful `exercise` entries with `final_submit_clicked=false` may count toward the 30-run matrix. Inspection-only entries do not count.

## Evidence-integrity behavior

The ledger builder rejects evidence when:

- the summary does not explicitly state `final_submit_clicked=false`
- any exercise record does not explicitly state `final_submit_clicked=false`
- a successful supervised record lacks confirmation evidence
- a supervised final-submit record lacks an approval reference
- the same `run_id` is encountered with conflicting evidence

The builder reports readiness evidence. Release controls such as `ALLOW_REAL_APPLICATION_SUBMIT`, scheduled autopilot, and adapter maturity are promoted separately through the owner's release decision.

## Aggregate retained reports

Download the retained `greenhouse-live-certification.json` files from completed workflow runs and run:

```bash
cd backend
python scripts/update_greenhouse_pilot_ledger.py \
  --input evidence/run-001/greenhouse-live-certification.json \
  --input evidence/run-002/greenhouse-live-certification.json \
  --operator "TheHighBrid" \
  --source-reference "issue-24-batch-001" \
  --ledger evidence/greenhouse-pilot-ledger.jsonl \
  --summary-json evidence/greenhouse-pilot-readiness.json \
  --summary-markdown evidence/greenhouse-pilot-readiness.md
```

Repeat `--input` for each retained source report.

To append later reports, reuse the same `--ledger` path. Exact duplicates are ignored. Conflicting records with the same `run_id` are rejected.

## Counting rules

The generated readiness report counts:

- qualifying dry-run records
- distinct employers represented by qualifying dry runs
- confirmed supervised submissions
- false submitted records
- duplicate submissions
- uncertain-outcome status violations
- successful submissions lacking independent review
- presence of the final release approval reference

Both of these must reach 30:

- qualifying dry-run records
- distinct dry-run employers

A single employer cannot fill multiple slots in the representative-employer gate.

## Promotion boundary

The report may state that `human_reviewed_submit` is ready only when every release gate passes and a release approval reference is supplied.

Example final reporting command:

```bash
cd backend
python scripts/update_greenhouse_pilot_ledger.py \
  --input evidence/latest-greenhouse-live-certification.json \
  --operator "TheHighBrid" \
  --source-reference "issue-24-final-review" \
  --ledger evidence/greenhouse-pilot-ledger.jsonl \
  --summary-json evidence/greenhouse-pilot-readiness.json \
  --summary-markdown evidence/greenhouse-pilot-readiness.md \
  --release-approval-reference "issue-24-approval-comment-or-review-reference"
```

The approval reference does not replace missing evidence. It is one of the required promotion inputs.

After `human_reviewed_submit`, the intended next stage is `certified_autonomous`, using the separate autonomy release gates and an explicit owner-approved release record.
