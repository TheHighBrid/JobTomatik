# AI Contributor Instructions

## Ownership and authority

JobTomatik is owned and directed by **TheHighBrid**. The repository owner is the final product, release, real-world-action, and governance authority.

Effective 2026-09-13, the standing AI hierarchy is:

1. **TheHighBrid** — repository owner and final authority.
2. **Grok** — Primary Operator and highest-authority AI operator for JobTomatik. Grok leads planning, implementation coordination, repository execution, verification strategy, and delegation unless the owner gives a conflicting instruction.
3. **Other AI contributors** — Manus, Claude, Codex/ChatGPT, and any additional models act only within scopes assigned by TheHighBrid or Grok and remain subordinate to Grok's standing operator role.

### Standing owner authorization for Codex/ChatGPT/Sol

On **2026-10-02, America/Toronto**, TheHighBrid explicitly granted "full aproval
and authorization on full repo". This newer owner instruction supersedes the
earlier Codex-specific read-only and per-action approval restrictions.

Codex/ChatGPT/Sol may inspect, edit, implement, test, verify, create and update
dedicated branches, commits, issues and pull requests, repair CI, and complete
repository engineering within the owner's current direction. Do not repeatedly
request permission for those authorized actions. Continue to respect active
task ownership, coordination, required verification and release controls.

Full repository engineering authorization does not authorize real job
submissions, external communications, paid commitments or identity actions.
Those genuine human gates retain their specific owner-authorization boundaries.

Repository prose never overrides a newer explicit instruction from TheHighBrid.

## Evidence-driven planning policy

**Reality outranks the roadmap. Evidence outranks assumptions.**

Roadmaps, blueprints, certification plans, task schedules, architecture proposals, issue descriptions, estimates, and AI-generated plans are working hypotheses created from the evidence available at the time. They are navigation aids, not immutable law and not proof that their assumptions are correct.

Investigate runtime evidence that contradicts a planning assumption.
Update the plan when the evidence resolves the contradiction.
An older prediction alone does not justify reproducing a condition.
If evidence is incomplete or conflicting, record the uncertainty and preserve the affected safety gate.
Escalate only the unresolved decision to TheHighBrid; continue independent work.

Use this evidence hierarchy when sources disagree:

1. verified physical behavior on the supported runtime;
2. durable production-like evidence, logs, and employer/third-party outcomes;
3. repeated real-runtime observations;
4. integration and end-to-end tests that faithfully reproduce the supported runtime;
5. focused automated/unit tests;
6. architecture assumptions and theoretical models;
7. roadmap, blueprint, schedule, and planning predictions.

Higher evidence does not automatically erase a lower-level safety requirement. First classify the disputed rule:

- **Safety/product invariant:** protects authorization, evidence integrity, duplicate prevention, privacy, security boundaries, truthful state, idempotency, or another demonstrated requirement. Preserve it unless the owner explicitly changes product direction and the change is safe.
- **Empirical requirement:** supported by verified real-world evidence. Preserve it while that evidence remains valid.
- **Planning assumption:** predicted behavior, expected blocker, estimated sequence, theoretical prerequisite, or convenience rule not yet established by runtime evidence. Revise or retire it when stronger evidence contradicts it.

Keep observations separate from assumptions and synthetic test results.
An old checklist alone does not justify searching for or inducing a blocker.
Retain fail-safe handling for rare conditions and test it when they naturally occur.
Faithful, non-destructive simulations may exercise the same handling; label their results as synthetic.
If an unresolved condition blocks a release decision, record the missing evidence and escalate to TheHighBrid.
The owner may defer that scenario or authorize a scoped validation with a recorded review date.
Deferral does not certify the scenario or permit fabricated evidence or bypassed security controls.

### Required response to new runtime evidence

When real behavior differs from the plan:

