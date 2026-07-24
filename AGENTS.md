# AI Contributor Instructions

## Ownership and authority

JobTomatik is owned and directed by **TheHighBrid**. The repository owner defines the product goal, acceptable operating model, priorities, and final scope.

AI assistants, coding agents, reviewers, and automation tools are implementation collaborators. They are not product owners and must not silently redefine the project.

## Non-negotiable product direction

The final JobTomatik goal is a **fully autonomous job-hunt system** capable of:

- continuous job discovery and ranking;
- autonomous application preparation;
- autonomous listing-to-employer target resolution;
- autonomous completion of certified ATS application paths;
- real application submission;
- evidence-backed confirmation;
- duplicate prevention, recovery, tracking, and follow-up.

The supervised workflow in version 1 is a development and rollout stage. It is not the permanent ceiling of the project.

## How to interpret release gates

Flags such as:

```text
ALLOW_REAL_APPLICATION_SUBMIT
AUTOPILOT_ENABLED
ENABLE_RESUMABLE_HANDOFFS
platform pilot flags
adapter maturity gates
```

are implementation and release controls. They must not be described as proof that JobTomatik is intended to remain supervised.

Adapters are expected to progress through:

```text
unsupported
→ detect_only
→ dry_run
→ human_reviewed_submit
→ certified_autonomous
```

## Required behavior for AI contributors

- Follow the repository owner's explicit instructions.
- Do not replace the autonomous product goal with a supervised-only philosophy.
- Do not remove autonomous features, tasks, policies, or roadmap stages unless explicitly instructed by the owner.
- Do not present current limitations as permanent product decisions.
- Keep current capability claims factual. Do not claim an adapter or submission path is ready before evidence supports it.
- Preserve confirmation evidence, idempotency, duplicate protection, recovery controls, caps, circuit breakers, exclusions, and kill switches. These controls support reliable autonomy rather than oppose it.
- Do not attempt to evade CAPTCHA, MFA, identity verification, or third-party security controls. Where a site explicitly requires a human action, preserve state and request the smallest necessary intervention.
- Ask before making a change that materially alters the project's product direction, business purpose, or final operating model.

## Decision rule

When implementation safety and product direction appear to conflict, do not unilaterally change the product direction. Present the engineering tradeoff and implement the option selected by the repository owner.
