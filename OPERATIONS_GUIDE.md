# JobTomatik Operations Guide

This guide explains how JobTomatik works from an operator's point of view, where the main controls live, what each major switch does, and how to move between safe development, supervised testing, and later autonomous operation without guessing.

The goal is not to repeat every implementation detail. It is to give the repository owner a clear control panel for the whole system.

## 1. The system in one picture

```text
Android app / browser UI
        |
        v
React + Capacitor frontend
        |
        | HTTP API
        v
FastAPI backend -----------------> SQLite or PostgreSQL
        |
        +-------------------------> Redis
        |                              |
        |                              v
        |                         Celery worker
        |                              |
        |                              v
        +-------------------------> Playwright / Chromium
                                       |
                                       v
                                Employer / ATS form
                                       |
                                       v
                              Confirmation evidence
```

The major parts are:

| Component | What it does | Typical location |
|---|---|---|
| Frontend | User interface for profile, jobs, applications, settings, review, and controls | `frontend/` |
| FastAPI backend | Main API, policy decisions, authentication, application state, approvals, evidence, settings | `backend/app/` |
| Database | Stores users, jobs, applications, policies, attempts, evidence, and operational state | SQLite locally, PostgreSQL optionally |
| Redis | Queue and coordination layer for background work | local Redis on Android/Termux |
| Celery worker | Runs scraping, application preparation, browser automation, follow-up jobs, and background tasks | `backend/app/tasks/` |
| Celery Beat | Scheduled task trigger for unattended operation | started by Android stack manager when configured |
| Browser runtime | Opens or attaches to Chromium and performs supported form work | Playwright or Android CDP |
| ATS adapters | Platform-specific application logic such as Greenhouse or Lever | backend services/adapters |
| Evidence and certification | Proves what happened and whether a release or adapter is ready | `backend/evidence/`, `docs/operations/`, certification services |
| Android stack manager | Starts, stops, verifies, and attests the local Android runtime | `backend/scripts/manage_android_stack.sh` |

## 2. The normal JobTomatik flow

Think of JobTomatik as a pipeline:

```text
Discover job
-> qualify and score
-> create application record
-> prepare materials
-> resolve real employer/ATS target
-> fill supported form
-> stop at any required human/security boundary
-> submit only when the current operating profile allows it
-> verify employer confirmation
-> record evidence
-> prevent duplicates
-> track and follow up
```

The frontend is the dashboard. FastAPI is the decision center. Redis and Celery are the conveyor belt. Chromium is the hands. The database and evidence layer are the memory and audit trail.

## 3. Where the controls actually live

There are four control layers.

### Layer A: core environment configuration

Primary files:

- `.env.example`
- `backend/.env`
- `backend/app/config.py`

`backend/.env` is the normal local source of truth for core settings.

### Layer B: unattended automation configuration

Primary file:

- `backend/app/services/operations_settings.py`

These values also fall back to `backend/.env` unless `JOBTOMATIK_OPERATIONS_ENV_FILE` points somewhere else.

### Layer C: per-user operational settings

The backend API also stores user-specific automation preferences such as allowed platforms, employer allow lists, quiet hours, and similar policy choices.

These are not the same as global environment switches. A user setting cannot override a global kill switch or a disabled release gate.

### Layer D: runtime-only Android controls

Primary files:

- `backend/scripts/manage_android_stack.sh`
- `backend/scripts/jobtomatik_termux_wrapper.sh`
- runtime identity and acceptance scripts

These identify the exact running commit, runtime role, Redis instance, frontend artifact, and browser bridge.

## 4. The master switchboard

### Emergency and consequential switches