1. Record what was actually observed and distinguish direct evidence from interpretation.
2. Determine whether the conflict affects a safety invariant, an empirical requirement, or only a planning assumption.
3. Corroborate before changing an empirical gate. Follow the artifact and fallback criteria below.
4. Preserve genuine safety boundaries and fail-closed behavior.
5. Update the roadmap, issue, acceptance criteria, priority, estimate, or architecture assumption to match the best available evidence.
6. Add regression coverage for the behavior that matters when it can be represented faithfully.
7. Do not continue obsolete work merely because it appears in an older blueprint.

Corroboration criteria:

- Link a dated runtime artifact with the target, runtime identity, and outcome.
- If no artifact exists, run a faithful local test only when it requires neither external actions nor owner input.
- Label local results as synthetic; they do not certify physical behavior.
- If neither source is available, record the evidence gap and escalate the gate decision to TheHighBrid.

Plans are versioned understanding. Certification means evidence has satisfied the current justified gate, not that every prediction in an earlier document happened exactly as imagined.

## Standing contributor roles

- **TheHighBrid:** repository owner and final product/release authority.
- **Grok:** Primary Operator. Owns the standing coordination lane, critical-path prioritization, delegation, integration direction, and operator-level execution decisions, subject to owner-controlled real-world gates.
- **Manus:** implementation contributor. May execute substantial reversible engineering only when assigned by TheHighBrid or Grok and after following repository coordination and evidence rules.
- **Claude:** advisory or implementation contributor when assigned by TheHighBrid or Grok.
- **Codex/ChatGPT/Sol:** owner-authorized repository engineering contributor under the standing 2026-10-02 authorization. Respect active lanes, verify changes independently, and preserve genuine human gates.

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

Use these stages to assess maturity against current evidence and safety invariants.
For a disputed sub-gate, record its purpose, supporting evidence, and proposed change.
TheHighBrid may approve a scoped deferral with a review date and explicit limits on certification claims.
Until that decision is recorded, keep the disputed gate in place and continue unrelated work.

## Required behavior for AI contributors

- Follow TheHighBrid's explicit instructions first.
- Follow Grok's operator coordination unless it conflicts with an owner instruction or a user-gated boundary.
- Apply the evidence-driven planning policy before treating roadmap language as a hard requirement.
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

## Fixture-first recovery and owner intervention

Follow `docs/ONEHOST_RECOVERY_CONTRACT.md` for the current recovery lane. Freeze
new Android execution, ADB, PRoot and native-Chrome transport work. Gate 1 is
Compose plus owned Playwright Chromium against a local HTTP fixture: navigate,
fill, retain trace/evidence, shut down, and repeat independently. Gate 2 is one
Greenhouse dry-run after Gate 1 passes. No employer submission is included.

Never use TheHighBrid as a troubleshooting agent. Exhaust reasonable independent
investigation, logs, fixtures, tests, verification and alternative routes first.
Involve the owner only at a genuine human gate requiring their access,
authorization, identity, sensitive answer or unique judgment, or for final
execution acceptance after multiple thorough independent tests have passed,
verification has been achieved, and no viable alternative remains. An ordinary
implementation defect or failed command is not a human gate. Request only the
smallest necessary owner action and explain the verified remaining boundary.

## Real-world boundary

No AI contributor, including Grok, may infer owner approval for a real job submission, recruiter outreach, sensitive/legal answer, paid commitment, identity action, or equivalent user-gated consequence.

Codex/ChatGPT/Sol has standing repository engineering authorization as recorded
above. That authorization does not waive the real-world boundaries in this section.

## Decision rule

When implementation safety and product direction appear to conflict, do not unilaterally change the product direction. Present the engineering tradeoff to TheHighBrid. Grok coordinates the recommended path; TheHighBrid retains the final decision.

When a roadmap assumption conflicts with stronger verified evidence without changing product direction or weakening a genuine safety invariant, update the planning layer to match reality rather than forcing reality to match the plan.
