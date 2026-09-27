# JobTomatik Evidence-Driven Planning Policy

## Core rule

**Reality outranks the roadmap. Evidence outranks assumptions.**

JobTomatik plans are living models of the project, not immutable specifications of future reality. A blueprint may predict the work, but verified runtime behavior determines what the work actually is.

This policy exists because JobTomatik crosses browser automation, Android runtime behavior, third-party ATS products, employer-specific forms, security boundaries, human handoffs, and state reconciliation. Several of those systems are outside JobTomatik's control and cannot be completely predicted from static analysis or synthetic tests.

## What is authoritative

The repository distinguishes three kinds of rules.

### 1. Safety and product invariants

These remain hard constraints unless the repository owner explicitly changes the product direction and the resulting change is safe. Examples include:

- never claim a submission without sufficient evidence;
- preserve owner authorization for real-world consequential actions;
- prevent duplicate submissions;
- do not invent sensitive or legal answers;
- fail closed when the target or outcome is genuinely ambiguous;
- do not bypass CAPTCHA, MFA, identity checks, or third-party security controls;
- preserve evidence provenance and truthful application state.

### 2. Empirical requirements

These are requirements established by verified physical/runtime evidence. They remain authoritative while the evidence remains applicable to the supported runtime.

### 3. Planning assumptions

These include predicted blockers, expected workflow sequences, theoretical prerequisites, estimates, proposed architecture, campaign sizes, expected CAPTCHA behavior, and other statements created before sufficient physical evidence existed.

Planning assumptions are explicitly revisable.

## Evidence hierarchy

When sources disagree, use this order:

1. Verified physical behavior on the supported runtime.
2. Durable production-like evidence, logs, and external outcomes.
3. Repeated real-runtime observations.
4. Faithful integration/end-to-end tests.
5. Focused automated/unit tests.
6. Architecture assumptions and theoretical models.
7. Roadmap, blueprint, schedule, and planning predictions.

The hierarchy is not permission to bypass safety. It determines which description of system behavior should be trusted when evidence conflicts.

## Adaptation protocol

When reality differs from a plan:

1. Capture the observed behavior.
2. Separate fact from interpretation.
3. Classify the conflicting rule as an invariant, empirical requirement, or planning assumption.
4. Corroborate the observation when useful and reasonably possible.
5. Protect real safety boundaries.
6. Update the issue, roadmap, acceptance criteria, architecture assumption, priority, or estimate that is now stale.
7. Add regression coverage when the real behavior can be faithfully represented.
8. Stop obsolete work that exists only to satisfy a superseded assumption.

Do not make the owner repeatedly perform real-world actions simply to prove a theoretical scenario that is not occurring naturally.

## Example: Lever CAPTCHA

The earlier Lever planning treated post-CAPTCHA recovery as an important certification concern. Subsequent native Android Chrome operation produced 30+ owner-reported real application runs without CAPTCHA. CAPTCHA had been associated with the older Chromium lane, which was abandoned for separate runtime/reliability reasons.

The evidence-driven response is:

- do not hunt for CAPTCHA;
- do not force or manufacture CAPTCHA;
- do not hold Lever certification open waiting for CAPTCHA;
- retain safe CAPTCHA detection and human-only handling as dormant exception behavior;
- exercise and strengthen that branch if CAPTCHA naturally appears in the supported runtime;
- focus current certification work on the failures and transitions that actually occur: confirmation reconciliation, duplicate suppression, Answer Vault resume behavior, retained-target continuity, and stranded-state recovery.

This is not lowering the safety bar. It is moving effort from an unobserved theoretical prerequisite to observed reliability requirements while preserving the security boundary.

## Certification interpretation

Certification is an evidence-backed claim about the current supported path. It is not proof that every scenario predicted by an older blueprint occurred.

A certification gate should answer:

- What behavior are we claiming?
- What genuine safety invariants protect that behavior?
- What physical or faithful runtime evidence supports the claim?
- What observed failure modes remain unresolved?
- Are any checklist items merely historical planning assumptions with no current evidence of relevance?

If a gate cannot explain why a requirement still matters, the requirement must be reviewed rather than obeyed mechanically.

## Roadmap maintenance

Roadmaps should record both the current plan and the evidence that caused meaningful changes. When a major assumption is retired, document why. This prevents future contributors from resurrecting obsolete work because they found an older plan without its runtime context.

The goal is not constant improvisation. The goal is disciplined adaptation: **stable invariants, measurable evidence, revisable assumptions.**