| Switch | Default | What it controls | Operator meaning |
|---|---:|---|---|
| `AUTOMATION_GLOBAL_KILL_SWITCH` | `false` | Stops scheduled automation, platform automation, live submission, and retained-browser resume before browser work | Emergency stop. Set `true` when you need the whole automation path frozen |
| `ALLOW_REAL_APPLICATION_SUBMIT` | `false` | Global permission layer for non-dry-run application submission | Keep off during development and shadow testing |
| `ALLOW_REAL_FOLLOWUP_SEND` | `false` | Permission for actual recruiter or hiring-team email sending | Separate from application submission permission |
| `AUTOPILOT_ENABLED` | `false` | Enables scheduled unattended operation | Does not by itself authorize a live application |
| `ENABLE_RESUMABLE_HANDOFFS` | `false` | Allows retained browser handoffs during approved non-dry-run flows | Dry runs can still retain required human-verification boundaries automatically |
| `GREENHOUSE_SUPERVISED_PILOT_ENABLED` | `false` | Greenhouse reviewed real-submission pilot gate | Used only with the other required submission and approval checks |
| `LEVER_SUPERVISED_PILOT_ENABLED` | `false` | Lever reviewed real-submission pilot configuration | On Android, persisted values are deliberately not enough to reopen Lever submission authority |

### Important rule

A switch being `true` does not automatically mean JobTomatik will submit.

Real execution is intentionally layered. Depending on the platform and runtime, JobTomatik can also require:

- adapter maturity;
- exact application identity;
- exact payload binding;
- one-time approval;
- runtime attestation;
- process-bound supervised runtime authority;
- duplicate checks;
- confirmation evidence requirements;
- user or policy eligibility;
- platform-specific release gates.

This is why flipping one variable does not bypass the rest of the system.

## 5. Core configuration switches

The canonical defaults below come from `.env.example` and `backend/app/config.py`.

### Runtime profile

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test`, or `production` |
| `ENABLE_API_DOCS` | `true` | Enables FastAPI interactive API documentation |
| `JOBTOMATIK_RUNTIME_REVISION` | empty | Exact Git commit the process claims to run |
| `JOBTOMATIK_EXPECTED_REVISION` | empty | Exact Git commit the deployment expects |
| `JOBTOMATIK_RUNTIME_ROLE` | `unknown` | Identifies `api`, `worker`, `beat`, `cli`, `ci`, and similar roles |

For Android Runtime V2, runtime and expected revision must match the exact deployed commit.

### Database and queue

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./jobtomatik.db` | Main database connection |
| `POSTGRES_PASSWORD` | local example value | Docker PostgreSQL password |
| `REDIS_URL` | `redis://localhost:6379/0` | Standard Redis/Celery connection |

The Android managed stack currently uses a dedicated Android Redis URL internally, defaulting to Redis DB 1, so do not assume the shell `.env` Redis value alone describes the final managed runtime.

