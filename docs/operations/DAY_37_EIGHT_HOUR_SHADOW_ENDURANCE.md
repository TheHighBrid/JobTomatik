# Day 37: Eight-Hour Unattended Shadow Endurance

Day 37 extends the physical-runtime no-submit campaign from four hours to one full
working-day window. It is a dependency-ordered certification stage, not permission to
skip Day 36 and not a claim that eight hours of wall-clock time alone proves readiness.

## Entry gate

Android `shadow_run_8h` admission requires all of the following:

- a retained user-owned `shadow_run_4h` evidence record;
- `status=passed` and `review_status=verified`;
- intact evidence payload hash and Phase 12 shadow provenance;
- exactly one linked completed Day 36 session;
- the real Day 36 endurance certifier still passes that predecessor session;
- the predecessor may be from its own older candidate SHA and is verified against that
  retained SHA rather than falsely requiring it to equal the newer Day 37 code;
- the current Day 37 candidate revision is known and matches the runtime revision;
- a fresh Android runtime-acceptance receipt matches the current process/artifact
  fingerprint and is no more than fifteen minutes old at launch;
- the requested duration is exactly 28,800 seconds;
- the full eight-hour policy window is ready;
- `ALLOW_REAL_APPLICATION_SUBMIT=false`;
- `ALLOW_REAL_FOLLOWUP_SEND=false`;
- Lever remains version `1.1.0`, maturity `dry_run`, with autonomous submission disabled.

Android `shadow_run_24h` remains hard-locked until the Day 38 stage is implemented and
its predecessor gate can validate a completed Day 37 run.

The ORM repeats the mutable Day 37 checks before insertion. Passing the UI/API preflight
therefore cannot bypass the database admission boundary.

## Exact launch phrase

After preflight passes, the operator must type the exact phrase shown by Shadow Campaign
Center:

```text
START FULL STACK SHADOW shadow_run_8h <candidate-revision-prefix>
```

The canonical cadence remains fifteen minutes unless a separately reviewed run plan
changes it. Only one active campaign is allowed for the account.

## Four bounded incident drills

Day 37 injects exactly one of each required incident into the real eight-hour session.
The drills are retained inside `ShadowRunCycle.observability_snapshot.day37_incident`.
A failed drill remains failed and is not automatically retried into a passing result.

| Earliest elapsed time | Incident | Production contract exercised |
| --- | --- | --- |
| 1:00 | source outage | one independent discovery source failure is bounded while another source result survives; raw exception text is not retained |
| 3:00 | browser crash/page loss | one JobTomatik-owned controlled page is destroyed, then a fresh controlled page is reacquired without terminating the externally owned Android browser process or touching unrelated tabs |
| 5:00 | stale posting | the production closed-listing detector returns `listing_closed`, `terminal=true`, `retryable=false` |
| 6:30 | ambiguous question | the production answer-policy resolver refuses autofill, generates no answer, and routes the unclassified question to `ambiguous_question` review |

The controlled source outage is injected into the same discovery result-folding function
used after production `asyncio.gather(return_exceptions=True)`. It does not intentionally
break a real third-party provider.

The browser drill never sends TERM/KILL to Chromium and never selects an existing user
tab. It exercises loss/reacquisition of JobTomatik-owned controlled pages only.

Each drill also records the current clustered-failure circuit-breaker decision. An
isolated controlled incident must not falsely trip the clustered breaker.

## Campaign qualification

The ordinary Phase 11 report must still qualify. Day 37 additionally requires:

- persisted elapsed time of at least 28,800 real seconds;
- retained-report elapsed time of at least 28,800 seconds;
- exact persisted/report timestamps;
- continuous cycle cadence;
- zero failed campaign cycles;
- memory telemetry across the run;
- one stable worker process identity across memory samples;
- zero duplicate cycle/application references;
- zero false submitted states;
- zero runaway retries;
- zero unexplained records;
- zero policy escapes;
- no active correlated application work after settling;
- reconciled browser cleanup;
- notification quality with no duplicate/noisy campaign notifications;
- all four Day 37 incidents present exactly once and in plan order;
- every incident occurred after its planned threshold and inside the session window;
- every recovery contract passed;
- no incident requested real submission, outreach, maturity mutation, or browser-process
  termination;
- the verified Day 36 predecessor remains valid at Day 37 certification time;
- the clustered circuit breaker is clear at certification;
- Lever still matches the frozen Day 35 `1.1.0` / `dry_run` candidate;
- final submit remained disabled.

Only then may the Day 37 certifier emit:

```text
day38_entry_eligible=true
```

## Post-run export

After the physical session is terminal and reconciled, export the retained evidence with:

```bash
cd backend
python scripts/export_day37_shadow_endurance.py \
  --session-id <SESSION_ID> \
  --verification-revision <EXACT_DAY37_RUNTIME_SHA>
```

The exporter is read-only with respect to campaign execution. It cannot create, advance,
inject, repair, or finalize a session. A non-passing report exits nonzero.

Default output:

```text
backend/evidence/day37-eight-hour-shadow-endurance.json
```

## CI boundary

`.github/workflows/day37-shadow-endurance-tooling-gate.yml` validates the implementation,
regressions, safety contract, exporter startup, and anti-counterfeit gate. Its own retained
JSON explicitly records:

```text
real_eight_hour_run_claimed=false
day37_complete=false
day38_entry_eligible=false
```

A GitHub Actions run, synthetic timestamps, fixture incidents, or a successful unit test
cannot substitute for eight hours of persisted physical-runtime evidence.

## Safety invariants

Throughout Day 37:

- real application submission stays disabled;
- real follow-up send stays disabled;
- recruiter outreach stays unauthorized;
- Lever maturity stays `dry_run`;
- no CAPTCHA, MFA, assessment, identity, or legal-answer boundary is bypassed;
- no adapter promotion is performed;
- no Day 38 / 24-hour campaign is admitted merely because Day 37 tooling exists.
