# Contributing to JobTomatik

Start with [current status](docs/PROJECT_STATUS.md), [the product contract](docs/PRODUCT.md), [AGENTS.md](AGENTS.md) and [the Famiglia roster](docs/GOVERNANCE.md). The final direction is reliable policy-bounded autonomous job hunting. Current supervised operation is a rollout stage.

## Before editing

1. Inspect current main and active claims on [issue #252](https://github.com/TheHighBrid/JobTomatik/issues/252).
2. Claim a bounded task, dedicated branch, base SHA, file scope and acceptance checks.
3. Reuse existing code and fixtures. Respect another contributor's active lane.
4. Use project aliases for presentation while preserving actual authors and account identities.

## Pull requests

Explain the concrete problem and resulting behavior. Include exact head/tree identity, relevant checks, evidence references, unresolved findings and whether anything was deployed. Distinguish synthetic tests from real-runtime and employer outcomes. Do not claim readiness from code presence or a single green job.

Run checks appropriate to the change. Runtime changes need meaningful regression evidence; documentation changes need valid links, coherent claims and clean diffs. Required checks and independent integration review still apply. A contributor's focused tests do not authorize self-merging its lane.

## Invariants

Preserve authentication, ownership, target integrity, atomic duplicate protection, truthful outcomes, privacy and operational release controls. Never automatically retry an uncertain submission, infer sensitive answers, bypass human verification or publish secrets/applicant data. Repository contribution permission does not grant real-world submission or spending authority.

## Handoff and reporting

Record what changed, how it was verified, exact source identity, runtime/deployment boundary, blockers and one next step. Update current status when evidence changes it. Preserve historical artifacts and notices. Report security concerns through [SECURITY.md](SECURITY.md); see [NOTICE.md](NOTICE.md) for current licensing and attribution scope.
