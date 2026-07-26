# JobTomatik Product Direction

## Owner-defined goal

JobTomatik is being built to become a fully autonomous job-hunt agent. The target operating model is not limited to job discovery or application preparation. The mature system is intended to search, decide, prepare, apply, submit, confirm, recover, track, and follow up with minimal routine human operation.

## Final operating loop

```text
continuous job discovery
→ fit scoring and policy filtering
→ application target resolution
→ tailored résumé and cover-letter selection
→ certified ATS execution
→ truthful answer-policy execution
→ real submission
→ employer confirmation evidence
→ duplicate-safe tracking
→ follow-up and outcome learning
```

## Progressive implementation

The project reaches autonomy progressively rather than pretending unfinished paths are complete.

Adapter maturity:

```text
unsupported
→ detect_only
→ dry_run
→ human_reviewed_submit
→ certified_autonomous
```

Operational progression:

```text
manual launch
→ supervised preview
→ bounded reviewed submission
→ scheduled autonomous execution
→ continuous autonomous operation
```

Current maturity is evidence about implementation status. It is not a permanent restriction on the product's intended scope.

## Autonomy safeguards

Reliable autonomy includes controls that prevent false success and uncontrolled repetition:

- explicit target identity;
- truthful applicant data and answer policies;
- correct document selection;
- idempotency and duplicate prevention;
- employer confirmation evidence;
- retry and crash recovery;
- per-day, per-week, per-employer, and per-platform limits;
- quiet hours and exclusions;
- circuit breakers and kill switches;
- observable logs and incident rollback.

These mechanisms make autonomous operation trustworthy. They are not a replacement for the autonomous goal.

## Human-required third-party boundaries

JobTomatik does not attempt to evade CAPTCHA, MFA, identity checks, assessments, or platform security controls. When a third party explicitly requires a human action, JobTomatik may preserve the browser state, request the smallest necessary intervention, and resume automatically afterward.

A required verification handoff is an external platform boundary. It does not convert the overall project into a supervised-only product.

## Contributor authority

The repository owner decides the product direction. Contributors and AI coding agents should implement that direction, surface engineering tradeoffs, and keep capability claims factual. They must not silently redefine JobTomatik as permanently supervised or remove autonomous scope without explicit owner instruction.
