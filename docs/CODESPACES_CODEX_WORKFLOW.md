# GitHub Codespaces and Codex workflow

This guide turns the JobTomatik repository into a browser-accessible Linux development workstation and defines a low-conflict parallel-agent workflow.

The Codespace does not change JobTomatik's product behavior, adapter maturity, campaign evidence, or release gates. It is development infrastructure only.

## What the Codespace contains

The repository dev container installs and configures:

- Python 3.11 in `.venv`;
- Node.js 20.19 and npm;
- Java 21 for the existing Android toolchain contract;
- backend dependencies, including FastAPI, Celery, Redis, PostgreSQL, and Playwright;
- Playwright Chromium and its Linux dependencies;
- PostgreSQL and Redis command-line clients;
- GitHub CLI;
- Docker and Docker Compose through Docker-in-Docker;
- VS Code browser extensions for Python, JavaScript, Docker, YAML, formatting, and GitHub pull requests;
- automatic forwarding for frontend port `3000` and API ports `8000` and `8010`.

The default startup keeps all real-submission and autonomous release gates at their repository-safe values.

## Create the Codespace from Android

1. Open the JobTomatik repository on GitHub in Chrome.
2. Tap **Code**.
3. Open the **Codespaces** tab.
4. Create a Codespace from the branch you intend to work on.
5. Let the `postCreateCommand` finish. It creates `.venv`, installs backend and frontend dependencies, installs Playwright Chromium, and creates a local `backend/.env` only when one does not already exist.
6. The `postStartCommand` starts PostgreSQL, Redis, FastAPI, Celery, and the React frontend.
7. Open the forwarded port named **JobTomatik frontend**.

A smaller Codespaces machine is suitable for most editing and focused tests. Use a larger machine only for Android builds or the broadest verification runs, and remain within the account's available Codespaces quota.

## Daily commands

Run these from the repository root.

```bash
# Start or repair the complete local stack
bash scripts/codespaces/start.sh

# Show tool versions, containers, service health, and recent logs
bash scripts/codespaces/doctor.sh

# Run diagnostics plus the canonical fast verification gate
bash scripts/codespaces/doctor.sh --test

# Stop application processes and local service containers
bash scripts/codespaces/stop.sh
```

Useful direct checks:

```bash
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh fast
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh backend-tests
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh frontend
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh deployment
PYTHON_BIN=.venv/bin/python bash scripts/verify.sh full
```

## Local URLs inside the Codespace

```text
Frontend: http://127.0.0.1:3000
API:      http://127.0.0.1:8000
API docs: http://127.0.0.1:8000/docs
```

Use the **Ports** panel to open the forwarded browser URLs. The public-looking Codespaces URL maps back to the private forwarded port according to the port visibility selected in GitHub.

The Vite development server proxies `/api` and `/uploads` to the backend. Docker Compose continues using the `backend` service hostname, while the Codespaces startup script supplies `VITE_DEV_PROXY_TARGET=http://127.0.0.1:8000` for local processes.

## Logs and troubleshooting

Runtime logs are written to:

```text
.codespaces/logs/backend.log
.codespaces/logs/celery.log
.codespaces/logs/frontend.log
.codespaces/logs/celery-beat.log
```

The normal worker runs automatically. Celery Beat remains opt-in to avoid unnecessary background load:

```bash
JOBTOMATIK_START_BEAT=1 bash scripts/codespaces/start.sh
```

When startup fails:

```bash
bash scripts/codespaces/doctor.sh
bash scripts/codespaces/stop.sh
bash scripts/codespaces/start.sh
```

When dependencies or the dev container configuration change, use the Codespaces command palette and run **Codespaces: Rebuild Container**.

## Codex repository setup

Codex reads `AGENTS.md` for repository-specific operating instructions. The file points agents to the canonical toolchain, verification script, cooperation board, product direction, and safety boundaries.

For each Codex task:

1. Create or select one GitHub issue.
2. Choose one work lane and a dedicated branch.
3. Record the branch, base SHA, intended files, exclusions, and acceptance tests on issue `#252` or its successor coordination issue.
4. Give Codex a bounded task with exact outputs and tests.
5. Open a draft pull request early.
6. Review the diff and terminal evidence.
7. Run the canonical affected verification gates before merging.
8. Refresh from current `main` before final validation.

Do not ask several agents to implement broad changes against the same branch. Parallelism should split ownership, not multiply merge conflicts.

## Recommended parallel lanes

### Agent 1: FastAPI job-source adapter interface

Primary ownership:

```text
backend/app/services/
backend/app/schemas/
backend/app/api/
focused backend adapter tests
```

Prompt template:

```text
Implement the linked issue for the FastAPI job-source adapter interface. Work only in Lane A on a dedicated branch. Preserve current adapter maturity and all fail-safe release defaults. Read AGENTS.md, the cooperation board, existing adapter contracts, and focused tests first. Add deterministic tests and run the smallest affected suite plus scripts/verify.sh fast. Do not change frontend, migrations, campaign evidence, or live-submission gates unless the issue explicitly requires coordinated work.
```

### Agent 2: Playwright selector-health tests

Primary ownership:

```text
browser and retained-session services
selector fixtures
browser-focused tests
selector-health reporting
```

Prompt template:

```text
Implement selector-health coverage for the linked issue in Lane B. Do not click final submit, enable live execution, bypass third-party controls, or fabricate confirmation evidence. Prefer deterministic fixtures and explicit degraded/blocked states. Run focused browser tests and scripts/verify.sh fast, then report exact commands and results.
```

### Agent 3: Application review queue UI

Primary ownership:

```text
frontend/src/
frontend runtime tests
accessibility and responsive behavior
existing API client integration
```

Prompt template:

```text
Implement the linked application review queue UI issue in Lane C. Preserve existing backend contracts unless a coordinated backend issue is linked. Include loading, empty, error, blocked, and success states; keyboard access; mobile behavior; and focused runtime tests. Run npm test, npm run build, and scripts/verify.sh fast.
```

### Agent 4: Database migrations and test coverage audit

Primary ownership:

```text
backend/app/models/
backend/alembic/
backend/tests/
scripts/verify.sh only when the issue requires verification changes
```

Prompt template:

```text
Audit and implement the linked migration or coverage issue in Lane D. Verify upgrade paths, do not rewrite retained evidence, and do not weaken release contracts. Run the migration smoke test, affected backend tests, and scripts/verify.sh fast. Report any untested state transition or schema risk as a blocker rather than guessing.
```

### Claude or another reviewer: architecture and edge cases

Reviewer focus:

- architecture consistency;
- state-machine gaps;
- duplicate and replay protection;
- truthful applicant-data handling;
- confirmation-evidence requirements;
- safety and release-gate drift;
- migration and rollback risk;
- missing negative tests.

The reviewer should normally inspect and comment on an existing draft pull request instead of creating a competing implementation branch.

## Pull request handoff receipt

Every agent should include:

```text
Repository state independently verified:
Accepted scope:
Rejected or excluded scope:
Base SHA:
Head SHA:
Files inspected:
Files changed:
Commands run:
Exact results:
Generated artifacts:
Known blockers:
Safety boundaries preserved:
Files intentionally unchanged:
Recommended integration action:
```

## Cost discipline

JobTomatik's default runtime remains usable without paid APIs. Codespaces usage is separate infrastructure consumption, so stop inactive Codespaces and use the smallest machine that can complete the current task. Local Termux and Ubuntu PRoot remain valid zero-cost execution paths.
