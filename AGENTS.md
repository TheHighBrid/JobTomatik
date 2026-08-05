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

## Multi-agent cooperation

Multiple AI contributors may work in parallel when the repository owner authorizes a task split.

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

The integration lead named on the cooperation board owns cross-branch reconciliation and combined gate review. Passing focused tests does not authorize an agent to merge its own lane or execute a user-gated action.

## Decision rule

When implementation safety and product direction appear to conflict, do not unilaterally change the product direction. Present the engineering tradeoff and implement the option selected by the repository owner.

## Codespaces workbench

The browser-accessible development environment is defined by:

- `.devcontainer/devcontainer.json`
- `.devcontainer/Dockerfile`
- `scripts/codespaces/bootstrap.sh`
- `scripts/codespaces/start.sh`
- `scripts/codespaces/doctor.sh`
- `scripts/codespaces/stop.sh`
- `docs/CODESPACES_CODEX_WORKFLOW.md`

The canonical toolchain remains `.jobtomatik-toolchain.env`. Do not create a competing version matrix in agent prompts or setup scripts.

Common commands from the repository root:

```bash
bash scripts/codespaces/start.sh
bash scripts/codespaces/doctor.sh
bash scripts/codespaces/doctor.sh --test
bash scripts/codespaces/stop.sh
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh fast
```

## Parallel implementation lanes

Choose one primary lane for each issue and branch. Record any required cross-lane file before editing it.

### Lane A: ATS and backend behavior

Primary scope:

- `backend/app/services/`
- adapter-specific API and schema files
- focused adapter and backend tests

Preserve adapter maturity, release gates, duplicate protection, and confirmation-evidence contracts unless the issue explicitly changes them with evidence and tests.

### Lane B: Playwright and selector reliability

Primary scope:

- retained-browser and Playwright services
- selector fixtures and health reporting
- browser-focused tests

Never enable final submission merely to exercise selector coverage. Use deterministic fixtures and explicit blocked or degraded states.

### Lane C: Application review user interface

Primary scope:

- `frontend/src/`
- frontend runtime tests
- accessibility, responsive behavior, and existing API integration

Do not silently redesign backend contracts. Link a coordinated backend issue when a contract change is necessary.

### Lane D: Database, migrations, and verification

Primary scope:

- SQLAlchemy models
- Alembic revisions
- migration smoke tests
- dependency, release-contract, and verification coverage

Every schema change must include a validated upgrade path and appropriate tests. Do not rewrite retained evidence to satisfy a migration.

### Reviewer lane

Review architecture, state transitions, truthful data handling, duplicate and replay protection, confirmation evidence, safety boundaries, migration risk, and missing negative tests. Reviewers should normally comment on the active draft pull request rather than create a competing implementation.

## Verification expectations

Run the smallest relevant checks during implementation and the canonical `fast` gate before proposing integration. Use broader modes when the affected surface requires them.

```bash
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh fast
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh backend-tests
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh frontend
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh deployment
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh full
```

A pull request must report the exact commands run and exact results. Do not claim a test passed when it was not executed.