### Security

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | placeholder | Authentication and security root. Must be strong for production or consequential operation |
| `ANSWER_VAULT_KEY` | empty | Optional separate encryption key for approved answer policies |
| `AUTONOMY_CERTIFICATION_SIGNING_KEY` | empty | Trust root for signed certified-autonomous release manifests |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` | Login token lifetime |
| `CORS_ORIGINS` | local frontend and Capacitor origins | Which credentialed frontends may call the API |

Important: production, real submission, real follow-up, or supervised pilot operation rejects a placeholder `SECRET_KEY`.

### AI

| Variable | Default | Purpose |
|---|---|---|
| `AI_PROVIDER` | `template` | Uses local template generation unless changed |
| `ANTHROPIC_API_KEY` | empty | Optional Anthropic API credential |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Configured Anthropic model |

`AI_PROVIDER=template` keeps the app usable without a paid AI provider.

### Email

| Variable | Default | Purpose |
|---|---|---|
| `SENDGRID_API_KEY` | empty | Enables real configured email delivery |
| `FROM_EMAIL` | `noreply@jobtomatik.com` | Sender address |
| `ALLOW_REAL_FOLLOWUP_SEND` | `false` | Independent live recruiter-follow-up permission |
| `SUPERVISED_FOLLOWUP_MAX_SCHEDULE_DAYS` | `30` | Maximum future scheduling horizon for supervised follow-up |

An application submission approval does not imply recruiter email approval.

### Job discovery and demo data

| Variable | Default | Purpose |
|---|---|---|
| `DEV_MOCK_JOBS` | `false` | Uses demo/mock job results for local UI work |
| `RAPIDAPI_KEY` | empty | Optional external job-board integration key |

Keep `DEV_MOCK_JOBS=false` for real job-search operation.

## 6. Browser controls

| Variable | Default | Purpose |
|---|---|---|
| `APPLICATION_BROWSER_PROFILE_DIR` | `browser_profiles/jobtomatik-operator` | Persistent Chromium profile |
| `APPLICATION_BROWSER_HEADLESS` | `false` in `.env.example` | Shows or hides the browser UI |
| `APPLICATION_BROWSER_EXECUTABLE` | empty | Optional explicit Chromium/Chrome path |
| `APPLICATION_BROWSER_CDP_ENDPOINT` | empty | Attach to an already-running Chromium through Chrome DevTools Protocol |
| `APPLICATION_TARGET_HUMAN_WAIT_SECONDS` | `0` | Optional worker-side wait before returning a human handoff |

### Android browser model

On Android, the preferred pattern is:

```env
APPLICATION_BROWSER_CDP_ENDPOINT=http://127.0.0.1:9222
```

Chromium runs natively in Termux. The Ubuntu PRoot backend attaches to it over CDP. When CDP is configured, JobTomatik does not own the external Chromium process and should not terminate it.

## 7. Autopilot controls

These are read by `backend/app/services/operations_settings.py`.

| Variable | Default | Meaning |
|---|---:|---|
| `AUTOPILOT_ENABLED` | `false` | Global scheduled automation enable |
| `AUTOPILOT_DEFAULT_DAILY_CAP` | `5` | Default maximum automated actions per day |
| `AUTOPILOT_DEFAULT_WEEKLY_CAP` | `20` | Default maximum automated actions per week |
| `AUTOPILOT_QUIET_HOURS_START_UTC` | `0` | Quiet-hours start |
| `AUTOPILOT_QUIET_HOURS_END_UTC` | `6` | Quiet-hours end |
| `AUTOPILOT_FAILURE_THRESHOLD` | `3` | Number of recent failures that trips the breaker |
| `AUTOPILOT_FAILURE_WINDOW_MINUTES` | `60` | Failure counting window |
| `AUTOPILOT_CIRCUIT_BREAKER_MINUTES` | `120` | How long the breaker pauses automated work |
| `AUTOPILOT_STALE_ATTEMPT_MINUTES` | `30` | When an old in-flight attempt becomes eligible for bounded recovery |
| `AUTOPILOT_DISABLED_PLATFORMS` | empty | Comma-separated platform block list or `all` |
| `JOBTOMATIK_OPERATIONS_ENV_FILE` | unset | Optional alternate file for operations settings |

### How to stop one platform

Example:

```env
AUTOPILOT_DISABLED_PLATFORMS=lever
```

Multiple:

```env
AUTOPILOT_DISABLED_PLATFORMS=lever,ashby
```

Everything:

```env
AUTOPILOT_DISABLED_PLATFORMS=all
```

## 8. Supervised platform pilot controls

### Greenhouse

The documented Greenhouse reviewed pilot uses layered authorization.

At minimum, the environment gates are:

```env
ALLOW_REAL_APPLICATION_SUBMIT=true
GREENHOUSE_SUPERVISED_PILOT_ENABLED=true
```

Those values still do not replace exact approval, target validation, duplicate checks, confirmation requirements, or other release gates.

### Lever on Android

Lever has an extra protection.

In `android_managed` runtime mode, stale persisted values such as:

```env
ALLOW_REAL_APPLICATION_SUBMIT=true
LEVER_SUPERVISED_PILOT_ENABLED=true
```

are deliberately not trusted as direct submission authority.

The API and worker require the temporary supervised Lever runtime lease at the exact execution boundary. This prevents a reboot, update, or stale `.env` file from silently reopening a Lever live-submit window.

Operational consequence: do not treat the Lever Android path as a simple two-switch feature toggle.

## 9. Resumable handoff controls

| Variable | Default | Purpose |
|---|---|---|
| `ENABLE_RESUMABLE_HANDOFFS` | `false` | Extends retained sessions to approved non-dry-run flows |
| `JOBTOMATIK_BROWSER_NODE_ID` | `local-node` | Identifies browser-session affinity |
| `HANDOFF_STORAGE_DIR` | `handoff_sessions` | Retained handoff storage directory |

Human handoffs exist for boundaries such as:

- CAPTCHA;
- MFA;
- login;
- identity or account checks;
- navigation problems requiring human interaction.

JobTomatik preserves state and resumes. It does not bypass those security boundaries.

## 10. Evidence-path configuration

These are not ordinary on/off switches. They tell the runtime where certification and pilot evidence lives.

### Greenhouse

```env
GREENHOUSE_PILOT_BASELINE_PATH=evidence/greenhouse-phase-a-baseline.csv
GREENHOUSE_PILOT_LEDGER_PATH=evidence/greenhouse-pilot-ledger.jsonl
GREENHOUSE_PILOT_READINESS_JSON_PATH=evidence/greenhouse-pilot-readiness.json
GREENHOUSE_PILOT_READINESS_MARKDOWN_PATH=evidence/greenhouse-pilot-readiness.md
```

### Lever

```env
LEVER_PILOT_BASELINE_PATH=evidence/lever-phase-a-baseline.csv
LEVER_PILOT_LEDGER_PATH=evidence/lever-pilot-ledger.jsonl
LEVER_PILOT_READINESS_JSON_PATH=evidence/lever-pilot-readiness.json
LEVER_PILOT_READINESS_MARKDOWN_PATH=evidence/lever-pilot-readiness.md
```

These paths should not be casually redirected during certification or campaign work because the evidence files are part of the release truth.

## 11. Android managed runtime controls

The Android stack manager adds another set of runtime variables.

| Variable | Typical/default behavior | Purpose |
|---|---|---|
| `JOBTOMATIK_RUNTIME_MODE` | `android_managed` under the managed stack | Tells the backend it is inside the controlled Android runtime |
| `JOBTOMATIK_RUNTIME_REVISION` | current Git SHA | Exact code revision running |
| `JOBTOMATIK_EXPECTED_REVISION` | same SHA | Deployment attestation target |
| `JOBTOMATIK_RUNTIME_ROLE` | assigned per process | `api`, `worker`, `beat`, and similar |
| `JOBTOMATIK_ANDROID_REDIS_URL` | `redis://localhost:6379/1` | Android managed Redis queue/database |
| `JOBTOMATIK_LEGACY_ANDROID_REDIS_URL` | `redis://localhost:6379/0` | Legacy Android Redis value used during migration/repair logic |
| `JOBTOMATIK_FRONTEND_RUNTIME_MODE` | `static_artifact` | Required Android Runtime V2 frontend mode |
| `JOBTOMATIK_FRONTEND_ARTIFACT_ROOT` | runtime-generated path | Exact static frontend artifact location |

