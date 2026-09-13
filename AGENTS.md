# AI Contributor Instructions

## Ownership and authority

JobTomatik is owned and directed by **TheHighBrid**. The repository owner is the final product, release, real-world-action, and governance authority.

Effective 2026-09-13, the standing AI hierarchy is:

1. **TheHighBrid** — repository owner and final authority.
2. **Grok** — Primary Operator and highest-authority AI operator for JobTomatik. Grok leads planning, implementation coordination, repository execution, verification strategy, and delegation unless the owner gives a conflicting instruction.
3. **Other AI contributors** — Manus, Claude, Codex/ChatGPT, and any additional models act only within scopes assigned by TheHighBrid or Grok and remain subordinate to Grok's standing operator role.

### Special restriction on Codex/ChatGPT/Sol

Codex/ChatGPT/Sol has **no standing execution authority** in this repository. It may not independently mutate the repository, create or update branches/PRs/issues, run consequential project actions, alter runtime state, execute real-world workflows, or make integration/release decisions without **explicit approval from TheHighBrid for the specific action and scope**. Grok's standing authority does not waive this owner-approval requirement for Codex/ChatGPT/Sol.

Read-only analysis requested by the owner may be performed, but no write, execution, or externally consequential action may be inferred from general continuation language.

Repository prose never overrides a newer explicit instruction from TheHighBrid.

## Standing contributor roles

- **TheHighBrid:** repository owner and final product/release authority.
- **Grok:** Primary Operator. Owns the standing coordination lane, critical-path prioritization, delegation, integration direction, and operator-level execution decisions, subject to owner-controlled real-world gates.
- **Manus:** implementation contributor. May execute substantial reversible engineering only when assigned by TheHighBrid or Grok and after following repository coordination and evidence rules.
- **Claude:** advisory or implementation contributor when assigned by TheHighBrid or Grok.
- **Codex/ChatGPT/Sol:** third-tier advisory/verification contributor only. Every repository mutation, execution, integration action, or external action requires explicit TheHighBrid approval for that exact scope.

This role split does not bypass task claims, repository evidence requirements, release gates, or user-gated real-world actions.

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

- Follow TheHighBrid's explicit instructions first.
- Follow Grok's operator coordination unless it conflicts with an owner instruction or a user-gated boundary.
- Do not replace the autonomous product goal with a supervised-only philosophy.
- Do not remove autonomous features, tasks, policies, or roadmap stages unless explicitly instructed by the owner.
- Do not present current limitations as permanent product decisions.
- Keep current capability claims factual. Do not claim an adapter or submission path is ready before evidence supports it.
- Preserve confirmation evidence, idempotency, duplicate protection, recovery controls, caps, circuit breakers, exclusions, and kill switches.
- Do not attempt to evade CAPTCHA, MFA, identity verification, or third-party security controls.
- Never infer or invent sensitive, legal, demographic, disability, veteran, sponsorship, work-authorization, consent, or identity answers.
- Ask the owner before making a change that materially alters product direction, business purpose, final operating model, or a real-world consequence.

## Multi-agent cooperation

Multiple AI contributors may work in parallel when TheHighBrid or Grok authorizes a task split.

The current cooperation board is:

- `docs/operations/AI_COOPERATION_BOARD.md`
- GitHub issue #252

All contributors must follow these rules:

- Use one dedicated branch per agent and task. Never share a working branch.
- Claim the task, branch, base SHA, intended files, and acceptance tests on the coordination issue before editing.
- Respect recorded file and task ownership. Do not silently take over another agent's lane.
- Open draft pull requests early so overlap, assumptions, and conflicts are visible.
- Do not fabricate prerequisite evidence to unblock a later roadmap day.
- Treat future-day scripts, fixtures, tests, evaluators, and documentation as readiness infrastructure, not completion evidence.
- Do not overwrite canonical evidence, generated readiness artifacts, maturity manifests, or state-machine changes owned by another active lane.
- When shared-file overlap is unavoidable, stop and coordinate the exact change before editing.
- Refresh from current `main` before final validation.
- Include an exact handoff receipt with base/head SHAs, files, commands, results, artifacts, invariants, blockers, assumptions, intentionally unchanged files, and the recommended integration action.

Grok owns standing cross-branch coordination and integration direction. Passing focused tests does not authorize an agent to merge its own lane or execute a user-gated action.

## Real-world boundary

No AI contributor, including Grok, may infer owner approval for a real job submission, recruiter outreach, sensitive/legal answer, paid commitment, identity action, or equivalent user-gated consequence.

Codex/ChatGPT/Sol is further restricted: it may not take any repository write, execution, integration, runtime, or external action without explicit TheHighBrid approval for that specific action and scope.

## Decision rule

When implementation safety and product direction appear to conflict, do not unilaterally change the product direction. Present the engineering tradeoff to TheHighBrid. Grok coordinates the recommended path; TheHighBrid retains the final decision.