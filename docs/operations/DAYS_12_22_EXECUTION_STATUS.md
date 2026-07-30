# Days 12–22 Execution Status

The read-only checkpoint evaluator now consumes three retained inputs:

1. `backend/evidence/lever-pilot-readiness.json`
2. `backend/evidence/lever-phase-b-launch.json`
3. `backend/evidence/greenhouse-phase-a-readiness.json`

Run it from `backend/` with:

```bash
PYTHONPATH=. python scripts/evaluate_campaign_days_12_22.py
```

It writes `backend/evidence/campaign-days-12-22.json`. It never opens a
browser, issues an approval, queues a submission, clicks final submit, or
changes adapter maturity.

## Safety-critical completion rules

- Day 13 requires the dry-run and distinct-site targets plus proof that every
  CAPTCHA, MFA, login, or anti-bot encounter remained
  `manual_challenge_handoff + needs_review`.
- Day 15 is derived from the separate retained launch input. Readiness-summary
  counters cannot substitute for exact user selections, read-only dossier
  hashes, or successful no-submit previews.
- Day 22 remains blocked until every applicable Greenhouse certification gate
  and `human_reviewed_submit_ready` are true. Its backlog includes false-status,
  duplicate, uncertain-outcome, independent-review, count, and approval gaps.

## Lever Phase B launch evidence

`lever-phase-b-launch.json` contains one record per exact application. A record
counts toward Day 15 only when it has:

- a non-empty `application_id` and `platform: "lever"`;
- `selected_by_user: true` with a retained `selection_reference`;
- a read-only dossier with a valid SHA-256 digest and
  `one_time_approval_required: true`;
- a dry preview with `passed: true`, `outcome: "ready_to_submit"`, and
  `final_submit_clicked: false`.

Day 15 completes only when at least two distinct application IDs satisfy all
three evidence layers and Lever Phase A is complete.

## Truthful current result

The retained Lever evidence proves **0/30** qualifying Phase A runs and
**0/10** supervised confirmed submissions. The launch evidence currently
contains no selected applications. Greenhouse has Phase A coverage, but its
supervised-count, independent-review, release-approval, and final readiness
gates remain incomplete. Therefore Days 12–22 are all blocked by evidence or a
required user gate.