Android Runtime V2 rejects a mismatched expected revision or unsupported frontend runtime mode.

That means the API, worker, Beat, frontend artifact, and acceptance checks are intended to prove they all belong to the same deployment instead of merely proving that some process is running.

## 12. Frontend control

```env
VITE_API_URL=http://127.0.0.1:8010
VITE_JOBTOMATIK_RUNTIME_REVISION=
```

For the installed Android app, the backend address is normally:

```text
http://127.0.0.1:8010
```

Do not append `/api` when entering the server URL in the app.

## 13. Safe operating profiles

### Profile A: development and UI work

Use this when changing code, UI, or general workflow logic.

```env
APP_ENV=development
DEV_MOCK_JOBS=false
ALLOW_REAL_APPLICATION_SUBMIT=false
ALLOW_REAL_FOLLOWUP_SEND=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
LEVER_SUPERVISED_PILOT_ENABLED=false
AUTOPILOT_ENABLED=false
ENABLE_RESUMABLE_HANDOFFS=false
AUTOMATION_GLOBAL_KILL_SWITCH=false
```

This keeps the system usable but consequential behavior off.

### Profile B: verification, CI, dry runs, shadow campaigns

Use the repository verification scripts and keep these controls off:

```env
ALLOW_REAL_APPLICATION_SUBMIT=false
ALLOW_REAL_FOLLOWUP_SEND=false
AUTOPILOT_ENABLED=false
ENABLE_RESUMABLE_HANDOFFS=false
```

