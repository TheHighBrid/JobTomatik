# Days 12–22 Execution Status

The read-only checkpoint evaluator consumes three retained inputs:

1. `backend/evidence/lever-pilot-readiness.json`
2. `backend/evidence/lever-phase-b-launch.json`
3. `backend/evidence/greenhouse-phase-a-readiness.json`

Run it from `backend/` with:

```bash
PYTHONPATH=. python scripts/evaluate_campaign_days_12_22.py
```

It writes `backend/evidence/campaign-days-12-22.json`. The evaluator never opens a
browser, issues an approval, queues a submission, clicks final submit, or
changes adapter maturity.

## Safety-critical completion rules

- Day 13 requires the dry-run and distinct-site targets plus proof that every
  CAPTCHA, MFA, login, or anti-bot encounter remained
  `manual_challenge_handoff + needs_review`.
- Day 15 is derived from the separate retained launch input. Readiness-summary
  counters cannot substitute for exact user selections, read-only dossier
  hashes, or successful no-submit previews.
- Days 16 through 20 count only distinct supervised submissions with strong
  confirmation evidence and completed independent review. A queued task,
  browser completion state, user report, synthetic preview, or unreviewed
  receipt does not count.
- Day 21 remains a separate promotion decision. Completion of Phase A or Phase B
  cannot silently change canonical maturity.
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

The retained Day 15 launch set currently contains:

- `D8-026`: Cin7, Customer Success Manager, Toronto, CAN
- `D8-028`: PocketHealth, Customer Success Manager, Greater Toronto Area

Both dossiers deliberately retain `synthetic_profile: true` Phase A previews.
They prove that the exact frozen postings reached a safe no-submit boundary.
They do not represent the repository owner's real profile, résumé, cover
letter, answer-policy payload, or permission to submit.

## Day 16 real-payload approval boundary

Before either selected application can receive a one-time supervised approval,
the authenticated runtime must build a fresh submission snapshot from the real
application records and current user-owned data. The preflight binds the exact:

- employer, role, canonical application URL, platform, and adapter version;
- current official Lever posting identity and target identity hash;
- application and user IDs plus submission idempotency key;
- profile snapshot hash;
- résumé file hash;
- cover-letter hash;
- approved answer-policy payload hash;
- combined payload hash;
- unresolved manual-review count and current application state.

The preflight must fail closed when the posting changed, the application is not
`ready_to_apply`, a manual review remains open, the résumé is missing, the
idempotency key is absent, the exact target identity is unverified, or the
required live and Lever pilot controls are disabled.

A one-time approval must then match the exact employer, role, and canonical URL,
explicitly confirm the final-submit intent, and remain bound to every retained
payload hash. Any payload drift, target drift, expiry, replacement approval, or
feature-gate change invalidates it before queueing.

After execution, Day 16 still requires strong confirmation evidence and an
independent review for each of two distinct applications. An approval or queue
receipt alone never advances the checkpoint.

## Truthful current result

At `main` SHA `1175119a3dc787e14cc2d61aada874d4a66b41b4`, retained evidence reports:

- Lever Phase A: **30/30** qualifying dry runs across **30 distinct sites**;
- regions covered: global and EU;
- preserved manual-challenge boundaries: **1**, with **0** violations;
- Day 15 selected applications: **2**;
- valid read-only approval dossiers: **2**;
- successful no-submit previews: **2**;
- supervised confirmed submissions: **0/10**;
- Day 16 progress: **0/2**;
- canonical Lever maturity: `dry_run`;
- promotion ready: `false`;
- final submit, submission queueing, and approval issuance by the checkpoint
  evaluator: `false`.

Therefore Days 12, 13, 14, and 15 are complete. Days 16 through 22 remain
blocked by retained evidence requirements, exact user approval gates, and the
separate maturity or release decisions documented in the generated campaign
artifact.

## Next action

1. Materialize the two selected roles as real user-owned application records.
2. Resolve all required non-sensitive and user-controlled answers without
   inferring legal, identity, demographic, salary, or other consequential data.
3. Run a fresh authenticated preflight for each application and present its
   exact real-payload hashes and blockers to the repository owner.
4. Obtain a separate explicit one-time approval for each exact application.
5. Execute only the approved supervised submission, stop on any drift or human
   verification boundary, retain strong confirmation evidence, and complete
   independent review before crediting Day 16.
