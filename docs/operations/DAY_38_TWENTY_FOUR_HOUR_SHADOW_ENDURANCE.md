# Day 38: Twenty-Four-Hour Shadow Endurance

Day 38 is a physical Android Runtime V2, full-stack, no-submit endurance stage. It is not a release authorization and it does not promote any ATS adapter.

## Entry prerequisite

Day 38 may be admitted only after a genuine Day 37 `shadow_run_8h` predecessor:

- completed at least 28,800 persisted seconds;
- passed the strict Day 37 endurance exporter;
- returned `day38_entry_eligible=true`;
- was retained as certification evidence;
- was independently reviewed and has `review_status=verified`;
- still re-passes the strict Day 37 certifier against its own original candidate revision.

For the physical Day 37 campaign that unlocked this stage, campaign #16 on revision `94198da8d824a869b27f0c805f0b83f178a44b69` produced strict report SHA-256 `4077bbf2ab2140db9582e1114d7658ee52e508144b6b2a08c4bea1328e08d8d8` and was independently verified as evidence #11.

## Launch contract

The Android 24-hour insertion boundary fails closed unless all of the following are true immediately before launch:

- target is exactly `shadow_run_24h`;
- requested duration is exactly 86,400 seconds;
- candidate revision equals the current managed runtime revision;
- a fresh Android Runtime V2 acceptance receipt exists for that exact revision;
- verified Day 37 predecessor admission succeeds;
- campaign policy readiness succeeds;
- real application submission remains disabled;
- real follow-up sending remains disabled;
- Lever remains version `1.1.0` at `dry_run` maturity with autonomous submission disabled;
- final-submit permission is false and no stop request exists at insertion.

The preflight UI is informative only. The ORM insertion boundary repeats the mutable launch checks so API or future internal callers cannot bypass them.

## Production-policy diagnostic telemetry

The actual shadow campaign continues to execute under the explicit `shadow_test` policy profile. That is intentional. Production quiet hours and application caps must not silently stop a certification campaign that is already guaranteed to be no-submit.

Each completed Day 38 cycle additionally retains a diagnostic-only evaluation of the production policy for the same account and cycle timestamp. This diagnostic:

- is marked non-authoritative;
- cannot authorize or block shadow execution;
- cannot enable submission or outreach;
- records what the production policy would have decided;
- records whether configured UTC quiet hours were active;
- records rolling previous-24-hours application count, cap, remaining capacity, threshold state, and the bounded application-id membership of that time window;
- records rolling previous-7-days capacity state.

The current production "daily" application cap is a rolling previous-24-hours window. It is not a UTC-midnight reset. The strict certifier therefore proves a real rolling-window rollover by showing that persisted application records present in the first diagnostic sample aged out of the window by the final sample. It does not require a below-cap to over-cap threshold crossing, because no-submit shadow applications themselves are persisted Application rows and can keep the raw production counter above the cap for the whole test.

## Strict Day 38 certification requirements

A completed campaign is not Day 38 evidence merely because its generic Phase 11 card is green. The strict Day 38 exporter additionally requires:

- persisted elapsed time of at least 86,400 seconds;
- retained Phase 11 report elapsed time of at least 86,400 seconds;
- exact retained report hash and timestamp consistency;
- exact candidate revision match;
- continuous cycle coverage;
- process-memory telemetry;
- stable worker process identity;
- zero cycle failures;
- zero duplicate tasks and application references;
- zero false submitted status;
- zero runaway retry;
- zero unexplained records;
- zero policy escapes;
- no active application work at certification;
- reconciled browser cleanup;
- acceptable notification quality;
- verified Day 37 predecessor still valid;
- diagnostic production-policy evidence on every completed cycle;
- configured quiet-hours transition observed across the 24-hour window;
- stable rolling-24-hours cap configuration and exact rolling-window semantics;
- policy diagnostics spanning at least 23 hours of the physical campaign;
- at least one persisted application that was inside the first rolling-24-hours sample aging out by the last sample;
- circuit breaker clear at certification;
- real submission and follow-up send still disabled;
- frozen and live Lever manifests still at `1.1.0 / dry_run`;
- all inherited Phase 11 quality gates still true.

A passing strict report sets `day39_entry_eligible=true`. It still does not authorize live submission, outreach, maturity promotion, or release.

## Physical post-run export

Run the exporter from the actual Ubuntu PRoot runtime checkout, not the separate native Termux checkout:

```bash
proot-distro login ubuntu --shared-tmp -- bash -lc '
cd /root/JobTomatik/backend &&
export JOBTOMATIK_RUNTIME_MODE=android_managed &&
.venv/bin/python scripts/export_day38_shadow_endurance.py \
  --session-id <SESSION_ID> \
  --verification-revision <DAY38_RUNTIME_SHA>
'
```

The exporter is post-run only. It does not start, advance, repair, finalize, inject into, or review a campaign.

Required compact result:

```json
{
  "passed": true,
  "day39_entry_eligible": true
}
```

The full report is written by default to:

```text
/root/JobTomatik/backend/evidence/day38-twenty-four-hour-shadow-endurance.json
```

Only after that strict pass may the retained `shadow_run_24h` evidence be independently reviewed for the next stage.

## Safety invariant

Throughout Day 38:

- `ALLOW_REAL_APPLICATION_SUBMIT=false`;
- `ALLOW_REAL_FOLLOWUP_SEND=false`;
- submission authorization remains false;
- outreach authorization remains false;
- adapter promotion authorization remains false.

Day 38 measures reliability. It does not spend real submission authority to prove that reliability.