Shadow and dry-run tooling adds its own evidence boundaries. Do not enable real submission to make a dry-run or shadow gate pass.

### Profile C: emergency freeze

Set:

```env
AUTOMATION_GLOBAL_KILL_SWITCH=true
AUTOPILOT_ENABLED=false
ALLOW_REAL_APPLICATION_SUBMIT=false
ALLOW_REAL_FOLLOWUP_SEND=false
```

This is the red button.

After resolving the incident, review the recovery runbook before restoring automation.

### Profile D: supervised real-world pilot

Do not copy a generic profile blindly.

The required controls depend on:

- platform;
- exact application;
- current adapter maturity;
- current runtime;
- one-time approval state;
- current evidence campaign;
- runtime attestation.

For Greenhouse, the environment portion may include the global real-submit gate plus the Greenhouse pilot flag.

For Lever Android, use the dedicated supervised control-request/runtime-lease workflow. Persisted `.env` flags alone are intentionally insufficient.

### Profile E: certified autonomous release

This is the target operating model, but it should be enabled only after the repository's certification process accepts the release manifest, adapter maturity, recovery behavior, caps, duplicate prevention, confirmation evidence, incident controls, and operator-selected rollout policy.

`AUTOPILOT_ENABLED=true` is one part of that release, not the whole certification.

## 14. How to change a switch correctly

For normal local/Android configuration:

1. Edit `backend/.env`.
2. Change only the intended variable.
3. Restart the managed stack so API, worker, Beat, and policy code read a consistent configuration.
4. Run the current runtime/preflight verification before relying on the new state.

Do not assume a changed `.env` value affects an already-running process.

### Example

To disable scheduled automation:

```env
AUTOPILOT_ENABLED=false
```

Then restart and verify.

To activate the emergency stop:

```env
AUTOMATION_GLOBAL_KILL_SWITCH=true
```

Then restart or use the documented recovery/runtime control path so all relevant processes see the value.

## 15. How to start and stop the Android stack

The managed path is preferred over manually launching independent processes because it verifies runtime identity and keeps the pieces aligned.

The wrapper ultimately calls:

```bash
bash backend/scripts/manage_android_stack.sh <action>
```

Common actions are defined by the script and its wrapper. Use the repository runbooks and current script help/output rather than inventing an unsupported action name.

The manager is responsible for the controlled lifecycle of:

- FastAPI;
- Celery worker;
- Celery Beat;
- static frontend artifact;
- Redis configuration/repair;
- runtime identity receipts;
- process PID files and logs.

Runtime files live under:

```text
backend/.runtime/
```

Logs live under:

```text
backend/.runtime/logs/
```

## 16. Where to look when something is wrong

| Symptom | First places to inspect |
|---|---|
| App cannot reach backend | `VITE_API_URL`, API process, port 8010, runtime logs |
| API works but background job never runs | Redis, Celery worker, queue ownership, worker log |
| Browser cannot open/attach | `APPLICATION_BROWSER_*`, CDP endpoint, Chromium process, Playwright runtime |
| Job reaches handoff and stops | Expected when CAPTCHA/MFA/login/manual navigation boundary exists |
| Autopilot refuses to run | kill switch, `AUTOPILOT_ENABLED`, per-user policy, caps, quiet hours, disabled platform, circuit breaker |
| Real submission is blocked | global submit flag, platform gate, adapter maturity, one-time approval, runtime lease, exact target/payload validation |
| Follow-up email is blocked | `ALLOW_REAL_FOLLOWUP_SEND`, SendGrid configuration, exact follow-up approval |
| Android acceptance rejects runtime | revision mismatch, wrong Redis, stale worker/process, wrong frontend artifact, missing runtime attestation |
| Duplicate is blocked | Usually correct behavior. Check confirmation/evidence and existing application state before trying again |

