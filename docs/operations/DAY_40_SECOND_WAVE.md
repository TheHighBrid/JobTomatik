# Day 40: Bounded Live Pilot, Second Wave

Day 40 is a continuation gate, not permission to increase autonomy casually. The first live wave from Day 39 must be complete, reconciled, and free of critical defects before another bounded window can be authorized.

## Entry contract

A Day 40 second wave is blocked unless the retained Day 39 first-wave report proves:

- completed status;
- exact release-candidate revision and Lever `1.1.0` binding;
- one or two attempted applications only;
- every attempt durably accounted for;
- zero critical defects;
- zero duplicate submissions;
- zero false submitted states;
- zero wrong targets;
- zero guessed required answers;
- zero ambiguous confirmations;
- zero breaker trips and policy escapes;
- zero unresolved outcomes;
- confirmation evidence reconciliation complete;
- attempt reservations remained non-reclaiming.

The second wave must remain on the same promoted exact revision. A code change between waves requires a new exact-head promotion and cannot inherit the previous live authority.

## Separate second-wave authorization

The Day 39 live-window authorization is not reused. Day 40 requires a new bounded owner authorization because the first wave is evidence, not an unlimited license.

The new request is limited to at most two attempts and at most a 12-hour window. Before persistence, the read-only admission evaluator additionally requires:

- Lever remains `1.1.0 / certified_autonomous`;
- no live window is active;
- real submission is disabled between waves;
- real follow-up sending remains disabled;
- the global kill switch is clear;
- production policy is ready and outside quiet hours;
- daily and weekly capacity cover the requested attempt cap;
- queue prioritization, cap enforcement, follow-up scheduling, and confirmation reconciliation surfaces report ready.

The exact acknowledgment is:

```text
AUTHORIZE SECOND WAVE LEVER 1.1.0 <REVISION12> <ATTEMPT_CAP>
```

The evaluator may return `second_wave_authorization_eligible=true`, but it never persists authority or enables submission.

## Second-wave exercise requirements

The real Day 40 wave must exercise:

- queue prioritization;
- production cap enforcement;
- follow-up scheduling without silently enabling real follow-up sending;
- platform confirmation evidence reconciliation;
- confirmation email or portal comparison when available, or a retained explanation that no external confirmation source was available.

## Strict Day 40 certification

`build_day40_second_wave_certification` must pass before Day 41 begins. It requires:

- exact verification revision;
- completed second wave;
- attempted count within the authorized cap;
- every attempt accounted for;
- sustained zero critical defects;
- sustained zero duplicate submissions;
- sustained zero false submitted states;
- zero wrong targets, guessed required answers, ambiguous confirmations, breaker trips, policy escapes, and unresolved outcomes;
- queue prioritization exercised;
- cap enforcement exercised;
- follow-up scheduling exercised;
- confirmation evidence reconciled;
- external confirmation comparison accounted for;
- non-reclaiming attempt reservations preserved;
- the live window closed after the wave;
- real application submission disabled after the wave;
- real follow-up sending disabled.

A passing report sets `day41_entry_eligible=true`.

## CI boundary

The Day 40 tooling workflow proves only that admission and certification logic are reproducible. CI explicitly records:

```json
{
  "real_second_wave_claimed": false,
  "day40_complete": false,
  "day41_entry_eligible": false
}
```

Synthetic CI output must never be used as live-pilot evidence.

## Safety rule

Stop the live wave immediately on any duplicate, wrong target, guessed required answer, ambiguous confirmation, circuit-breaker trip, loss of exact runtime identity, or policy escape. Do not weaken the certification gate to rescue a failed live wave.
