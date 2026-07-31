# Repository and Future-Task Readiness Audit

**Audit date:** 2026-07-31  
**Scope:** repository health, dependency integrity, roadmap ordering, future execution readiness, and autonomy-goal alignment

## Decision

The implementation remains aligned with the owner's fully autonomous end goal and preserves the required evidence, idempotency, recovery, circuit-breaker, handoff, and kill-switch controls. Current retained evidence does **not** authorize a real submission or an adapter promotion.

The roadmap sequence is viable after closing one planning gap: it previously selected an autonomous candidate and later attempted a live unattended pilot without an explicit checkpoint that actually made the autonomous-certification decision. Day 35 now requires that separate, evidence-backed promotion or explicitly blocks Day 39.

## Corrections made

1. Pinned `react-router-dom` to current 7.18.2 instead of accepting npm's unsafe downgrade suggestion. npm reports one upstream RSC-only CSRF advisory with no patched published version; JobTomatik does not enable React Server Components or React Router server actions. The audit gate allows only that exact advisory and will fail on every new production finding.
2. Added `bash scripts/verify.sh dependencies`, which checks the installed Python dependency graph and audits production frontend dependencies against the narrow documented exception.
3. Clarified that the published root v1.00 metadata and the reserved Android v2.00 development identity intentionally describe different artifacts until the v2.00 release is cut.
4. Added dependency-order semantics and a cross-phase prerequisite map so accelerated preparation cannot be mistaken for evidence completion.
5. Added the missing autonomous-promotion decision before any live unattended pilot.

## Truthful current checkpoint

- Phase 1 controls are retained as passed evidence.
- The Lever target corpus is locked, but the canonical retained readiness remains 0/30 qualifying Phase A dry runs.
- Lever Phase B launch contains no selected applications and no supervised confirmations.
- Greenhouse supervised and autonomous promotion gates remain incomplete.
- No adapter is currently `certified_autonomous`; real submission and autopilot defaults remain disabled.
- Read-only future-day evaluators may be implemented and tested early, but their blocked result is not roadmap completion.

## Ready-to-run gate ladder

Run from a clean checkout with the canonical versions in `.jobtomatik-toolchain.env`:

```bash
bash scripts/verify.sh bootstrap
bash scripts/verify.sh fast
bash scripts/verify.sh dependencies
bash scripts/verify.sh backend
bash scripts/verify.sh frontend
bash scripts/verify.sh deployment
bash scripts/verify.sh android
```

Use `bash scripts/verify.sh full` for the deterministic release matrix. Browser, Android, Docker, external-site dry runs, signing, and live pilot evidence still require their documented environments or user gates; local unit success must not replace those lanes.

## Future package-change rule

For each dependency update:

1. keep the lockfile and manifest in the same change;
2. prefer the smallest supported patch/minor update and review breaking changes before a major update;
3. run the dependency gate plus every affected backend/frontend/browser/Android lane;
4. regenerate only evidence whose producer or schema changed;
5. never promote maturity from package availability or synthetic tests alone;
6. record environmental skips as blockers for the relevant release gate, not as passes.

## Remaining external or user-gated work

The repository cannot pre-create truthful legal answers, choose real jobs, complete CAPTCHA/MFA/identity checks, supply private credentials/signing keys, manufacture real confirmation evidence, or approve maturity promotion. Each relevant roadmap checkpoint already calls for the smallest necessary user action. All other implementation, fixture, audit, and dry-run preparation remains automation-owned.