## 17. The switches you should think of as the main dashboard

For day-to-day ownership, these are the most important ones to remember:

```text
AUTOMATION_GLOBAL_KILL_SWITCH
AUTOPILOT_ENABLED
ALLOW_REAL_APPLICATION_SUBMIT
ALLOW_REAL_FOLLOWUP_SEND
GREENHOUSE_SUPERVISED_PILOT_ENABLED
LEVER_SUPERVISED_PILOT_ENABLED
ENABLE_RESUMABLE_HANDOFFS
AUTOPILOT_DISABLED_PLATFORMS
AUTOPILOT_DEFAULT_DAILY_CAP
AUTOPILOT_DEFAULT_WEEKLY_CAP
APPLICATION_BROWSER_CDP_ENDPOINT
JOBTOMATIK_RUNTIME_MODE
JOBTOMATIK_RUNTIME_REVISION
JOBTOMATIK_EXPECTED_REVISION
VITE_API_URL
```

A useful mental model is:

```text
Kill switch = Can automation move at all?
Autopilot = May the scheduler initiate unattended work?
Real-submit gate = May a non-dry-run submission path exist?
Platform gate = Is this ATS inside the current rollout window?
Approval/runtime lease = Is this exact application authorized right now?
Adapter maturity = Is this platform implementation trusted enough?
Confirmation evidence = Did the employer actually receive it?
Caps/circuit breaker = Should automation continue operating today?
```

## 18. What not to do

Do not:

- turn on several consequential switches at once just to see what happens;
- change evidence paths during an active certification/campaign without a deliberate migration;
- use a placeholder `SECRET_KEY` with production or real-action settings;
- treat a dry-run success as confirmation of submission;
- treat a submit click as confirmation without employer evidence;
- repeat an application after a valid received/thank-you confirmation;
- bypass CAPTCHA, MFA, login, identity verification, assessments, or third-party security controls;
- assume persisted Lever Android flags grant current submission authority;
- manually start a mixture of old and new Android processes and assume they belong to the same revision.

## 19. Verification commands and references

Canonical full verification entry point:

```bash
bash scripts/verify.sh
```

Repository verification documentation:

- `docs/VERIFICATION.md`
- `docs/CURRENT_HEAD_FINAL_ACCEPTANCE.md`
- Android readiness and acceptance documents under `docs/`
- recovery and incident runbooks under `docs/operations/`

Android runtime acceptance and identity logic lives under:

- `backend/scripts/android_runtime_acceptance.py`
- `backend/scripts/check_runtime_identity.py`
- `backend/scripts/manage_android_stack.sh`

## 20. Operator checklist before enabling more autonomy

Before moving a consequential switch from false to true, verify:

- [ ] current `main` or release SHA is known;
- [ ] runtime SHA matches expected SHA;
- [ ] API and worker belong to the intended deployment;
- [ ] database and Redis are the intended instances;
- [ ] browser node is reachable and correct;
- [ ] adapter maturity matches the intended operating level;
- [ ] exact application/payload approval requirements are satisfied where applicable;
- [ ] duplicate prevention is healthy;
- [ ] confirmation evidence is required and working;
- [ ] recovery and circuit breaker behavior is healthy;
- [ ] daily/weekly caps are deliberate;
- [ ] platform exclusions are deliberate;
- [ ] emergency kill switch is known and tested;
- [ ] no placeholder secrets are used for consequential operation;
- [ ] evidence/certification files are current and belong to this release.

If those boxes are not true, the correct move is usually not another switch. The correct move is to repair the failing prerequisite first.

## 21. Final mental model

JobTomatik is not one giant automation switch.

It is a layered control system:

```text
UI
-> API policy
-> user settings
-> global operations policy
-> platform maturity
-> exact approval / runtime authority
-> worker queue
-> browser
-> employer confirmation
-> evidence
```

The safest way to operate it is to keep most release gates false during development, use the repository's dry-run/shadow paths to prove behavior, and promote only the specific layer whose evidence is ready.

That lets JobTomatik move toward full autonomy without turning the system into a black box.