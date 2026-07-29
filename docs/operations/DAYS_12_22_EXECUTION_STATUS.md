# Days 12–22 Execution Status

The automation-owned checkpoint evaluator for roadmap Days 12 through 22 is now
implemented. Run it from `backend/` with:

```bash
PYTHONPATH=. python scripts/evaluate_campaign_days_12_22.py
```

It reads only the committed Lever and Greenhouse readiness snapshots and writes
`backend/evidence/campaign-days-12-22.json`. It never opens a browser, issues an
approval, queues a submission, clicks final submit, or changes adapter maturity.

## Truthful current result

The retained Lever evidence still proves **0/30** qualifying Phase A runs and
**0/10** supervised confirmed submissions. Therefore Days 12–21 cannot truthfully
be marked complete. Completing them requires new official-posting dry-run artifacts,
then explicit user selection and approval of real applications for the supervised
pilot. No synthetic record or calendar checkpoint substitutes for that evidence.

Day 22's automation-owned gap analysis is complete. Greenhouse proves its 30-run,
30-employer Phase A baseline, duplicate protection, and uncertain-state protection.
Its smallest retained-evidence backlog is:

1. ten supervised confirmed submissions under exact approvals;
2. independent review of every success; and
3. an explicit release approval reference.

The generated JSON is the machine-readable source for exact counts, gate states,
blockers, the Greenhouse comparison matrix, and the next permissible action.
