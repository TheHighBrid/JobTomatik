# Days 12–22 Execution Status

## July 30 owner progress report

The owner reported 19 successful supervised submissions across 19 of the 30
candidate Lever sites and stated that their evidence received independent review.
That progress is retained in `backend/evidence/lever-days-12-22-owner-report.json`
and displayed by the campaign report.

The aggregate report is reconciliation input rather than a replacement for the
sanitized per-attempt ledger. Certification counts remain ledger-derived so the
system can verify target identity, exact approval consumption, evidence/payload
hashes, duplicate protection, and uncertain outcomes for every attempt. Import the
19 corresponding records into the canonical Lever pilot ledger and rerun readiness;
records that satisfy all gates will then count automatically toward Days 16–20.

The automation-owned checkpoint evaluator for roadmap Days 12 through 22 is now
implemented. Run it from `backend/` with:

```bash
PYTHONPATH=. python scripts/evaluate_campaign_days_12_22.py
```

It reads the committed Lever and Greenhouse readiness snapshots plus the optional
owner-progress report, then writes `backend/evidence/campaign-days-12-22.json`. It
never opens a browser, issues an approval, queues a submission, clicks final submit,
or changes adapter maturity.

## Truthful current result

The owner report records **19** supervised confirmations with **19** independent
reviews. The canonical ledger currently proves **0/30** qualifying Phase A runs and
**0/10** supervised confirmed submissions because the corresponding per-attempt
records have not yet been reconciled into it. Days 12–21 therefore remain pending
ledger verification; an aggregate claim or calendar checkpoint cannot substitute
for the target, approval, hash, duplicate, and outcome evidence of each attempt.

Day 22's automation-owned gap analysis is complete. Greenhouse proves its 30-run,
30-employer Phase A baseline, duplicate protection, and uncertain-state protection.
Its smallest retained-evidence backlog is:

1. ten supervised confirmed submissions under exact approvals;
2. independent review of every success; and
3. an explicit release approval reference.

The generated JSON is the machine-readable source for exact counts, gate states,
blockers, the Greenhouse comparison matrix, and the next permissible action.
